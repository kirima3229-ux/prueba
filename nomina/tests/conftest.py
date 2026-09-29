from datetime import date

import pytest
from django.test import Client
from django_otp import DEVICE_ID_SESSION_KEY
from django_otp.oath import TOTP
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.companias.models import Compania
from apps.cuentas.models import Usuario
from apps.empleados.models import Empleado

CONTRASENA = "Contrasena-Segura-2026"


def token_actual(dispositivo: TOTPDevice) -> str:
    totp = TOTP(dispositivo.bin_key, dispositivo.step, dispositivo.t0, dispositivo.digits, dispositivo.drift)
    return str(totp.token()).zfill(dispositivo.digits)


def crear_usuario(username, rol, companias=(), con_2fa=False, **extra):
    usuario = Usuario.objects.create_user(username=username, password=CONTRASENA, rol=rol, **extra)
    usuario.companias.set(companias)
    if con_2fa:
        TOTPDevice.objects.create(user=usuario, name="prueba", confirmed=True)
    return usuario


def cliente_de(usuario) -> Client:
    """Cliente con sesión iniciada (y verificada con 2FA si el usuario lo tiene)."""
    cliente = Client()
    cliente.force_login(usuario)
    dispositivo = TOTPDevice.objects.filter(user=usuario, confirmed=True).first()
    if dispositivo is not None:
        sesion = cliente.session
        sesion[DEVICE_ID_SESSION_KEY] = dispositivo.persistent_id
        sesion.save()
    return cliente


def crear_compania(nombre, ein):
    compania = Compania(nombre=nombre, frecuencia_pago=Compania.Frecuencia.SEMANAL, numero_empleados=10)
    compania.asignar_ein(ein)
    compania.cuenta_patronal_dtrh = "1234567890"
    compania.save()
    return compania


def crear_empleado(compania, numero="100", ssn="123456789", **extra):
    datos = dict(
        compania=compania,
        numero_empleado=numero,
        nombre="Juan",
        apellido_paterno="Del Pueblo",
        fecha_empleo=date(2020, 5, 1),
        tipo_pago=Empleado.TipoPago.HORA,
        tarifa="10.50",
    )
    datos.update(extra)
    empleado = Empleado(**datos)
    empleado.asignar_ssn(ssn)
    empleado.save()
    return empleado


@pytest.fixture
def compania(db):
    return crear_compania("Restaurante El Ejemplo", "660000001")


@pytest.fixture
def otra_compania(db):
    return crear_compania("Farmacia Ajena", "660000002")


@pytest.fixture
def admin(db):
    return crear_usuario("admin", Usuario.Rol.ADMIN, con_2fa=True)


@pytest.fixture
def preparador(db, compania):
    return crear_usuario("preparador", Usuario.Rol.PREPARADOR, companias=[compania])


@pytest.fixture
def lectura(db, compania):
    return crear_usuario("lectura", Usuario.Rol.LECTURA, companias=[compania])


@pytest.fixture
def cliente_admin(admin):
    return cliente_de(admin)


@pytest.fixture
def cliente_preparador(preparador):
    return cliente_de(preparador)


@pytest.fixture
def cliente_lectura(lectura):
    return cliente_de(lectura)
