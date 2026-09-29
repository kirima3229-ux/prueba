from axes.signals import user_locked_out
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .servicios import Accion, registrar


@receiver(user_logged_in)
def al_entrar(sender, request, user, **kwargs):
    registrar(request, Accion.LOGIN, usuario=user, descripcion="Entrada exitosa")


@receiver(user_logged_out)
def al_salir(sender, request, user, **kwargs):
    if user is not None:
        registrar(request, Accion.LOGOUT, usuario=user)


@receiver(user_login_failed)
def al_fallar(sender, credentials, request=None, **kwargs):
    nombre = (credentials or {}).get("username", "")
    motivo = (credentials or {}).get("motivo", "usuario o contraseña incorrectos")
    registrar(
        request,
        Accion.LOGIN_FALLIDO,
        descripcion=f"Intento fallido para el usuario '{nombre[:150]}': {motivo}",
    )


@receiver(user_locked_out)
def al_bloquear(sender, request, username=None, ip_address=None, **kwargs):
    registrar(
        request,
        Accion.BLOQUEO,
        descripcion=f"Cuenta '{(username or '')[:150]}' bloqueada por intentos fallidos",
        ip=ip_address,
    )
