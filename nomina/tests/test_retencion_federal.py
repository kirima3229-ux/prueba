"""
Retención federal (Publicación 15-T 2026, Hoja 1A). Casos calculados a mano:

Tabla estándar de soltero 2026 (desplazamiento 16,100 − 8,600 = 7,500):
    7,500 → 10%;  19,900 → $1,240 + 12%;  57,900 → $5,800 + 22% …
Casados (19,300): 19,300 → 10%; 44,100 → $2,480 + 12% (igual a la tabla publicada por el IRS).
"""

import importlib
from datetime import date
from decimal import Decimal as D

import pytest

from apps.calculo import motor
from apps.calculo.motor import Horas, Monto, TipoDeduccion

from .test_motor import PARAMS, TASAS

SEMILLA = importlib.import_module("apps.parametros.migrations.0011_tablas_federales")


def _tablas(anio):
    salida = {}
    for estado, (deduccion, limites) in SEMILLA.DATOS[anio].items():
        for nombre, desplazamiento, lims in (
            ("estandar", deduccion - SEMILLA.AJUSTE[estado], limites),
            ("paso2", deduccion / 2, [D(l) / 2 for l in limites]),
        ):
            salida[(estado, nombre)] = tuple(motor.Tramo(d, None, c, t) for d, c, t in SEMILLA.tabla(lims, desplazamiento))
    return salida


P2026 = motor.Parametros(**{**PARAMS.__dict__, "tramos_federales": _tablas(2026)})


def federal(tarifa, horas="40", frecuencia="semanal", deducciones=(), **w4):
    emp = motor.Empleado(regimen="ley4", tipo_pago="hora", tarifa=D(tarifa), w4_aplica=True, **w4)
    r = motor.calcular(empleado=emp, parametros=P2026, tasas=TASAS, frecuencia=frecuencia,
                       horas=Horas(regulares=D(horas)), deducciones=list(deducciones))
    return r


def test_tabla_2026_igual_a_la_publicada():
    casados = _tablas(2026)[("married", "estandar")]
    assert [(t.desde, t.cuota_fija, t.tasa) for t in casados[:3]] == [
        (D("0"), D("0"), D("0")), (D("19300"), D("0"), D("10")), (D("44100"), D("2480"), D("12"))]
    soltero = _tablas(2026)[("single", "estandar")]
    assert [(t.desde, t.cuota_fija) for t in soltero[1:4]] == [(D("7500"), 0), (D("19900"), D("1240")),
                                                               (D("57900"), D("5800"))]


@pytest.mark.parametrize("caso,esperado", [
    # Soltero, semanal $1,000: 52,000 − 8,600 = 43,400 → 1,240 + 12% × 23,500 = 4,060 ÷ 52
    (dict(tarifa="25"), D("78.08")),
    # Casado, bisemanal $3,000, dependientes $4,000: 78,000 − 12,900 = 65,100 → 2,480 + 12% × 21,000 = 5,000;
    # 5,000 ÷ 26 − 4,000 ÷ 26 = 38.46
    (dict(tarifa="37.50", horas="80", frecuencia="bisemanal", w4_estado_civil="married",
          w4_dependientes=D("4000")), D("38.46")),
    # Soltero con el paso 2 marcado: tabla de múltiples empleos (8,050; 14,250 → $620 + 12%; 33,250 → $2,900 + 22%)
    (dict(tarifa="25", w4_paso2=True), D("135.10")),
    # W-4 de 2019 o anterior, soltero, 1 exención: 52,000 − 4,300 = 47,700 → 1,240 + 12% × 27,800 = 4,576 ÷ 52
    (dict(tarifa="25", w4_version="2019", w4_exenciones=1), D("88.00")),
    # Jefe de familia, otros ingresos 5,200, deducciones 2,600, adicional $10 por período:
    # 52,000 + 5,200 − 2,600 − 8,600 = 46,000 → 1,770 + 12% × 12,750 = 3,300 ÷ 52 = 63.46 + 10
    (dict(tarifa="25", w4_estado_civil="head", w4_otros_ingresos=D("5200"), w4_deducciones=D("2600"),
          w4_retencion_adicional=D("10")), D("73.46")),
    # Salario bajo: no llega al primer tramo
    (dict(tarifa="5"), D("0.00")),
])
def test_hoja_1a(caso, esperado):
    r = federal(**caso)
    assert r.monto("retencion_federal") == esperado
    linea = next(l for l in r.retenciones if l.codigo == "retencion_federal")
    assert linea.explicacion


def test_deduccion_antes_de_federal_reduce_la_base():
    plan = TipoDeduccion("plan", "Plan 401(k)", antes_de_federal=True)
    r = federal("25", deducciones=[Monto(plan, D("50"))])
    # 950 × 52 = 49,400 − 8,600 = 40,800 → 1,240 + 12% × 20,900 = 3,748 ÷ 52
    assert r.tributables["federal"] == D("950.00") and r.monto("retencion_federal") == D("72.08")


def test_sin_w4_no_hay_retencion_federal():
    r = motor.calcular(empleado=motor.Empleado(regimen="ley4", tipo_pago="hora", tarifa=D("25")), parametros=P2026,
                       tasas=TASAS, frecuencia="semanal", horas=Horas(regulares=D("40")))
    assert not any(l.codigo == "retencion_federal" for l in r.retenciones)


def test_falta_la_tabla():
    sin_tablas = motor.Parametros(**{**PARAMS.__dict__, "tramos_federales": {}})
    emp = motor.Empleado(regimen="ley4", tipo_pago="hora", tarifa=D("25"), w4_aplica=True)
    with pytest.raises(motor.ErrorCalculo, match="retención federal"):
        motor.calcular(empleado=emp, parametros=sin_tablas, tasas=TASAS, frecuencia="semanal",
                       horas=Horas(regulares=D("40")))


@pytest.mark.django_db
def test_tablas_sembradas_y_nomina(compania, preparador):
    from apps.companias.models import TasasCompania
    from apps.nomina import servicios
    from apps.parametros.models import ParametrosAnuales

    from .conftest import crear_empleado
    from .test_nomina import entrar_horas, periodo_semana

    p = ParametrosAnuales.objects.get(anio=2026)
    assert p.tramos_federales.count() == 3 * 2 * 8 and p.estado == "por_verificar"
    TasasCompania.objects.create(compania=compania, anio=2026, suta_tasa=D("2.4"), aportacion_especial_tasa=D("1"),
                                 sinot_empleado_tasa=D("0.3"), sinot_patrono_tasa=D("0.3"))
    emp = crear_empleado(compania, tarifa="25", w4_aplica=True, fecha_empleo=date(2020, 1, 6))
    periodo = periodo_semana(compania, preparador)
    entrar_horas(periodo, emp, horas_regulares="40")
    assert servicios.calcular_periodo(periodo, preparador) == []
    r = periodo.resultados.get()
    assert r.trib_federal == D("1000.00")
    assert r.lineas.get(codigo="retencion_federal").monto == D("78.08")
    assert "tramos_federales" in periodo.parametros_usados
