import io
from datetime import date
from decimal import Decimal as D

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.companias.models import Compania
from apps.core import cifrado
from apps.empleados.models import Empleado
from apps.servicios import pagos
from apps.servicios.models import PagoServicio, ProveedorServicios

from .conftest import crear_empleado
from .test_servicios import crear_proveedor

NUEVA_INDICE = "cGxhbm8tZGUtcHJ1ZWJhLTMyLWJ5dGVzLWV4YWN0b3M="  # 32 bytes


def _crudo(modelo, campo, pk):
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {campo} FROM {modelo._meta.db_table} WHERE id = %s", [pk])
        return cursor.fetchone()[0]


@pytest.fixture
def datos_con_llave_1(settings, compania, admin):
    settings.NOMINA_LLAVE_ACTIVA = "1"
    emp = crear_empleado(compania, numero="1", ssn="234567890", nombre="Ana")
    emp.asignar_cuenta_bancaria("111122223333")
    emp.save()
    prov = crear_proveedor(compania)
    pago, _ = pagos.registrar(proveedor=prov, fecha=date(2026, 3, 1), monto=D("100"), usuario=admin)
    settings.NOMINA_LLAVE_ACTIVA = "2"
    return emp, prov, pago


@pytest.mark.django_db
def test_recifra_todo_con_la_llave_activa(datos_con_llave_1, compania):
    emp, prov, pago = datos_con_llave_1
    assert cifrado.id_llave_de(_crudo(Empleado, "ssn", emp.pk)) == "1"
    salida = io.StringIO()
    call_command("rotar_llaves", inventario=True, stdout=salida)
    assert "llave 1" in salida.getvalue()
    with pytest.raises(CommandError, match="--confirmar"):
        call_command("rotar_llaves")
    call_command("rotar_llaves", confirmar=True, stdout=io.StringIO())
    for modelo, campo, pk in ((Empleado, "ssn", emp.pk), (Empleado, "banco_cuenta", emp.pk),
                              (ProveedorServicios, "identificacion", prov.pk), (Compania, "ein", compania.pk)):
        assert cifrado.id_llave_de(_crudo(modelo, campo, pk)) == "2", (modelo, campo)
    emp = Empleado.objects.get(pk=emp.pk)
    assert emp.ssn.revelar() == "234567890" and emp.banco_cuenta.revelar() == "111122223333"
    # El pago de servicios es inmutable para los modelos, pero la rotación no cambia su contenido.
    assert PagoServicio.objects.get(pk=pago.pk).monto == D("100.00")
    assert RegistroAuditoria.objects.filter(accion=Accion.LLAVES_ROTADAS).exists()
    salida = io.StringIO()
    call_command("rotar_llaves", inventario=True, stdout=salida)
    assert "llave 1" not in salida.getvalue()


@pytest.mark.django_db
def test_rota_la_llave_de_los_indices(datos_con_llave_1, settings, compania):
    emp, prov, _ = datos_con_llave_1
    viejo = Empleado.objects.get(pk=emp.pk).ssn_indice
    call_command("rotar_llaves", confirmar=True, llave_indice_nueva=NUEVA_INDICE, stdout=io.StringIO())
    settings.NOMINA_LLAVE_INDICE = NUEVA_INDICE
    emp = Empleado.objects.get(pk=emp.pk)
    assert emp.ssn_indice != viejo and emp.ssn_indice == Empleado.indice_ssn("234567890")
    prov = ProveedorServicios.objects.get(pk=prov.pk)
    assert prov.identificacion_indice == ProveedorServicios.indice_identificacion(prov.tipo_identificacion, "123456789")
    compania = Compania.objects.get(pk=compania.pk)
    assert compania.ein_indice == cifrado.indice_ciego(compania.ein.revelar(), "ein")


@pytest.mark.django_db
def test_llave_indice_invalida(compania):
    with pytest.raises(CommandError, match="32 bytes"):
        call_command("rotar_llaves", confirmar=True, llave_indice_nueva="YWJj")


def test_generar_llave():
    salida = io.StringIO()
    call_command("generar_llave", stdout=salida)
    assert len(cifrado.llave_de_texto(salida.getvalue().strip())) == 32
