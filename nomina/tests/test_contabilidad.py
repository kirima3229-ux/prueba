import csv
import io
from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.nomina import contabilidad, servicios
from apps.nomina.models import CuentaContable, LineaResultado
from apps.parametros.models import ConceptoDeduccion

from .conftest import crear_empleado
from .test_nomina import compania_lista, entrar_horas, periodo_semana  # noqa: F401


@pytest.fixture
def nomina(compania_lista, preparador):  # noqa: F811
    ana = crear_empleado(compania_lista, numero="1", ssn="234567890", nombre="Ana", tarifa="12")
    beto = crear_empleado(compania_lista, numero="2", ssn="345678901", nombre="Beto", tarifa="15")
    periodo = periodo_semana(compania_lista, preparador)
    entrar_horas(periodo, ana, horas_regulares="40")
    entrada = entrar_horas(periodo, beto, horas_regulares="40")
    entrada.deducciones.create(concepto=ConceptoDeduccion.objects.get(codigo="plan_medico"), monto=D("50"))
    servicios.calcular_periodo(periodo, preparador)
    servicios.cerrar_periodo(periodo, preparador)
    return periodo


def _por_cuenta(lineas):
    return {l.cuenta: (l.debito, l.credito) for l in lineas}


@pytest.mark.django_db
def test_asiento_cuadra_con_cuentas_sugeridas(nomina):
    lineas = contabilidad.asiento(LineaResultado.objects.filter(resultado__periodo=nomina), {})
    assert contabilidad.cuadra(lineas)
    cuentas = _por_cuenta(lineas)
    bruto = sum(r.bruto for r in nomina.resultados.all())
    neto = sum(r.neto for r in nomina.resultados.all())
    assert cuentas["Gastos de nómina:Salarios"] == (bruto, 0)
    assert cuentas["Nómina por pagar"] == (0, neto)
    assert cuentas["Deducciones de empleados por pagar"] == (0, D("50.00"))
    # SS y Medicare de empleado y patrono juntos en la cuenta del 941.
    fica = sum(l.monto for l in LineaResultado.objects.filter(
        resultado__periodo=nomina, codigo__in=["ss_empleado", "ss_patrono", "medicare_empleado", "medicare_patrono"]))
    assert fica > 0 and cuentas["IRS 941 por pagar"] == (0, fica)
    patronal = sum(r.total_patronal for r in nomina.resultados.all())
    assert cuentas["Gastos de nómina:Contribuciones patronales"] == (patronal, 0)


@pytest.mark.django_db
def test_asignacion_por_concepto_y_por_grupo(nomina, compania_lista):  # noqa: F811
    asignadas = {"pasivo:*": "Otros pasivos", "pasivo:retencion_pr": "Hacienda por pagar",
                 "patronal:futa": "Gasto FUTA", "neto": "Banco Popular"}
    cuentas = _por_cuenta(contabilidad.asiento(LineaResultado.objects.filter(resultado__periodo=nomina), asignadas))
    assert "Hacienda por pagar" in cuentas and "Gasto FUTA" in cuentas and "Banco Popular" in cuentas
    # Las claves con sugerida propia la conservan aunque el grupo tenga otra cuenta.
    assert "IRS 941 por pagar" in cuentas


@pytest.mark.django_db
def test_reverso_invierte_el_asiento(nomina, admin):
    reverso = servicios.reversar_periodo(nomina, "Error", admin)
    original = _por_cuenta(contabilidad.asiento(LineaResultado.objects.filter(resultado__periodo=nomina), {}))
    invertido = _por_cuenta(contabilidad.asiento(LineaResultado.objects.filter(resultado__periodo=reverso), {}))
    assert {c: (cr, db) for c, (db, cr) in original.items()} == invertido
    ambos = contabilidad.asiento(LineaResultado.objects.filter(resultado__periodo__in=[nomina, reverso]), {})
    assert ambos == []


@pytest.mark.django_db
def test_pantallas(cliente_admin, cliente_preparador, cliente_lectura, nomina):
    url = reverse("nomina:asiento", args=[nomina.pk])
    assert "Cuadra" in cliente_lectura.get(url).content.decode()
    respuesta = cliente_lectura.get(url + "?formato=csv")
    filas = list(csv.reader(io.StringIO(respuesta.content.decode("utf-8-sig"))))
    assert filas[0][:5] == ["Journal No", "Journal Date", "Account", "Debits", "Credits"]
    assert filas[1][0] == f"NOM-20260918-{nomina.pk}" and filas[1][1] == "09/18/2026"
    debitos = sum(D(f[3] or 0) for f in filas[1:])
    creditos = sum(D(f[4] or 0) for f in filas[1:])
    assert debitos == creditos > 0
    assert cliente_lectura.get(url + "?formato=xlsx").status_code == 200

    config = reverse("nomina:cuentas_contables")
    assert cliente_preparador.get(config).status_code == 403
    assert cliente_admin.get(config).status_code == 200
    cliente_admin.post(config, {"c_neto": "Banco Popular", "c_pasivo:retencion_pr": "  "})
    assert list(CuentaContable.objects.values_list("clave", "cuenta")) == [("neto", "Banco Popular")]
    assert RegistroAuditoria.objects.filter(accion=Accion.CUENTAS_CONTABLES).exists()
    assert "Banco Popular" in cliente_lectura.get(url).content.decode()


@pytest.mark.django_db
def test_nomina_abierta_no_tiene_asiento(cliente_preparador, compania_lista, preparador):  # noqa: F811
    periodo = periodo_semana(compania_lista, preparador, date(2026, 10, 5))
    respuesta = cliente_preparador.get(reverse("nomina:asiento", args=[periodo.pk]))
    assert respuesta.status_code == 302
