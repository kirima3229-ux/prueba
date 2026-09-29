"""Cálculo de la retención por servicios prestados (sin base de datos)."""

from decimal import Decimal as D

import pytest

from apps.servicios.calculo import Tratamiento, calcular_retencion, retencion_esperada

GENERAL = dict(tasa_general=D("10"), exencion_anual=D("500"))


def calc(monto, acumulado="0", **extra):
    return calcular_retencion(monto=D(monto), acumulado_previo=D(acumulado), **{**GENERAL, **extra})


@pytest.mark.parametrize(
    "monto,acumulado,exencion,base,retencion",
    [
        ("400", "0", "400", "0", "0.00"),          # dentro de los primeros $500
        ("500", "0", "500", "0", "0.00"),          # exactamente $500
        ("300", "400", "100", "200", "20.00"),     # cruza el umbral: solo el exceso
        ("1000", "600", "0", "1000", "100.00"),    # exención ya consumida
        ("1500", "0", "500", "1000", "100.00"),    # un solo pago grande
        ("100", "500", "0", "100", "10.00"),       # justo después del umbral
    ],
)
def test_exencion_primeros_500(monto, acumulado, exencion, base, retencion):
    r = calc(monto, acumulado)
    assert r.exencion_aplicada == D(exencion)
    assert r.base_sujeta == D(base)
    assert r.retencion == D(retencion)
    assert r.neto == D(monto) - D(retencion)
    assert r.tratamiento == Tratamiento.GENERAL


def test_redondeo_al_centavo_mitad_hacia_arriba():
    assert calc("533.33").retencion == D("3.33")   # 3.333
    assert calc("533.35").retencion == D("3.34")   # 3.335 → 3.34


def test_relevo_parcial():
    r = calc("1500", tratamiento=Tratamiento.RELEVO_PARCIAL, tasa_relevo_parcial=D("5"))
    assert r.tasa == D("5") and r.retencion == D("50.00")


@pytest.mark.parametrize(
    "tratamiento", [Tratamiento.RELEVO_TOTAL, Tratamiento.DECLARACION_JURADA, Tratamiento.EXENTO_PAGO]
)
def test_sin_retencion(tratamiento):
    r = calc("2000", tratamiento=tratamiento)
    assert r.retencion == D("0.00") and r.neto == D("2000.00")
    # La exención igual se consume: el total pagado cuenta para la 480.6SP.
    assert r.exencion_aplicada == D("500")


def test_tasa_y_exencion_vienen_de_configuracion():
    r = calcular_retencion(monto=D("2000"), acumulado_previo=D("0"), tasa_general=D("7"), exencion_anual=D("0"))
    assert r.retencion == D("140.00")


def test_monto_invalido():
    with pytest.raises(ValueError):
        calc("0")
    with pytest.raises(ValueError):
        calc("-10")


def test_relevo_parcial_sin_porcentaje():
    with pytest.raises(ValueError):
        calc("1000", tratamiento=Tratamiento.RELEVO_PARCIAL)


def test_explicacion_legible():
    texto = calc("300", "400").explicacion
    assert "$400.00" in texto and "$200.00" in texto and "$20.00 retenido" in texto


def test_retencion_esperada_para_conciliar():
    # Tres pagos de $400 al 10%: 0 + 30 + 40 = 70.
    assert retencion_esperada([(D("400"), D("10"))] * 3, D("500")) == D("70.00")


def test_relevo_parcial_respeta_los_primeros_500_al_cruzar_el_umbral():
    # Confirmado por Quality Group: con relevo parcial, los primeros $500 del año siguen exentos.
    r = calc("1000", "400", tratamiento=Tratamiento.RELEVO_PARCIAL, tasa_relevo_parcial=D("5"))
    assert r.exencion_aplicada == D("100") and r.base_sujeta == D("900")
    assert r.retencion == D("45.00")
