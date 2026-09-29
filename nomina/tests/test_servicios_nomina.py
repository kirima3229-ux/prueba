from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.nomina import reportes
from apps.servicios.models import PagoServicio

from .test_nomina import compania_lista, periodo_semana  # noqa: F401
from .test_servicios import crear_proveedor


@pytest.fixture
def datos(compania_lista, preparador):  # noqa: F811
    luis = crear_proveedor(compania_lista)
    acme = crear_proveedor(compania_lista, numero="P-2", tipo="ein", identificacion="661234567",
                           tipo_persona="entidad", nombre="ACME LLC", apellido_paterno="")
    return periodo_semana(compania_lista, preparador), luis, acme


@pytest.mark.django_db
def test_vista_previa_y_registro(cliente_preparador, datos):
    periodo, luis, acme = datos
    url = reverse("nomina:servicios", args=[periodo.pk])
    base = {f"monto_{luis.pk}": "800", f"referencia_{luis.pk}": "F-10", f"metodo_{luis.pk}": "cheque",
            f"monto_{acme.pk}": "", f"metodo_{acme.pk}": "transferencia"}
    html = cliente_preparador.post(url, {**base, "accion": "vista_previa"}).content.decode()
    assert "$30.00" in html and "Registrar pagos" in html  # 10% de 300 (después de los primeros $500)
    assert PagoServicio.objects.count() == 0
    respuesta = cliente_preparador.post(url, {**base, "accion": "registrar"})
    assert respuesta.status_code == 302
    pago = PagoServicio.objects.get()
    assert (pago.proveedor, pago.fecha, pago.origen, pago.periodo_nomina) == (luis, periodo.fecha_pago, "nomina", periodo)
    assert pago.retencion == D("30.00") and pago.referencia == "F-10"
    assert "F-10" in cliente_preparador.get(url).content.decode()
    # La retención aparece en los impuestos a pagar del mes.
    obligaciones = reportes.impuestos(periodo.compania, periodo.fecha_pago.replace(day=1), periodo.fecha_pago)
    assert any(o.concepto.startswith("Retención de servicios") and o.monto == D("30.00") for o in obligaciones)


@pytest.mark.django_db
def test_errores(cliente_preparador, cliente_lectura, datos):
    periodo, luis, _ = datos
    url = reverse("nomina:servicios", args=[periodo.pk])
    html = cliente_preparador.post(url, {f"monto_{luis.pk}": "abc", "accion": "registrar"}).content.decode()
    assert "no es válido" in html and PagoServicio.objects.count() == 0
    html = cliente_preparador.post(url, {"accion": "registrar"}).content.decode()
    assert "al menos un pago" in html
    assert cliente_lectura.get(url).status_code == 200
    assert cliente_lectura.post(url, {f"monto_{luis.pk}": "10", "accion": "registrar"}).status_code == 403
