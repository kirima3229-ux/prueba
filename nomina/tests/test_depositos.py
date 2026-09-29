from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.servicios import depositos
from apps.servicios.models import DepositoRetencion, ErrorPagoInmutable

from .test_pagos_servicios import pagar
from .test_servicios import crear_proveedor


@pytest.fixture
def proveedor(compania):
    return crear_proveedor(compania)


@pytest.mark.django_db
def test_periodo_sugerido_mensual(compania, proveedor, preparador):
    pagar(proveedor, "1500", preparador, fecha=date(2026, 7, 10))
    assert depositos.periodo_sugerido(compania) == (date(2026, 7, 1), date(2026, 7, 31))
    depositos.registrar(compania=compania, desde=date(2026, 7, 1), hasta=date(2026, 7, 31),
                        fecha_deposito=date(2026, 8, 10), confirmacion="C1", usuario=preparador)
    assert depositos.periodo_sugerido(compania) == (date(2026, 8, 1), date(2026, 8, 31))


@pytest.mark.django_db
def test_periodo_sugerido_bisemanal(compania, proveedor, preparador):
    compania.frecuencia_deposito = "bisemanal"
    compania.save()
    pagar(proveedor, "1500", preparador, fecha=date(2026, 7, 10))
    assert depositos.periodo_sugerido(compania) == (date(2026, 7, 10), date(2026, 7, 23))
    depositos.registrar(compania=compania, desde=date(2026, 7, 10), hasta=date(2026, 7, 23),
                        fecha_deposito=date(2026, 7, 24), confirmacion="", usuario=preparador)
    assert depositos.periodo_sugerido(compania) == (date(2026, 7, 24), date(2026, 8, 6))


@pytest.mark.django_db
def test_deposito_agrupa_solo_retencion_pendiente(compania, proveedor, preparador):
    exento = pagar(proveedor, "400", preparador, fecha=date(2026, 7, 1))      # sin retención
    p1 = pagar(proveedor, "600", preparador, fecha=date(2026, 7, 5))          # retiene 50
    p2 = pagar(proveedor, "300", preparador, fecha=date(2026, 8, 5))          # fuera del período
    deposito = depositos.registrar(compania=compania, desde=date(2026, 7, 1), hasta=date(2026, 7, 31),
                                   fecha_deposito=date(2026, 8, 10), confirmacion="C1", usuario=preparador)
    assert deposito.monto == D("50.00")
    assert list(deposito.pagos.all()) == [p1]
    exento.refresh_from_db()
    p2.refresh_from_db()
    assert exento.deposito is None and p2.deposito is None
    assert depositos.total_pendiente(compania) == D("30.00")
    # Un pago ya depositado no entra en otro depósito.
    with pytest.raises(depositos.ErrorDeposito):
        depositos.registrar(compania=compania, desde=date(2026, 7, 1), hasta=date(2026, 7, 31),
                            fecha_deposito=date(2026, 8, 11), confirmacion="C2", usuario=preparador)


@pytest.mark.django_db
def test_deposito_inmutable(compania, proveedor, preparador):
    pagar(proveedor, "1500", preparador, fecha=date(2026, 7, 5))
    deposito = depositos.registrar(compania=compania, desde=date(2026, 7, 1), hasta=date(2026, 7, 31),
                                   fecha_deposito=date(2026, 8, 10), confirmacion="C1", usuario=preparador)
    deposito.monto = D("1")
    with pytest.raises(ErrorPagoInmutable):
        deposito.save()
    with pytest.raises(ErrorPagoInmutable):
        deposito.delete()


@pytest.mark.django_db
def test_anular_deposito_libera_pagos(cliente_preparador, compania, proveedor, preparador):
    pago = pagar(proveedor, "1500", preparador, fecha=date(2026, 7, 5))
    deposito = depositos.registrar(compania=compania, desde=date(2026, 7, 1), hasta=date(2026, 7, 31),
                                   fecha_deposito=date(2026, 8, 10), confirmacion="C1", usuario=preparador)
    cliente_preparador.post(reverse("servicios:deposito_anular", args=[deposito.pk]), {"motivo": "Registrado por error"})
    deposito.refresh_from_db()
    pago.refresh_from_db()
    assert deposito.estado == "anulado" and pago.deposito is None
    assert depositos.total_pendiente(compania) == D("100.00")
    assert RegistroAuditoria.objects.filter(accion=Accion.DEPOSITO_ANULADO).exists()


@pytest.mark.django_db
def test_anular_pago_depositado_marca_diferencia(cliente_preparador, compania, proveedor, preparador):
    pago = pagar(proveedor, "1500", preparador, fecha=date(2026, 7, 5))
    deposito = depositos.registrar(compania=compania, desde=date(2026, 7, 1), hasta=date(2026, 7, 31),
                                   fecha_deposito=date(2026, 8, 10), confirmacion="C1", usuario=preparador)
    respuesta = cliente_preparador.post(reverse("servicios:pago_anular", args=[pago.pk]), {"motivo": "Error"}, follow=True)
    assert "de más" in respuesta.content.decode()
    deposito.refresh_from_db()
    assert deposito.diferencia == D("100.00")


@pytest.mark.django_db
def test_registrar_por_pantalla(cliente_preparador, compania, proveedor, preparador):
    pagar(proveedor, "1500", preparador, fecha=date(2026, 7, 5))
    vista = cliente_preparador.get(reverse("servicios:deposito_nuevo"), {"desde": "2026-07-01", "hasta": "2026-07-31"})
    html = vista.content.decode()
    assert "$100.00" in html and "csrfmiddlewaretoken" in html
    respuesta = cliente_preparador.post(
        reverse("servicios:deposito_nuevo"),
        {"desde": "2026-07-01", "hasta": "2026-07-31", "fecha_deposito": "2026-08-10", "confirmacion": "SURI-123"},
    )
    deposito = DepositoRetencion.objects.get()
    assert respuesta["Location"] == reverse("servicios:deposito_detalle", args=[deposito.pk])
    assert deposito.monto == D("100.00") and deposito.confirmacion == "SURI-123"
    assert RegistroAuditoria.objects.filter(accion=Accion.DEPOSITO_REGISTRADO).exists()


@pytest.mark.django_db
def test_solo_lectura_no_deposita(cliente_lectura, compania, proveedor, preparador):
    pagar(proveedor, "1500", preparador, fecha=date(2026, 7, 5))
    assert cliente_lectura.get(reverse("servicios:depositos")).status_code == 200
    assert cliente_lectura.get(reverse("servicios:deposito_nuevo")).status_code == 403


@pytest.mark.django_db
def test_trimestral(cliente_preparador, compania, proveedor, preparador):
    otro = crear_proveedor(compania, numero="P-2", identificacion="234567890", nombre="Rosa")
    pagar(proveedor, "1500", preparador, fecha=date(2026, 7, 5))   # T3: retiene 100
    pagar(proveedor, "200", preparador, fecha=date(2026, 10, 1))   # T4
    pagar(otro, "800", preparador, fecha=date(2026, 9, 30))        # T3: retiene 30
    depositos.registrar(compania=compania, desde=date(2026, 7, 1), hasta=date(2026, 7, 31),
                        fecha_deposito=date(2026, 8, 10), confirmacion="C1", usuario=preparador)
    respuesta = cliente_preparador.get(reverse("servicios:trimestral"), {"anio": 2026, "trimestre": 3})
    c = respuesta.context
    assert c["totales"]["monto"] == D("2300.00") and c["totales"]["retencion"] == D("130.00")
    assert c["depositado"] == D("100.00") and c["pendiente"] == D("30.00")
    assert len(c["filas"]) == 2
    excel = cliente_preparador.get(reverse("servicios:trimestral"), {"anio": 2026, "trimestre": 3, "formato": "xlsx"})
    assert excel.status_code == 200 and excel["Content-Disposition"].endswith('T3_2026.xlsx"')


def test_rango_trimestre():
    assert depositos.rango_trimestre(2026, 1) == (date(2026, 1, 1), date(2026, 3, 31))
    assert depositos.rango_trimestre(2026, 4) == (date(2026, 10, 1), date(2026, 12, 31))
    assert depositos.trimestre_de(date(2026, 9, 30)) == 3
