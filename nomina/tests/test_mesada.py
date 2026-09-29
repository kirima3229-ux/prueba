"""Calculadora de mesada (Ley 80) con casos calculados a mano."""

from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.calculo.mesada import (
    ReglaMesada,
    calcular_mesada,
    liquidar,
    salario_base_por_horas,
    tarifa_para_liquidacion,
)
from apps.licencias.models import MovimientoLicencia
from apps.parametros.models import ParametrosAnuales

from .conftest import crear_empleado

REGLAS = [
    ReglaMesada("anterior", D("0"), D("5"), D("2"), D("1"), None),
    ReglaMesada("anterior", D("5"), D("15"), D("3"), D("2"), None),
    ReglaMesada("anterior", D("15"), None, D("6"), D("3"), None),
    ReglaMesada("ley4", D("0"), None, D("3"), D("2"), D("9")),
]
SALARIO = D("2600")  # semanal: 2,600 × 12 ÷ 52 = 600


def mesada(regimen, empleo, despido=date(2026, 9, 30), **extra):
    return calcular_mesada(regimen=regimen, fecha_empleo=empleo, fecha_despido=despido,
                           salario_mensual=SALARIO, reglas=REGLAS, **extra)


def test_anterior_menos_de_5_anios():
    # 3 años completos: 2 × 2,600 + 3 × 1 × 600 = 5,200 + 1,800
    assert mesada("anterior", date(2013, 1, 15), date(2016, 3, 1)).monto == D("7000.00")


def test_anterior_de_5_a_15_anios():
    # 16/5/2016 → 30/9/2026: 10 años completos → 3 × 2,600 + 10 × 2 × 600 = 7,800 + 12,000
    assert mesada("anterior", date(2016, 5, 16)).monto == D("19800.00")


def test_anterior_mas_de_15_anios_sin_tope():
    # 20 años completos: 6 × 2,600 + 20 × 3 × 600 = 15,600 + 36,000
    assert mesada("anterior", date(2006, 9, 1)).monto == D("51600.00")


def test_limite_exacto_de_5_anios_usa_el_primer_tramo():
    r = mesada("anterior", date(2011, 9, 30), date(2016, 9, 30))
    assert r.anios_completos == 5
    assert r.monto == D("8200.00")  # 2 × 2,600 + 5 × 1 × 600


def test_ley4_con_tope_de_9_meses():
    # 2 años: 3 × 2,600 + 2 × 2 × 600 = 7,800 + 2,400 = 10,200
    assert mesada("ley4", date(2024, 9, 1)).monto == D("10200.00")
    # 20 años: 7,800 + 20 × 2 × 600 = 31,800 → tope de 9 meses = 23,400
    r = calcular_mesada(regimen="ley4", fecha_empleo=date(2017, 2, 1), fecha_despido=date(2037, 3, 1),
                        salario_mensual=SALARIO, reglas=REGLAS)
    assert r.monto == D("23400.00") and "Tope" in r.explicacion


def test_periodo_probatorio_no_aplica():
    r = mesada("ley4", date(2026, 3, 1), periodo_probatorio=True)
    assert not r.aplica and r.monto == D("0")


def test_fechas_invalidas():
    r = mesada("ley4", date(2026, 10, 1))
    assert not r.aplica


def test_explicacion():
    texto = mesada("anterior", date(2016, 5, 16)).explicacion
    assert "10 completos" in texto and "$600.00" in texto and "Mesada: $19,800.00" in texto


# --- Con base de datos -----------------------------------------------------------

@pytest.mark.django_db
def test_reglas_de_mesada_cargadas_y_copiadas(cliente_admin):
    p = ParametrosAnuales.objects.get(anio=2026)
    assert p.reglas_mesada.count() == 4
    assert p.reglas_mesada.get(regimen="ley4").tope_meses == D("9")
    cliente_admin.post(reverse("parametros:copiar"), {"origen": p.pk, "anio": 2027})
    assert ParametrosAnuales.objects.get(anio=2027).reglas_mesada.count() == 4


@pytest.mark.django_db
def test_pantalla_de_mesada(cliente_preparador, compania):
    emp = crear_empleado(compania, fecha_empleo=date(2016, 5, 16))  # régimen anterior
    respuesta = cliente_preparador.post(reverse("calculo:mesada"), {
        "empleado": emp.pk, "fecha_despido": "2026-09-30", "salario_mensual": "2600"})
    r = respuesta.context["liquidacion"].mesada
    assert r.monto == D("19800.00")
    html = respuesta.content.decode()
    assert "19,800.00" in html or "19800.00" in html
    assert "POR VERIFICAR" in html


@pytest.mark.django_db
def test_mesada_empleado_de_otra_compania(cliente_preparador, compania, otra_compania):
    ajeno = crear_empleado(otra_compania, numero="9", ssn="345678901")
    respuesta = cliente_preparador.post(reverse("calculo:mesada"), {
        "empleado": ajeno.pk, "fecha_despido": "2026-09-30", "salario_mensual": "2600"})
    assert respuesta.context["liquidacion"] is None and "empleado" in respuesta.context["form"].errors


# --- Liquidación ------------------------------------------------------------------


def test_salario_base_por_horas():
    assert salario_base_por_horas(D("12.50"), D("176")) == D("2200.00")


def test_tarifa_para_liquidacion():
    assert tarifa_para_liquidacion(tipo_pago="hora", tarifa=D("12"), horas_regulares_periodo=None,
                                   salario_mensual=D("2000"))[0] == D("12")
    assert tarifa_para_liquidacion(tipo_pago="salario", tarifa=D("800"), horas_regulares_periodo=D("40"),
                                   salario_mensual=D("3466.67"))[0] == D("20")
    tarifa, texto = tarifa_para_liquidacion(tipo_pago="exento", tarifa=D("3000"), horas_regulares_periodo=None,
                                            salario_mensual=D("5200"))
    assert tarifa == D("30") and "2,080" in texto  # 5,200 × 12 ÷ 2,080
    # Mesero a $4: las vacaciones se liquidan al salario mínimo.
    tarifa, texto = tarifa_para_liquidacion(tipo_pago="hora", tarifa=D("4"), horas_regulares_periodo=None,
                                            salario_mensual=D("700"), salario_minimo=D("10.50"))
    assert tarifa == D("10.50") and "salario mínimo" in texto


def test_liquidar_suma_mesada_y_vacaciones():
    m = mesada("ley4", date(2024, 9, 1))  # 10,200
    liq = liquidar(mesada=m, horas_vacaciones=D("40"), horas_enfermedad=D("24"), tarifa_hora=D("15"), texto_tarifa="$15")
    assert liq.pago_vacaciones == D("600.00") and liq.total == D("10800.00")
    assert liq.horas_enfermedad == D("24")


@pytest.mark.django_db
def test_pantalla_liquidacion_empleado_por_hora(cliente_preparador, compania, preparador):
    emp = crear_empleado(compania, fecha_empleo=date(2024, 9, 1), tarifa="15")  # Ley 4, por hora
    MovimientoLicencia.objects.create(empleado=emp, tipo="vacaciones", clase="saldo_inicial", horas=D("40"),
                                      fecha=date(2026, 1, 1), creado_por=preparador)
    respuesta = cliente_preparador.post(reverse("calculo:mesada"), {
        "empleado": emp.pk, "fecha_despido": "2026-09-30", "horas_30_dias": "173.33"})
    liq = respuesta.context["liquidacion"]
    # Base: 173.33 × 15 = 2,599.95; semanal 599.99; 3 meses 7,799.85 + 4 semanas 2,399.95 = 10,199.80
    assert liq.mesada.monto == D("10199.80")
    assert liq.pago_vacaciones == D("600.00")  # 40 h × $15
    assert liq.total == D("10799.80")
    assert "173.33 h × $15.00" in respuesta.content.decode()


@pytest.mark.django_db
def test_asalariado_necesita_salario_base(cliente_preparador, compania):
    emp = crear_empleado(compania, tipo_pago="salario", tarifa="800")
    respuesta = cliente_preparador.post(reverse("calculo:mesada"), {
        "empleado": emp.pk, "fecha_despido": "2026-09-30", "horas_30_dias": "160"})
    assert "horas_30_dias" in respuesta.context["form"].errors
    respuesta = cliente_preparador.post(reverse("calculo:mesada"), {"empleado": emp.pk, "fecha_despido": "2026-09-30"})
    assert "salario_mensual" in respuesta.context["form"].errors
