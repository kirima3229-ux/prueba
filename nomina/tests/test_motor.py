"""
Pruebas del motor de cálculo con casos calculados a mano.
Los parámetros son los valores iniciales de 2026 (POR VERIFICAR); cuando
Quality Group entregue casos reales, se añaden aquí como pruebas adicionales.
"""

from decimal import Decimal as D

import pytest

from apps.calculo import motor
from apps.calculo.motor import Acumulados, Concepto, Horas, Monto, TipoDeduccion

TRAMOS = (
    motor.Tramo(D("0"), D("9000"), D("0"), D("0")),
    motor.Tramo(D("9000"), D("25000"), D("0"), D("7")),
    motor.Tramo(D("25000"), D("41500"), D("1120"), D("14")),
    motor.Tramo(D("41500"), D("61500"), D("3430"), D("25")),
    motor.Tramo(D("61500"), None, D("8430"), D("33")),
)
PARAMS = motor.Parametros(
    anio=2026, ss_tasa_empleado=D("6.2"), ss_tasa_patrono=D("6.2"), ss_tope=D("184500"),
    medicare_tasa_empleado=D("1.45"), medicare_tasa_patrono=D("1.45"),
    medicare_adicional_tasa=D("0.9"), medicare_adicional_umbral=D("200000"),
    futa_tasa=D("0.6"), futa_tope=D("7000"), desempleo_tope=D("7000"), sinot_tope=D("9000"),
    choferil_empleado_semanal=D("0.50"), choferil_patrono_semanal=D("0.30"),
    exencion_personal_individuo=D("0"), exencion_personal_casado=D("0"),
    exencion_dependiente=D("2500"), exencion_dependiente_custodia=D("1250"), exencion_veterano=D("1500"),
    tramos=TRAMOS,
    horas_extra={
        "anterior": motor.ReglaHorasExtra(D("2"), D("2"), D("2"), D("2")),
        "ley4": motor.ReglaHorasExtra(D("1.5"), D("1.5"), D("1.5"), D("1.5")),
    },
    salario_minimo=D("10.50"),
    verificado=True,
)
TASAS = motor.TasasCompania(
    suta=D("2.4"), aportacion_especial=D("1"), sinot_empleado=D("0.3"), sinot_patrono=D("0.3"),
    cfse_por_100=D("3.5"), verificadas=True,
)
POR_HORA = motor.Empleado(regimen="ley4", tipo_pago="hora", tarifa=D("12"))

PLAN_MEDICO = TipoDeduccion("plan_medico", "Plan médico", antes_de_pr=True, antes_de_federal=True, antes_de_fica=True)
RETIRO_1165E = TipoDeduccion("retiro_1165e", "Retiro 1165(e)", antes_de_pr=True)
PRESTAMO = TipoDeduccion("prestamo", "Préstamo")
REEMBOLSO = Concepto("reembolso", "Reembolso", pr=False, ss=False, medicare=False, futa=False, desempleo=False, sinot=False, cfse=False)
PROPINAS = Concepto("propinas", "Propinas", cfse=False)


def calc(empleado=POR_HORA, horas=Horas(regulares=D("40")), frecuencia="semanal", **extra):
    return motor.calcular(empleado=empleado, parametros=PARAMS, tasas=TASAS, frecuencia=frecuencia, horas=horas, **extra)


def test_caso_base_semanal():
    r = calc()
    assert r.bruto == D("480.00")
    # 480 × 52 = 24,960; (24,960 − 9,000) × 7% = 1,117.20 anual ÷ 52 = 21.48
    assert r.monto("retencion_pr") == D("21.48")
    assert r.monto("ss_empleado") == D("29.76")
    assert r.monto("medicare_empleado") == D("6.96")
    assert r.monto("sinot_empleado") == D("1.44")
    assert r.neto == D("420.36")
    assert r.monto("ss_patrono") == D("29.76")
    assert r.monto("medicare_patrono") == D("6.96")
    assert r.monto("futa") == D("2.88")
    assert r.monto("suta") == D("11.52")
    assert r.monto("aportacion_especial") == D("4.80")
    assert r.monto("sinot_patrono") == D("1.44")
    assert r.monto("cfse") == D("16.80")
    assert r.alertas == []


def test_tabla_por_tramos():
    assert motor.impuesto_por_tabla(D("9000"), TRAMOS)[0] == D("0")
    assert motor.impuesto_por_tabla(D("25000"), TRAMOS)[0] == D("1120")
    assert motor.impuesto_por_tabla(D("41500"), TRAMOS)[0] == D("3430")
    assert motor.impuesto_por_tabla(D("100000"), TRAMOS)[0] == D("21135")  # 8,430 + 38,500 × 33%
    assert motor.impuesto_por_tabla(D("0"), TRAMOS)[0] == D("0")


@pytest.mark.parametrize("regimen,esperado", [("anterior", D("48.00")), ("ley4", D("36.00"))])
def test_horas_extra_segun_regimen(regimen, esperado):
    emp = motor.Empleado(regimen=regimen, tipo_pago="hora", tarifa=D("12"))
    r = calc(emp, Horas(regulares=D("40"), extra_diarias=D("2")))
    assert r.monto("horas_extra") == esperado


def test_todas_las_clases_de_horas_extra():
    r = calc(horas=Horas(regulares=D("40"), extra_diarias=D("1"), extra_semanales=D("2"), septimo_dia=D("3"), periodo_alimentos=D("1")))
    horas_extra = [l for l in r.ingresos if l.codigo == "horas_extra"]
    assert len(horas_extra) == 4
    assert sum(l.monto for l in horas_extra) == D("7") * D("12") * D("1.5")


def test_asalariado_horas_extra_con_tarifa_derivada():
    emp = motor.Empleado(regimen="ley4", tipo_pago="salario", tarifa=D("800"), horas_regulares_periodo=D("40"))
    r = calc(emp, Horas(extra_semanales=D("4")))
    assert r.monto("regular") == D("800.00")
    assert r.monto("horas_extra") == D("120.00")  # 800/40 = 20 × 1.5 × 4


def test_asalariado_sin_horas_regulares_no_calcula_horas_extra():
    emp = motor.Empleado(regimen="ley4", tipo_pago="salario", tarifa=D("800"))
    with pytest.raises(motor.ErrorCalculo):
        calc(emp, Horas(extra_semanales=D("4")))


def test_exento_no_cobra_horas_extra():
    emp = motor.Empleado(regimen="ley4", tipo_pago="exento", tarifa=D("1500"), horas_regulares_periodo=D("40"))
    r = calc(emp, Horas(extra_semanales=D("5")))
    assert r.bruto == D("1500.00")
    assert any("exento" in a for a in r.alertas)


def test_tope_seguro_social():
    r = calc(horas=Horas(regulares=D("40")), acumulados=Acumulados(ss=D("184300")))
    assert r.monto("ss_empleado") == D("12.40")  # solo 200 hasta el tope
    assert r.monto("medicare_empleado") == D("6.96")  # Medicare no tiene tope


def test_medicare_adicional_al_cruzar_200000():
    emp = motor.Empleado(regimen="ley4", tipo_pago="salario", tarifa=D("1000"))
    r = calc(emp, Horas(), acumulados=Acumulados(medicare=D("199500")))
    assert r.monto("medicare_adicional") == D("4.50")  # 500 × 0.9%
    r = calc(emp, Horas(), acumulados=Acumulados(medicare=D("250000")))
    assert r.monto("medicare_adicional") == D("9.00")
    assert calc(emp, Horas()).monto("medicare_adicional") == D("0")


def test_topes_futa_desempleo_y_sinot():
    r = calc(acumulados=Acumulados(futa=D("6800"), desempleo=D("7000"), sinot=D("8900")))
    assert r.monto("futa") == D("1.20")  # 200 × 0.6%
    assert r.monto("suta") == D("0.00") and r.monto("aportacion_especial") == D("0.00")
    assert r.monto("sinot_empleado") == D("0.30")  # 100 × 0.3%


def test_deducciones_antes_y_despues_de_contribuciones():
    deducciones = [Monto(PLAN_MEDICO, D("50")), Monto(RETIRO_1165E, D("20")), Monto(PRESTAMO, D("25"))]
    r = calc(deducciones=deducciones)
    assert r.tributables["pr"] == D("410.00")  # 480 − 50 − 20
    assert r.tributables["ss"] == D("430.00")  # 480 − 50 (el 1165(e) no reduce FICA)
    assert r.monto("ss_empleado") == D("26.66")
    assert r.total_deducciones == D("95.00")
    assert r.neto == r.bruto - r.total_retenciones - D("95")


def test_ingresos_no_tributables_y_propinas():
    r = calc(otros_ingresos=[Monto(REEMBOLSO, D("100")), Monto(PROPINAS, D("60"))])
    assert r.bruto == D("640.00")
    assert r.tributables["pr"] == D("540.00") and r.tributables["ss"] == D("540.00")
    assert r.tributables["cfse"] == D("480.00")


def test_exenciones_499_r4():
    emp = motor.Empleado(regimen="ley4", tipo_pago="hora", tarifa=D("12"), r4_dependientes=2)
    # 24,960 − 5,000 = 19,960; 10,960 × 7% = 767.20 ÷ 52 = 14.75
    assert calc(emp).monto("retencion_pr") == D("14.75")
    emp = motor.Empleado(regimen="ley4", tipo_pago="hora", tarifa=D("12"), r4_veterano=True,
                         r4_dependientes_custodia_compartida=1, r4_concesion_deducciones=D("1000"))
    # 24,960 − 1,500 − 1,250 − 1,000 = 21,210; 12,210 × 7% = 854.70 ÷ 52 = 16.44
    assert calc(emp).monto("retencion_pr") == D("16.44")


def test_retencion_adicional():
    emp = motor.Empleado(regimen="ley4", tipo_pago="hora", tarifa=D("12"), r4_retencion_adicional=D("10"))
    assert calc(emp).monto("retencion_pr") == D("31.48")


def test_frecuencia_mensual():
    emp = motor.Empleado(regimen="ley4", tipo_pago="salario", tarifa=D("3000"))
    r = calc(emp, Horas(), frecuencia="mensual")
    # 36,000 anual: 1,120 + 11,000 × 14% = 2,660 ÷ 12 = 221.67
    assert r.monto("retencion_pr") == D("221.67")


def test_seguro_choferil():
    emp = motor.Empleado(regimen="ley4", tipo_pago="hora", tarifa=D("12"), aplica_choferil=True)
    r = calc(emp)
    assert r.monto("choferil_empleado") == D("0.50") and r.monto("choferil_patrono") == D("0.30")
    r = calc(emp, Horas(regulares=D("80")), frecuencia="bisemanal")
    assert r.monto("choferil_empleado") == D("1.00")
    assert calc(emp, semanas_choferil=5, frecuencia="mensual").monto("choferil_patrono") == D("1.50")
    assert calc().monto("choferil_empleado") == D("0")


def test_alertas():
    emp = motor.Empleado(regimen="ley4", tipo_pago="hora", tarifa=D("9"))
    r = calc(emp, deducciones=[Monto(PRESTAMO, D("1000"))])
    textos = " ".join(r.alertas)
    assert "salario mínimo" in textos
    assert "negativo" in textos
    sin_verificar = motor.Parametros(**{**PARAMS.__dict__, "verificado": False})
    r = motor.calcular(empleado=POR_HORA, parametros=sin_verificar, tasas=TASAS, frecuencia="semanal",
                       horas=Horas(regulares=D("40")))
    assert any("POR VERIFICAR" in a for a in r.alertas)


def test_sin_tasa_cfse():
    tasas = motor.TasasCompania(**{**TASAS.__dict__, "cfse_por_100": None})
    r = motor.calcular(empleado=POR_HORA, parametros=PARAMS, tasas=tasas, frecuencia="semanal", horas=Horas(regulares=D("40")))
    assert r.monto("cfse") == D("0") and any("CFSE" in a for a in r.alertas)


def test_licencias_pagadas():
    r = calc(horas=Horas(regulares=D("32"), vacaciones=D("8")))
    assert r.monto("vacaciones") == D("96.00") and r.bruto == D("480.00")


def test_cada_linea_tiene_explicacion():
    r = calc(deducciones=[Monto(PLAN_MEDICO, D("50"))])
    for linea in r.ingresos + r.retenciones + r.patronales + r.deducciones:
        assert linea.explicacion, linea.codigo


# --- Empleados con propinas (meseros) --------------------------------------------

MESERO = motor.Empleado(regimen="ley4", tipo_pago="hora", tarifa=D("4"), recibe_propinas=True)


def test_mesero_licencias_se_pagan_al_salario_minimo():
    r = calc(MESERO, Horas(regulares=D("40"), vacaciones=D("8"), enfermedad=D("4")),
             otros_ingresos=[Monto(PROPINAS, D("400"))])
    assert r.monto("regular") == D("160.00")         # 40 h a su tarifa de $4
    assert r.monto("vacaciones") == D("84.00")       # 8 h al mínimo de $10.50
    assert r.monto("enfermedad") == D("42.00")       # 4 h al mínimo
    vacaciones = next(l for l in r.ingresos if l.codigo == "vacaciones")
    assert "al salario mínimo" in vacaciones.explicacion
    # Con propinas suficientes no hay alerta de salario mínimo.
    assert not any("mínimo" in a for a in r.alertas)


def test_mesero_propinas_insuficientes():
    r = calc(MESERO, Horas(regulares=D("40")), otros_ingresos=[Monto(PROPINAS, D("100"))])
    # 40 h × $10.50 = $420; $160 + $100 = $260 → faltan $160
    assert any("debe completar $160.00" in a for a in r.alertas)


def test_mesero_bajo_el_minimo_en_efectivo():
    params = motor.Parametros(**{**PARAMS.__dict__, "salario_minimo_propinas": D("3")})
    emp = motor.Empleado(regimen="ley4", tipo_pago="hora", tarifa=D("2"), recibe_propinas=True)
    r = motor.calcular(empleado=emp, parametros=params, tasas=TASAS, frecuencia="semanal",
                       horas=Horas(regulares=D("40")), otros_ingresos=[Monto(PROPINAS, D("500"))])
    assert any("mínimo en efectivo" in a for a in r.alertas)


def test_empleado_sin_propinas_bajo_el_minimo_si_alerta():
    emp = motor.Empleado(regimen="ley4", tipo_pago="hora", tarifa=D("8"))
    r = calc(emp, Horas(regulares=D("40"), vacaciones=D("8")))
    assert any("por debajo del salario mínimo" in a for a in r.alertas)
    assert r.monto("vacaciones") == D("84.00")  # las licencias nunca bajo el mínimo


def test_licencias_a_su_tarifa_si_es_mayor_que_el_minimo():
    r = calc(horas=Horas(regulares=D("32"), vacaciones=D("8")))
    assert r.monto("vacaciones") == D("96.00")  # 8 × $12


def test_asalariado_licencias_incluidas_en_el_salario():
    emp = motor.Empleado(regimen="ley4", tipo_pago="salario", tarifa=D("800"), horas_regulares_periodo=D("40"))
    r = calc(emp, Horas(vacaciones=D("8")))
    assert r.bruto == D("800.00") and r.monto("vacaciones") == D("0")
    assert any("incluidas en el salario" in a for a in r.alertas)


@pytest.mark.parametrize(
    "tarifa,regimen,esperado",
    [
        # Opinión del Secretario DTRH 2024-01: 1.5 × $10.50 − $8.37 = $7.38 por hora extra
        (D("2.13"), "ley4", D("22.14")),   # 3 h × 7.38
        (D("4"), "ley4", D("27.75")),      # 3 h × (15.75 − 6.50)
        (D("2.13"), "anterior", D("37.89")),  # 3 h × (2 × 10.50 − 8.37) = 3 × 12.63
    ],
)
def test_horas_extra_de_meseros_sobre_el_salario_minimo(tarifa, regimen, esperado):
    emp = motor.Empleado(regimen=regimen, tipo_pago="hora", tarifa=tarifa, recibe_propinas=True)
    r = calc(emp, Horas(regulares=D("40"), extra_semanales=D("3")), otros_ingresos=[Monto(PROPINAS, D("600"))])
    assert r.monto("horas_extra") == esperado
    linea = next(l for l in r.ingresos if l.codigo == "horas_extra")
    assert "crédito por propinas" in linea.explicacion


def test_credito_por_propinas_incluye_horas_extra():
    emp = motor.Empleado(regimen="ley4", tipo_pago="hora", tarifa=D("2.13"), recibe_propinas=True)
    # 43 h × $8.37 = $359.91 de crédito; propinas $300 → faltan $59.91
    r = calc(emp, Horas(regulares=D("40"), extra_semanales=D("3")), otros_ingresos=[Monto(PROPINAS, D("300"))])
    assert any("debe completar $59.91" in a for a in r.alertas)


def test_empleado_sin_propinas_horas_extra_a_su_tarifa():
    assert calc(horas=Horas(regulares=D("40"), extra_semanales=D("2"))).monto("horas_extra") == D("36.00")
