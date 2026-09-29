import pytest
from django.conf import settings
from django.contrib.auth.hashers import get_hasher
from django.test import Client
from django.urls import URLPattern, URLResolver, get_resolver, reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.cuentas.models import Usuario

from .conftest import CONTRASENA, cliente_de, crear_usuario, token_actual

RUTAS_PUBLICAS = {"cuentas:entrar", "cuentas:verificar"}


def _todas_las_rutas(resolver=None, prefijo=""):
    resolver = resolver or get_resolver()
    for patron in resolver.url_patterns:
        if isinstance(patron, URLResolver):
            espacio = f"{patron.namespace}:" if patron.namespace else prefijo
            yield from _todas_las_rutas(patron, espacio)
        elif isinstance(patron, URLPattern) and patron.name:
            yield prefijo + patron.name


def _url_de_prueba(nombre):
    for kwargs in ({}, {"pk": 1}, {"pk": 1, "tasas_pk": 1}, {"pk": 1, "catalogo": "departamentos"},
                   {"pk": 1, "catalogo": "departamentos", "item_pk": 1}):
        try:
            return reverse(nombre, kwargs=kwargs)
        except Exception:
            continue
    raise AssertionError(f"No se pudo construir la URL de {nombre}")


@pytest.mark.django_db
def test_ninguna_pagina_accesible_sin_sesion():
    cliente = Client()
    rutas = sorted(set(_todas_las_rutas()) - RUTAS_PUBLICAS)
    assert len(rutas) > 15
    for nombre in rutas:
        url = _url_de_prueba(nombre)
        for metodo in (cliente.get, cliente.post):
            respuesta = metodo(url)
            assert respuesta.status_code == 302, f"{nombre} respondió {respuesta.status_code} sin sesión"
            assert respuesta["Location"].startswith(reverse("cuentas:entrar")), nombre


def test_contrasenas_con_argon2():
    assert settings.PASSWORD_HASHERS[0].endswith("Argon2PasswordHasher")
    assert get_hasher().algorithm == "argon2"


@pytest.mark.django_db
def test_contrasena_guardada_con_hash(preparador):
    preparador.refresh_from_db()
    assert preparador.password.startswith("argon2$")
    assert CONTRASENA not in preparador.password


def test_politica_minimo_12_caracteres():
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        validate_password("Corta-123")
    validate_password("Una-frase-larga-y-segura-2026")


def test_sesion_expira_a_los_15_minutos():
    assert settings.SESSION_COOKIE_AGE == 15 * 60
    assert settings.SESSION_SAVE_EVERY_REQUEST is True


@pytest.mark.django_db
def test_entrada_correcta_sin_2fa(preparador):
    cliente = Client()
    respuesta = cliente.post(reverse("cuentas:entrar"), {"username": "preparador", "password": CONTRASENA})
    assert respuesta.status_code == 302
    assert cliente.get(reverse("inicio")).status_code == 200
    assert RegistroAuditoria.objects.filter(accion=Accion.LOGIN, usuario=preparador).exists()


@pytest.mark.django_db
def test_bloqueo_tras_5_intentos(preparador):
    cliente = Client()
    for _ in range(5):
        cliente.post(reverse("cuentas:entrar"), {"username": "preparador", "password": "incorrecta-123456"})
    # Aun con la contraseña correcta, la cuenta queda bloqueada.
    respuesta = cliente.post(reverse("cuentas:entrar"), {"username": "preparador", "password": CONTRASENA})
    assert respuesta.status_code == 429
    assert "bloqueada" in respuesta.content.decode()
    assert RegistroAuditoria.objects.filter(accion=Accion.LOGIN_FALLIDO).count() >= 5
    assert RegistroAuditoria.objects.filter(accion=Accion.BLOQUEO).exists()


@pytest.mark.django_db
def test_admin_desbloquea(preparador, cliente_admin):
    cliente = Client()
    for _ in range(5):
        cliente.post(reverse("cuentas:entrar"), {"username": "preparador", "password": "incorrecta-123456"})
    cliente_admin.post(reverse("cuentas:usuario_desbloquear", args=[preparador.pk]))
    respuesta = cliente.post(reverse("cuentas:entrar"), {"username": "preparador", "password": CONTRASENA})
    assert respuesta.status_code == 302
    assert RegistroAuditoria.objects.filter(accion=Accion.DESBLOQUEO).exists()


@pytest.mark.django_db
def test_entrada_con_2fa_requiere_codigo(admin):
    cliente = Client()
    respuesta = cliente.post(reverse("cuentas:entrar"), {"username": "admin", "password": CONTRASENA})
    assert respuesta["Location"] == reverse("cuentas:verificar")
    # Sin el código no hay sesión.
    assert cliente.get(reverse("inicio"))["Location"].startswith(reverse("cuentas:entrar"))

    dispositivo = TOTPDevice.objects.get(user=admin)
    cliente.post(reverse("cuentas:entrar"), {"username": "admin", "password": CONTRASENA})
    respuesta = cliente.post(reverse("cuentas:verificar"), {"codigo": token_actual(dispositivo)})
    assert respuesta.status_code == 302
    assert cliente.get(reverse("inicio")).status_code == 200


@pytest.mark.django_db
def test_codigo_2fa_incorrecto_cuenta_para_bloqueo(admin):
    cliente = Client()
    for _ in range(5):
        cliente.post(reverse("cuentas:entrar"), {"username": "admin", "password": CONTRASENA})
        respuesta = cliente.post(reverse("cuentas:verificar"), {"codigo": "000000"})
    assert respuesta.status_code == 429
    respuesta = cliente.post(reverse("cuentas:entrar"), {"username": "admin", "password": CONTRASENA})
    assert respuesta.status_code == 429


@pytest.mark.django_db
def test_admin_sin_2fa_debe_configurarlo():
    usuario = crear_usuario("nuevoadmin", Usuario.Rol.ADMIN)
    cliente = cliente_de(usuario)
    respuesta = cliente.get(reverse("empleados:lista"))
    assert respuesta["Location"] == reverse("cuentas:configurar_2fa")

    respuesta = cliente.get(reverse("cuentas:configurar_2fa"))
    assert respuesta.status_code == 200
    assert "<svg" in respuesta.content.decode()
    dispositivo = TOTPDevice.objects.get(user=usuario, confirmed=False)
    respuesta = cliente.post(reverse("cuentas:configurar_2fa"), {"codigo": token_actual(dispositivo)})
    assert respuesta.status_code == 302
    assert TOTPDevice.objects.filter(user=usuario, confirmed=True).exists()
    assert cliente.get(reverse("inicio")).status_code == 200


@pytest.mark.django_db
def test_sesion_con_2fa_sin_verificar_se_cierra(admin):
    from django.test import Client

    cliente = Client()
    cliente.force_login(admin)  # sesión sin verificar el código
    respuesta = cliente.get(reverse("cuentas:cambiar_contrasena"))
    assert respuesta["Location"] == reverse("cuentas:entrar")


@pytest.mark.django_db
def test_contrasena_temporal_obliga_a_cambiarla(compania):
    usuario = crear_usuario("temporal", Usuario.Rol.PREPARADOR, companias=[compania], debe_cambiar_contrasena=True)
    cliente = cliente_de(usuario)
    assert cliente.get(reverse("empleados:lista"))["Location"] == reverse("cuentas:cambiar_contrasena")
    respuesta = cliente.post(
        reverse("cuentas:cambiar_contrasena"),
        {"actual": CONTRASENA, "nueva1": "Otra-Contrasena-Nueva-99", "nueva2": "Otra-Contrasena-Nueva-99"},
    )
    assert respuesta.status_code == 302
    assert cliente.get(reverse("empleados:lista")).status_code == 200


@pytest.mark.django_db
def test_cabeceras_de_seguridad(cliente_preparador):
    respuesta = cliente_preparador.get(reverse("inicio"))
    assert "default-src 'self'" in respuesta["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in respuesta["Content-Security-Policy"]
    assert respuesta["X-Frame-Options"] == "DENY"
    assert respuesta["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in respuesta["Cache-Control"]


@pytest.mark.django_db
def test_csrf_activo(preparador):
    cliente = Client(enforce_csrf_checks=True)
    respuesta = cliente.post(reverse("cuentas:entrar"), {"username": "preparador", "password": CONTRASENA})
    assert respuesta.status_code == 403


@pytest.mark.django_db
def test_redireccion_externa_bloqueada(preparador):
    cliente = Client()
    respuesta = cliente.post(
        reverse("cuentas:entrar") + "?next=https://sitio-malicioso.com/",
        {"username": "preparador", "password": CONTRASENA, "next": "https://sitio-malicioso.com/"},
    )
    assert respuesta["Location"] == reverse("inicio")
