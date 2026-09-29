import base64
import importlib
import io
import os
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.core import respaldo
from apps.empleados.models import Empleado

from .conftest import crear_empleado

LLAVE = os.urandom(32)


def _cifrado(datos: bytes, llave=LLAVE) -> bytes:
    salida = io.BytesIO()
    respaldo.cifrar(io.BytesIO(datos), salida, llave)
    return salida.getvalue()


@pytest.mark.parametrize("tamano", [0, 1, respaldo.TAMANO_BLOQUE - 1, respaldo.TAMANO_BLOQUE,
                                    respaldo.TAMANO_BLOQUE * 2 + 17])
def test_ida_y_vuelta(tamano):
    datos = os.urandom(tamano)
    salida = io.BytesIO()
    assert respaldo.descifrar(io.BytesIO(_cifrado(datos)), salida, [LLAVE]) == tamano
    assert salida.getvalue() == datos


def test_detecta_alteraciones():
    datos = os.urandom(respaldo.TAMANO_BLOQUE * 2 + 100)
    cifrado = _cifrado(datos)
    alterado = bytearray(cifrado)
    alterado[len(cifrado) // 2] ^= 1
    with pytest.raises(respaldo.ErrorRespaldo, match="alterado"):
        respaldo.descifrar(io.BytesIO(bytes(alterado)), None, [LLAVE])
    # Cortado justo al final de un bloque completo (no el último): se nota.
    primer_bloque = respaldo.LARGO_ENCABEZADO + 4 + respaldo.TAMANO_BLOQUE + 16
    with pytest.raises(respaldo.ErrorRespaldo, match="cortó"):
        respaldo.descifrar(io.BytesIO(cifrado[:primer_bloque]), None, [LLAVE])
    with pytest.raises(respaldo.ErrorRespaldo, match="de más"):
        respaldo.descifrar(io.BytesIO(cifrado + b"x"), None, [LLAVE])
    with pytest.raises(respaldo.ErrorRespaldo, match="Ninguna de las llaves"):
        respaldo.descifrar(io.BytesIO(cifrado), None, [os.urandom(32)])
    with pytest.raises(respaldo.ErrorRespaldo, match="no es un respaldo"):
        respaldo.descifrar(io.BytesIO(b"PK\x03\x04 zip"), None, [LLAVE])


def test_llave_vieja_sigue_restaurando(settings):
    vieja, nueva = os.urandom(32), os.urandom(32)
    cifrado = _cifrado(b"datos viejos", vieja)
    settings.NOMINA_LLAVE_RESPALDO = ",".join(base64.b64encode(k).decode() for k in (nueva, vieja))
    llaves = respaldo.llaves_respaldo()
    assert llaves[0] == nueva
    salida = io.BytesIO()
    respaldo.descifrar(io.BytesIO(cifrado), salida, llaves)
    assert salida.getvalue() == b"datos viejos"


_TRIGGERS = importlib.import_module("apps.auditoria.migrations.0003_bitacora_inmutable")


def _triggers(crear: bool):
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute(_TRIGGERS.POSTGRES_CREAR if crear else _TRIGGERS.POSTGRES_BORRAR)
        else:
            for sql in (_TRIGGERS.SQLITE_CREAR if crear else _TRIGGERS.SQLITE_BORRAR):
                cursor.execute(sql)


@pytest.fixture
def recrear_triggers(django_db_blocker):
    """Se desmonta después de la limpieza de la base de datos: deja la bitácora inmutable otra vez."""
    yield
    with django_db_blocker.unblock():
        _triggers(crear=True)


@pytest.fixture
def quitar_triggers(transactional_db):
    """La limpieza final (flush) borra la bitácora; sólo en esta prueba se quitan los triggers para eso."""
    yield
    _triggers(crear=False)


def test_respaldar_verificar_y_restaurar(recrear_triggers, transactional_db, quitar_triggers, tmp_path, compania):
    ana = crear_empleado(compania, numero="1", ssn="234567890", nombre="Ana")
    salida = io.StringIO()
    call_command("respaldar", destino=str(tmp_path), stdout=salida)
    archivos = list(tmp_path.glob("nomina-*.respaldo"))
    assert len(archivos) == 1 and oct(archivos[0].stat().st_mode & 0o777) == "0o600"
    contenido = archivos[0].read_bytes()
    assert contenido.startswith(b"NOMRESP1") and b"Del Pueblo" not in contenido
    assert RegistroAuditoria.objects.filter(accion=Accion.RESPALDO_CREADO).exists()

    call_command("verificar_respaldo", str(archivos[0]), stdout=io.StringIO())

    # Cambios después del respaldo; al restaurar, vuelve todo como estaba.
    crear_empleado(compania, numero="2", ssn="345678901", nombre="Beto")
    Empleado.objects.filter(pk=ana.pk).update(nombre="Cambiada")
    with pytest.raises(CommandError, match="--confirmar"):
        call_command("restaurar", str(archivos[0]))
    call_command("restaurar", str(archivos[0]), confirmar=True, stdout=io.StringIO())
    connection.close()
    assert list(Empleado.objects.values_list("nombre", flat=True)) == ["Ana"]
    assert Empleado.objects.get().ssn.revelar() == "234567890"
    assert RegistroAuditoria.objects.filter(accion=Accion.RESPALDO_RESTAURADO).exists()
    call_command("verificar_auditoria", stdout=io.StringIO())


@pytest.mark.django_db
def test_errores_de_los_comandos(tmp_path, settings):
    with pytest.raises(CommandError, match="No existe"):
        call_command("verificar_respaldo", str(tmp_path / "nada.respaldo"))
    falso = Path(tmp_path / "falso.respaldo")
    falso.write_bytes(b"no soy un respaldo")
    with pytest.raises(CommandError, match="no es un respaldo"):
        call_command("verificar_respaldo", str(falso))
    settings.NOMINA_LLAVE_RESPALDO = ""
    with pytest.raises(CommandError, match="NOMINA_LLAVE_RESPALDO"):
        call_command("respaldar", destino=str(tmp_path))


@pytest.mark.django_db
def test_borra_respaldos_viejos(tmp_path):
    viejo = tmp_path / "nomina-20200101-000000.respaldo"
    viejo.write_bytes(b"x")
    os.utime(viejo, (0, 0))
    otro = tmp_path / "otro-archivo.txt"
    otro.write_bytes(b"x")
    os.utime(otro, (0, 0))
    call_command("respaldar", destino=str(tmp_path), conservar_dias=30, stdout=io.StringIO())
    assert not viejo.exists() and otro.exists()
    assert len(list(tmp_path.glob("nomina-*.respaldo"))) == 1
