from datetime import date
from decimal import Decimal as D

import pytest

from apps.companias.models import TasasCompania
from apps.licencias.models import MovimientoLicencia, saldo
from apps.nomina import servicios
from apps.nomina.models import (
    DeduccionRecurrente,
    EntradaIngreso,
    ErrorNominaCerrada,
    LineaResultado,
    PeriodoNomina,
)
from apps.parametros.models import ConceptoDeduccion, ConceptoIngreso

from .conftest import crear_empleado


@pytest.fixture
def compania_lista(compania):
    TasasCompania.objects.create(compania=compania, anio=2026, suta_tasa=D("2.4"), aportacion_especial_tasa=D("1"),
                                 sinot_empleado_tasa=D("0.3"), sinot_patrono_tasa=D("0.3"))
    return compania


@pytest.fixture
def empleado(compania_lista):
    return crear_empleado(compania_lista, tarifa="12", fecha_empleo=date(2020, 1, 6))


def periodo_semana(compania, usuario, inicio=date(2026, 9, 7)):
    from datetime import timedelta

    return servicios.crear_periodo(compania=compania, inicio=inicio, fin=inicio + timedelta(days=6),
                                   fecha_pago=inicio + timedelta(days=11), usuario=usuario)


def entrar_horas(periodo, empleado, **horas):
    entrada = periodo.entradas.get(empleado=empleado)
    for campo, valor in horas.items():
        setattr(entrada, campo, D(valor))
    entrada.save()
    servicios.marcar_modificado(periodo)
    return entrada


@pytest.mark.django_db
def test_sugerir_periodo(compania_lista, preparador):
    inicio, fin, pago = servicios.sugerir_periodo(compania_lista)
    assert inicio.weekday() == 0 and (fin - inicio).days == 6
    periodo_semana(compania_lista, preparador)
    assert servicios.sugerir_periodo(compania_lista)[0] == date(2026, 9, 14)
    compania_lista.frecuencia_pago = "quincenal"
    assert servicios.sugerir_periodo(compania_lista)[:2] == (date(2026, 9, 14), date(2026, 9, 15))


@pytest.mark.django_db
def test_crear_periodo_incluye_empleados_y_deducciones_recurrentes(compania_lista, empleado, preparador):
    inactivo = crear_empleado(compania_lista, numero="2", ssn="234567890", activo=False,
                              fecha_terminacion=date(2026, 1, 1))
    plan = ConceptoDeduccion.objects.get(codigo="plan_medico")
    DeduccionRecurrente.objects.create(empleado=empleado, concepto=plan, monto=D("50"))
    DeduccionRecurrente.objects.create(empleado=empleado, concepto=plan, monto=D("99"), activo=False)
    periodo = periodo_semana(compania_lista, preparador)
    assert list(periodo.entradas.values_list("empleado", flat=True)) == [empleado.pk]
    assert inactivo.pk not in periodo.entradas.values_list("empleado", flat=True)
    entrada = periodo.entradas.get()
    assert [(d.concepto.codigo, d.monto) for d in entrada.deducciones.all()] == [("plan_medico", D("50.00"))]


@pytest.mark.django_db
def test_calcular_y_cerrar(compania_lista, empleado, preparador):
    periodo = periodo_semana(compania_lista, preparador)
    entrar_horas(periodo, empleado, horas_regulares="40")
    with pytest.raises(servicios.ErrorNomina, match="calcule"):
        servicios.cerrar_periodo(periodo, preparador)
    assert servicios.calcular_periodo(periodo, preparador) == []
    r = periodo.resultados.get()
    assert r.bruto == D("480.00") and r.neto == D("420.36")
    assert r.ssn_ultimos4 == "6789" and r.lineas.filter(grupo="retencion", codigo="ss_empleado").get().monto == D("29.76")
    assert periodo.parametros_usados["ss_tope"] == "184500.00"
    # Un cambio después de calcular obliga a recalcular.
    entrar_horas(periodo, empleado, horas_regulares="40")
    periodo.refresh_from_db()
    with pytest.raises(servicios.ErrorNomina, match="calcule de nuevo"):
        servicios.cerrar_periodo(periodo, preparador)
    servicios.calcular_periodo(periodo, preparador)
    servicios.cerrar_periodo(periodo, preparador)
    periodo.refresh_from_db()
    assert periodo.estado == "cerrada"
    r = periodo.resultados.get()
    r.neto = D("1")
    with pytest.raises(ErrorNominaCerrada):
        r.save()
    with pytest.raises(ErrorNominaCerrada):
        periodo.exigir_editable()


@pytest.mark.django_db
def test_acumulados_del_anio_aplican_topes(compania_lista, empleado, preparador):
    p1 = periodo_semana(compania_lista, preparador)
    entrar_horas(p1, empleado, horas_regulares="40")
    EntradaIngreso.objects.create(entrada=p1.entradas.get(), concepto=ConceptoIngreso.objects.get(codigo="bono"),
                                  monto=D("6700"))
    servicios.calcular_periodo(p1, preparador)
    servicios.cerrar_periodo(p1, preparador)
    assert servicios.acumulados(empleado, 2026).futa == D("7180.00")

    p2 = periodo_semana(compania_lista, preparador, inicio=date(2026, 9, 14))
    entrar_horas(p2, empleado, horas_regulares="40")
    servicios.calcular_periodo(p2, preparador)
    lineas = {l.codigo: l.monto for l in LineaResultado.objects.filter(resultado__periodo=p2)}
    assert lineas["futa"] == D("0.00") and lineas["suta"] == D("0.00")  # tope de $7,000 ya alcanzado
    assert lineas["ss_empleado"] == D("29.76")  # el Seguro Social sigue


@pytest.mark.django_db
def test_licencias_se_descuentan_al_cerrar_y_vuelven_al_reversar(compania_lista, empleado, preparador, admin):
    MovimientoLicencia.objects.create(empleado=empleado, tipo="vacaciones", clase="saldo_inicial", horas=D("40"),
                                      fecha=date(2026, 1, 1))
    periodo = periodo_semana(compania_lista, preparador)
    entrar_horas(periodo, empleado, horas_regulares="32", horas_vacaciones="8")
    servicios.calcular_periodo(periodo, preparador)
    servicios.cerrar_periodo(periodo, preparador)
    assert saldo(empleado, "vacaciones") == D("32")

    reverso = servicios.reversar_periodo(periodo, "Horas equivocadas", admin)
    periodo.refresh_from_db()
    assert periodo.estado == "reversada" and reverso.tipo == "reverso" and reverso.estado == "cerrada"
    assert reverso.resultados.get().bruto == D("-480.00")
    assert saldo(empleado, "vacaciones") == D("40")
    a = servicios.acumulados(empleado, 2026)
    assert a.ss == D("0") and a.futa == D("0")  # el reverso deja los acumulados en cero
    with pytest.raises(servicios.ErrorNomina):
        servicios.reversar_periodo(periodo, "otra vez", admin)
    with pytest.raises(servicios.ErrorNomina):
        servicios.reversar_periodo(reverso, "reverso del reverso", admin)


@pytest.mark.django_db
def test_errores_por_empleado_impiden_cerrar(compania_lista, preparador):
    asalariado = crear_empleado(compania_lista, numero="3", ssn="345678901", tipo_pago="salario", tarifa="800")
    periodo = periodo_semana(compania_lista, preparador)
    entrar_horas(periodo, asalariado, horas_extra_semanales="2")  # sin horas regulares por período
    errores = servicios.calcular_periodo(periodo, preparador)
    assert errores and "horas regulares por período" in errores[0]
    with pytest.raises(servicios.ErrorNomina, match="errores"):
        servicios.cerrar_periodo(periodo, preparador)


@pytest.mark.django_db
def test_ytd_por_concepto(compania_lista, empleado, preparador):
    p1 = periodo_semana(compania_lista, preparador)
    entrar_horas(p1, empleado, horas_regulares="40")
    servicios.calcular_periodo(p1, preparador)
    servicios.cerrar_periodo(p1, preparador)
    p2 = periodo_semana(compania_lista, preparador, inicio=date(2026, 9, 14))
    entrar_horas(p2, empleado, horas_regulares="30")
    servicios.calcular_periodo(p2, preparador)
    ytd = servicios.acumulados_por_concepto(p2.resultados.get())
    assert ytd[("ingreso", "regular")] == D("840.00")  # 480 + 360
    assert ytd[("retencion", "ss_empleado")] == D("29.76") + D("22.32")


@pytest.mark.django_db
def test_sin_tasas_de_la_compania(compania, preparador):
    empleado = crear_empleado(compania)
    periodo = periodo_semana(compania, preparador)
    entrar_horas(periodo, empleado, horas_regulares="40")
    with pytest.raises(Exception, match="no tiene tasas"):
        servicios.calcular_periodo(periodo, preparador)
    assert PeriodoNomina.objects.get(pk=periodo.pk).estado == "borrador"
