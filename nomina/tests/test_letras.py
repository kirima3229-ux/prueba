from decimal import Decimal as D

import pytest

from apps.core.letras import monto_en_letras


@pytest.mark.parametrize("monto,esperado", [
    ("0.50", "CERO DÓLARES CON 50/100"),
    ("1", "UN DÓLAR CON 00/100"),
    ("15.05", "QUINCE DÓLARES CON 05/100"),
    ("21", "VEINTIÚN DÓLARES CON 00/100"),
    ("31", "TREINTA Y UN DÓLARES CON 00/100"),
    ("100", "CIEN DÓLARES CON 00/100"),
    ("101.10", "CIENTO UN DÓLARES CON 10/100"),
    ("516.99", "QUINIENTOS DIECISÉIS DÓLARES CON 99/100"),
    ("777", "SETECIENTOS SETENTA Y SIETE DÓLARES CON 00/100"),
    ("1000", "MIL DÓLARES CON 00/100"),
    ("1234.56", "MIL DOSCIENTOS TREINTA Y CUATRO DÓLARES CON 56/100"),
    ("21001", "VEINTIÚN MIL UN DÓLARES CON 00/100"),
    ("100000", "CIEN MIL DÓLARES CON 00/100"),
    ("901915.40", "NOVECIENTOS UN MIL NOVECIENTOS QUINCE DÓLARES CON 40/100"),
    ("1000000", "UN MILLÓN DE DÓLARES CON 00/100"),
    ("2500100", "DOS MILLONES QUINIENTOS MIL CIEN DÓLARES CON 00/100"),
    ("12.345", "DOCE DÓLARES CON 35/100"),
])
def test_espanol(monto, esperado):
    assert monto_en_letras(D(monto)) == esperado


@pytest.mark.parametrize("monto,esperado", [
    ("1", "ONE AND 00/100 DOLLAR"),
    ("1234.56", "ONE THOUSAND TWO HUNDRED THIRTY-FOUR AND 56/100 DOLLARS"),
    ("15", "FIFTEEN AND 00/100 DOLLARS"),
    ("2000017.01", "TWO MILLION SEVENTEEN AND 01/100 DOLLARS"),
])
def test_ingles(monto, esperado):
    assert monto_en_letras(D(monto), "en") == esperado


def test_negativo():
    with pytest.raises(ValueError):
        monto_en_letras(D("-1"))
