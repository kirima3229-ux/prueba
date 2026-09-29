import base64
import time

import qrcode
import qrcode.image.svg
from axes.handlers.proxy import AxesProxyHandler
from axes.utils import reset as axes_reset
from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_not_required
from django.contrib.auth.signals import user_login_failed
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST
from django_otp import login as otp_login
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.auditoria.servicios import Accion, diferencias, instantanea, registrar
from apps.core.permisos import exento_requisitos_cuenta, requiere_admin

from .forms import (
    CambiarContrasenaForm,
    CodigoOTPForm,
    ConfirmarPasswordForm,
    EntradaForm,
    RestablecerContrasenaForm,
    UsuarioCrearForm,
    UsuarioEditarForm,
)
from .models import Usuario

CLAVE_PRE_OTP = "pre_otp"
SEGUNDOS_PRE_OTP = 300


def _destino_seguro(request, destino):
    if destino and url_has_allowed_host_and_scheme(
        destino, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return destino
    return "inicio"


@login_not_required
@sensitive_post_parameters("password")
@never_cache
@require_http_methods(["GET", "POST"])
def entrar(request):
    if request.user.is_authenticated:
        return redirect("inicio")
    form = EntradaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        # authenticate() pasa por Axes: si la cuenta está bloqueada, el
        # middleware de Axes responde con la página de bloqueo.
        usuario = authenticate(
            request,
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password"],
        )
        if usuario is None:
            form.add_error(None, "Usuario o contraseña incorrectos.")
        else:
            destino = request.POST.get("next") or request.GET.get("next")
            if usuario.tiene_2fa():
                request.session.cycle_key()
                request.session[CLAVE_PRE_OTP] = {
                    "usuario_id": usuario.pk,
                    "backend": usuario.backend,
                    "inicio": time.time(),
                    "next": destino or "",
                }
                return redirect("cuentas:verificar")
            login(request, usuario)
            return redirect(_destino_seguro(request, destino))
    return render(
        request,
        "cuentas/entrar.html",
        {"form": form, "next": request.GET.get("next", "")},
    )


@login_not_required
@never_cache
@require_http_methods(["GET", "POST"])
def verificar(request):
    """Segundo paso: código TOTP de Google Authenticator."""
    pendiente = request.session.get(CLAVE_PRE_OTP)
    if not pendiente or time.time() - pendiente["inicio"] > SEGUNDOS_PRE_OTP:
        request.session.pop(CLAVE_PRE_OTP, None)
        messages.error(request, "La verificación expiró. Entre de nuevo.")
        return redirect("cuentas:entrar")

    usuario = get_object_or_404(get_user_model(), pk=pendiente["usuario_id"], is_active=True)
    credenciales = {"username": usuario.get_username()}
    if AxesProxyHandler.is_locked(request, credenciales):
        request.session.pop(CLAVE_PRE_OTP, None)
        return render(request, "cuentas/bloqueado.html", status=429)

    form = CodigoOTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        dispositivo = None
        for candidato in TOTPDevice.objects.filter(user=usuario, confirmed=True):
            if candidato.verify_token(form.cleaned_data["codigo"]):
                dispositivo = candidato
                break
        if dispositivo is None:
            # Cuenta como intento fallido para el bloqueo de Axes.
            user_login_failed.send(
                sender=__name__,
                credentials={**credenciales, "motivo": "código 2FA incorrecto"},
                request=request,
            )
            if AxesProxyHandler.is_locked(request, credenciales):
                request.session.pop(CLAVE_PRE_OTP, None)
                return render(request, "cuentas/bloqueado.html", status=429)
            form.add_error("codigo", "Código incorrecto o vencido.")
        else:
            request.session.pop(CLAVE_PRE_OTP, None)
            usuario.backend = pendiente["backend"]
            login(request, usuario)
            otp_login(request, dispositivo)
            axes_reset(username=usuario.get_username())
            return redirect(_destino_seguro(request, pendiente.get("next")))
    return render(request, "cuentas/verificar.html", {"form": form})


@require_POST
@exento_requisitos_cuenta
def salir(request):
    logout(request)
    messages.info(request, "Sesión cerrada.")
    return redirect("cuentas:entrar")


@sensitive_post_parameters("actual", "nueva1", "nueva2")
@exento_requisitos_cuenta
def cambiar_contrasena(request):
    form = CambiarContrasenaForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = request.user
        usuario.set_password(form.cleaned_data["nueva1"])
        usuario.debe_cambiar_contrasena = False
        usuario.save(update_fields=["password", "debe_cambiar_contrasena"])
        update_session_auth_hash(request, usuario)
        registrar(request, Accion.CONTRASENA_CAMBIADA, objeto=usuario)
        messages.success(request, "Contraseña cambiada.")
        return redirect("inicio")
    return render(request, "cuentas/cambiar_contrasena.html", {"form": form})


def _qr_svg(texto: str) -> str:
    imagen = qrcode.make(texto, image_factory=qrcode.image.svg.SvgPathImage, box_size=8)
    return imagen.to_string(encoding="unicode")


@exento_requisitos_cuenta
def configurar_2fa(request):
    usuario = request.user
    confirmado = TOTPDevice.objects.filter(user=usuario, confirmed=True).first()
    if confirmado is not None:
        return render(
            request,
            "cuentas/2fa_estado.html",
            {"dispositivo": confirmado, "form": ConfirmarPasswordForm()},
        )

    # Un solo dispositivo pendiente por usuario; se reutiliza hasta confirmar.
    dispositivo = TOTPDevice.objects.filter(user=usuario, confirmed=False).first()
    if dispositivo is None:
        dispositivo = TOTPDevice.objects.create(user=usuario, name="Autenticador", confirmed=False)

    form = CodigoOTPForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        if dispositivo.verify_token(form.cleaned_data["codigo"]):
            with transaction.atomic():
                dispositivo.confirmed = True
                dispositivo.save(update_fields=["confirmed"])
                TOTPDevice.objects.filter(user=usuario).exclude(pk=dispositivo.pk).delete()
            otp_login(request, dispositivo)
            registrar(request, Accion.OTP_CONFIGURADO, objeto=usuario)
            messages.success(request, "Autenticación de dos pasos activada.")
            return redirect("inicio")
        form.add_error("codigo", "Código incorrecto. Verifique la hora de su teléfono e intente de nuevo.")

    clave_texto = base64.b32encode(dispositivo.bin_key).decode("ascii").rstrip("=")
    return render(
        request,
        "cuentas/2fa_configurar.html",
        {
            "form": form,
            "qr_svg": _qr_svg(dispositivo.config_url),
            "clave_texto": " ".join(clave_texto[i : i + 4] for i in range(0, len(clave_texto), 4)),
        },
    )


@require_POST
@sensitive_post_parameters("password")
def desactivar_2fa(request):
    usuario = request.user
    if usuario.es_admin:
        messages.error(request, "Los administradores no pueden desactivar el 2FA.")
        return redirect("cuentas:configurar_2fa")
    form = ConfirmarPasswordForm(request.POST)
    valido = form.is_valid() and usuario.check_password(form.cleaned_data["password"])
    if valido:
        valido = any(
            d.verify_token(form.cleaned_data["codigo"])
            for d in TOTPDevice.objects.filter(user=usuario, confirmed=True)
        )
    if not valido:
        messages.error(request, "Contraseña o código incorrecto.")
        return redirect("cuentas:configurar_2fa")
    TOTPDevice.objects.filter(user=usuario).delete()
    registrar(request, Accion.OTP_ELIMINADO, objeto=usuario, descripcion="Desactivado por el propio usuario")
    messages.success(request, "Autenticación de dos pasos desactivada.")
    return redirect("inicio")


# --- Administración de usuarios ------------------------------------------------


def _foto_usuario(usuario):
    foto = instantanea(usuario)
    foto["companias"] = sorted(str(c) for c in usuario.companias.all()) if usuario.pk else []
    return foto


@requiere_admin
def usuarios_lista(request):
    from axes.models import AccessAttempt

    usuarios = Usuario.objects.prefetch_related("companias")
    bloqueados = set(
        AccessAttempt.objects.filter(failures_since_start__gte=_limite_intentos()).values_list(
            "username", flat=True
        )
    )
    con_2fa = set(TOTPDevice.objects.filter(confirmed=True).values_list("user_id", flat=True))
    return render(
        request,
        "cuentas/usuarios_lista.html",
        {"usuarios": usuarios, "bloqueados": bloqueados, "con_2fa": con_2fa},
    )


def _limite_intentos():
    from django.conf import settings

    return settings.AXES_FAILURE_LIMIT


@requiere_admin
@sensitive_post_parameters("nueva1", "nueva2")
def usuario_nuevo(request):
    form = UsuarioCrearForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario = form.save()
        registrar(
            request,
            Accion.USUARIO_CREADO,
            objeto=usuario,
            cambios={"rol": usuario.get_rol_display(), "companias": [str(c) for c in usuario.companias.all()]},
        )
        messages.success(request, f"Usuario {usuario.username} creado. Deberá cambiar la contraseña al entrar.")
        return redirect("cuentas:usuarios")
    return render(request, "cuentas/usuario_form.html", {"form": form, "titulo": "Nuevo usuario"})


@requiere_admin
def usuario_editar(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    antes = _foto_usuario(usuario)
    form = UsuarioEditarForm(request.POST or None, instance=usuario, editor=request.user)
    if request.method == "POST" and form.is_valid():
        usuario = form.save()
        cambios = diferencias(antes, _foto_usuario(usuario))
        if cambios:
            registrar(request, Accion.USUARIO_MODIFICADO, objeto=usuario, cambios=cambios)
        messages.success(request, "Usuario actualizado.")
        return redirect("cuentas:usuarios")
    return render(
        request,
        "cuentas/usuario_form.html",
        {"form": form, "titulo": f"Editar usuario {usuario.username}", "usuario_obj": usuario},
    )


@requiere_admin
@sensitive_post_parameters("nueva1", "nueva2")
def usuario_restablecer_contrasena(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    form = RestablecerContrasenaForm(usuario, request.POST or None)
    if request.method == "POST" and form.is_valid():
        usuario.set_password(form.cleaned_data["nueva1"])
        usuario.debe_cambiar_contrasena = True
        usuario.save(update_fields=["password", "debe_cambiar_contrasena"])
        registrar(request, Accion.CONTRASENA_RESTABLECIDA, objeto=usuario)
        messages.success(request, f"Contraseña temporal asignada a {usuario.username}.")
        return redirect("cuentas:usuarios")
    return render(
        request,
        "cuentas/usuario_contrasena.html",
        {"form": form, "usuario_obj": usuario},
    )


@requiere_admin
@require_POST
def usuario_desbloquear(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    axes_reset(username=usuario.get_username())
    registrar(request, Accion.DESBLOQUEO, objeto=usuario)
    messages.success(request, f"Cuenta {usuario.username} desbloqueada.")
    return redirect("cuentas:usuarios")


@requiere_admin
@require_POST
def usuario_reiniciar_2fa(request, pk):
    usuario = get_object_or_404(Usuario, pk=pk)
    if usuario.pk == request.user.pk:
        messages.error(request, "Para cambiar su propio 2FA, otro administrador debe reiniciarlo.")
        return redirect("cuentas:usuarios")
    TOTPDevice.objects.filter(user=usuario).delete()
    registrar(request, Accion.OTP_ELIMINADO, objeto=usuario, descripcion="Reiniciado por administrador")
    messages.success(request, f"2FA de {usuario.username} reiniciado. Deberá configurarlo de nuevo.")
    return redirect("cuentas:usuarios")
