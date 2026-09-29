from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.nomina import servicios
from apps.nomina.models import EntradaDeduccion, EntradaIngreso, LineaResultado
from apps.parametros.models import ConceptoDeduccion, ConceptoIngreso
from apps.planillas import datos, pdf_w2

from .conftest import crear_empleado
from .test_nomina import compania_lista, entrar_horas  # noqa: F401


def _suma(codigo, empleado, campo="monto"):
    return sum((getattr(l, campo) or D("0")) for l in LineaResultado.objects.filter(codigo=codigo,
                                                                                    resultado__empleado=empleado))


@pytest.fixture
def escenario(compania_lista, preparador):  # noqa: F811
    c = compania_lista
    federal = crear_empleado(c, numero="1", ssn="234567890", nombre="Ana", tarifa="30", w4_aplica=True,
                             direccion_linea1="100 Main St", ciudad="Miami", estado="FL", codigo_postal="33101")
    solo_pr = crear_empleado(c, numero="2", ssn="345678901", nombre="Beto", tarifa="15")
    k401 = ConceptoDeduccion.objects.get(codigo="retiro_401k")
    propinas = ConceptoIngreso.objects.get(codigo="propinas")
    for semana in range(3):
        inicio = date(2026, 3, 2) + timedelta(weeks=semana)
        p = servicios.crear_periodo(compania=c, inicio=inicio, fin=inicio + timedelta(days=6),
                                    fecha_pago=inicio + timedelta(days=11), usuario=preparador)
        e = entrar_horas(p, federal, horas_regulares="40")
        EntradaDeduccion.objects.create(entrada=e, concepto=k401, monto=D("60"))
        EntradaIngreso.objects.create(entrada=e, concepto=propinas, monto=D("40"))
        entrar_horas(p, solo_pr, horas_regulares="40")
        assert servicios.calcular_periodo(p, preparador) == []
        servicios.cerrar_periodo(p, preparador)
    return c, federal, solo_pr


@pytest.mark.django_db
def test_casillas(escenario):
    c, federal, solo_pr = escenario
    filas = datos.w2_federal(c, 2026)
    assert [d.empleado for d in filas] == [federal]  # el empleado sólo de PR no lleva W-2 federal
    d = filas[0]
    # (1,200 + 40 − 60 del 401(k)) × 3
    assert d.c1_salarios == D("3540.00")
    assert d.c2_retencion_federal == _suma("retencion_federal", federal) > 0
    assert d.c7_propinas_ss == D("120.00")
    assert d.c3_salarios_ss + d.c7_propinas_ss == _suma("ss_empleado", federal, "base") == D("3720.00")
    assert d.c4_ss_retenido == _suma("ss_empleado", federal)
    assert d.c5_salarios_medicare == D("3720.00") and d.c6_medicare_retenido == _suma("medicare_empleado", federal)
    assert d.c12 == {"D": D("180.00")} and d.c13_plan_retiro
    assert d.c17_retencion_estatal == _suma("retencion_pr", federal)
    assert "SINOT (PR)" in d.c14


@pytest.mark.django_db
def test_sin_empleados_federales(compania_lista):  # noqa: F811
    assert datos.w2_federal(compania_lista, 2026) == []


@pytest.mark.django_db
def test_pantalla_copias_y_permisos(cliente_lectura, cliente_preparador, escenario):
    c, federal, _ = escenario
    url = reverse("planillas:planilla", args=["w2"]) + "?anio=2026"
    html = cliente_lectura.get(url).content.decode()
    assert "TOTALES W-3 (1 formularios)" in html and "Ana" in html and "Beto" not in html
    assert "234567890" not in html
    assert cliente_lectura.get(url + "&formato=copias").status_code == 403
    pdf = cliente_preparador.get(url + "&formato=copias")
    assert pdf["Content-Type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert RegistroAuditoria.objects.filter(accion=Accion.ARCHIVO_GENERADO, descripcion__startswith="W-2 federal").exists()
    assert cliente_lectura.get(url + "&formato=pdf").content.startswith(b"%PDF")
    vacio = reverse("planillas:planilla", args=["w2"]) + "?anio=2025&formato=copias"
    assert cliente_preparador.get(vacio).status_code == 302


@pytest.mark.django_db
def test_pdf_tres_copias(escenario):
    c, *_ = escenario
    contenido = pdf_w2.generar(datos.w2_federal(c, 2026), c, 2026, comprimir=False)
    for rotulo in (b"Copy B", b"Copy C", b"Copy 2"):
        assert rotulo in contenido
    assert b"XXX-XX-7890" in contenido and b"234567890" not in contenido
    assert b"3,540.00" in contenido
