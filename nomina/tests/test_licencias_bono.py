"""Vacaciones, enfermedad y bono de Navidad (sin base de datos)."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.calculo import licencias as L

REGLAS = [
    L.ReglaLicencia("vacaciones", "anterior", "grande", D("0"), None, D("115"), D("1.25")),
    L.ReglaLicencia("vacaciones", "anterior", "pequeno", D("0"), None, D("115"), D("0.5")),
    L.ReglaLicencia("enfermedad", "anterior", "grande", D("0"), None, D("115"), D("1")),
    L.ReglaLicencia("enfermedad", "anterior", "pequeno", D("0"), None, D("115"), D("1")),
    L.ReglaLicencia("vacaciones", "ley4", "grande", D("0"), D("1"), D("130"), D("0.5")),
    L.ReglaLicencia("vacaciones", "ley4", "grande", D("1"), D("5"), D("130"), D("0.75")),
    L.ReglaLicencia("vacaciones", "ley4", "grande", D("5"), D("15"), D("130"), D("1")),
    L.ReglaLicencia("vacaciones", "ley4", "grande", D("15"), None, D("130"), D("1.25")),
    L.ReglaLicencia("vacaciones", "ley4", "pequeno", D("0"), None, D("130"), D("0.5")),
    L.ReglaLicencia("enfermedad", "ley4", "grande", D("0"), None, D("130"), D("1")),
    L.ReglaLicencia("enfermedad", "ley4", "pequeno", D("0"), None, D("130"), D("1")),
]


def acumular(tipo="vacaciones", regimen="ley4", empleados=30, fecha_empleo=date(2024, 1, 15),
             fin_de_mes=date(2026, 9, 30), horas=D("160"), **extra):
    return L.acumular_mes(tipo=tipo, regimen=regimen, numero_empleados=empleados, limite_pequeno=12,
                          fecha_empleo=fecha_empleo, fin_de_mes=fin_de_mes, horas_trabajadas=horas,
                          horas_por_dia=D("8"), reglas=REGLAS, **extra)


def test_anios_de_servicio():
    assert L.anios_de_servicio(date(2025, 9, 30), date(2026, 9, 30)) == D("1")      # aniversario exacto
    assert L.anios_de_servicio(date(2021, 9, 30), date(2026, 9, 30)) == D("5")
    assert D("1") < L.anios_de_servicio(date(2025, 9, 29), date(2026, 9, 30)) < D("1.01")  # un año y un día
    assert L.anios_de_servicio(date(2025, 10, 1), date(2026, 9, 30)) < D("1")
    assert L.anios_de_servicio(date(2026, 10, 1), date(2026, 9, 30)) == D("0")
    assert L.anios_de_servicio(date(2024, 2, 29), date(2025, 3, 1)) == D("1")        # 29 de febrero


@pytest.mark.parametrize(
    "fecha_empleo,horas_esperadas",
    [
        (date(2026, 3, 1), D("4.00")),    # primer año: ½ día
        (date(2025, 9, 30), D("4.00")),   # aniversario exacto: todavía ½ día
        (date(2025, 8, 31), D("6.00")),   # 1 año y 1 mes: ¾ día
        (date(2024, 1, 15), D("6.00")),   # 2.7 años: ¾ día
        (date(2021, 9, 30), D("6.00")),   # 5 años exactos: todavía ¾ día
        (date(2021, 8, 31), D("8.00")),   # 5 años y 1 mes: 1 día
        (date(2019, 5, 1), D("8.00")),    # 7 años: 1 día
    ],
)
def test_vacaciones_ley4_por_antiguedad(fecha_empleo, horas_esperadas):
    assert acumular(fecha_empleo=fecha_empleo).horas == horas_esperadas


def test_vacaciones_ley4_mas_de_15_anios_usa_1_25():
    # Un empleado Ley 4 necesita 15 años de servicio: se prueba con fechas futuras.
    r = acumular(fecha_empleo=date(2017, 2, 1), fin_de_mes=date(2032, 3, 31))
    assert r.horas == D("10.00")


def test_vacaciones_regimen_anterior():
    r = acumular(regimen="anterior", fecha_empleo=date(2010, 1, 1))
    assert r.horas == D("10.00")  # 1.25 × 8


def test_patrono_pequeno():
    assert acumular(empleados=12).horas == D("4.00")  # ½ día sin importar antigüedad
    assert acumular(regimen="anterior", empleados=10, fecha_empleo=date(2010, 1, 1)).horas == D("4.00")
    assert acumular(empleados=13).horas == D("6.00")


def test_enfermedad_un_dia():
    assert acumular(tipo="enfermedad").horas == D("8.00")
    assert acumular(tipo="enfermedad", regimen="anterior", fecha_empleo=date(2010, 1, 1)).horas == D("8.00")


def test_horas_minimas_por_regimen():
    assert acumular(horas=D("129.5")).horas == D("0")          # Ley 4: 130 h
    assert "se requieren 130" in acumular(horas=D("129.5")).explicacion
    assert acumular(regimen="anterior", fecha_empleo=date(2010, 1, 1), horas=D("115")).horas == D("10.00")
    assert acumular(regimen="anterior", fecha_empleo=date(2010, 1, 1), horas=D("114")).horas == D("0")


def test_tope_de_acumulacion():
    tope = L.tope_horas("vacaciones", dias_por_mes_actual=D("0.75"), horas_por_dia=D("8"),
                        tope_vacaciones_meses=24, tope_enfermedad_dias=D("15"))
    assert tope == D("144.00")
    r = acumular(balance_actual=D("140"), tope_horas=tope)
    assert r.horas == D("4") and "Tope" in r.explicacion
    assert acumular(balance_actual=D("144"), tope_horas=tope).horas == D("0")
    assert L.tope_horas("enfermedad", dias_por_mes_actual=D("1"), horas_por_dia=D("8"),
                        tope_vacaciones_meses=24, tope_enfermedad_dias=D("15")) == D("120.00")


# --- Bono de Navidad -------------------------------------------------------------

ANTERIOR = L.ReglaBono("anterior", 10, D("700"), 15, D("6"), D("600"), D("3"), D("300"), D("10000"))
LEY4 = L.ReglaBono("ley4", 10, D("1350"), 20, D("2"), D("600"), D("2"), D("300"), None)


def test_periodo_bono():
    assert L.periodo_bono(2026) == (date(2025, 10, 1), date(2026, 9, 30))


@pytest.mark.parametrize(
    "regla,empleados,horas,salario,esperado",
    [
        (ANTERIOR, 30, "2000", "25000", "600.00"),   # 6% de $10,000 (tope de salario)
        (ANTERIOR, 30, "800", "8000", "480.00"),     # 6% × 8,000
        (ANTERIOR, 15, "2000", "25000", "300.00"),   # 3% de $10,000
        (ANTERIOR, 30, "699", "8000", "0"),          # no llega a 700 h
        (LEY4, 25, "2080", "20000", "400.00"),       # 2% × 20,000
        (LEY4, 25, "2080", "40000", "600.00"),       # 2% × 40,000 = 800 → máximo 600
        (LEY4, 20, "2080", "20000", "300.00"),       # 20 o menos: máximo 300
        (LEY4, 25, "1349", "20000", "0"),            # no llega a 1,350 h
    ],
)
def test_bono_de_navidad(regla, empleados, horas, salario, esperado):
    r = L.calcular_bono(regla=regla, numero_empleados=empleados, horas_trabajadas=D(horas), salario=D(salario))
    assert r.monto == D(esperado)
    assert r.elegible == (D(esperado) > 0)
    assert r.explicacion
