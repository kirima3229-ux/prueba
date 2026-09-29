from datetime import date

import pytest

from apps.core import fechas


def test_feriados_2026():
    f = fechas.feriados_federales(2026)
    assert date(2026, 1, 19) in f  # MLK
    assert date(2026, 7, 3) in f  # 4 de julio cae sábado → viernes 3
    assert date(2026, 11, 26) in f  # Acción de Gracias
    assert date(2026, 5, 25) in f  # Recordación


@pytest.mark.parametrize("pago,vence", [
    (date(2026, 9, 18), date(2026, 10, 15)),
    (date(2026, 12, 31), date(2027, 1, 15)),
    (date(2026, 1, 9), date(2026, 2, 17)),  # 15 feb domingo, 16 feriado de Presidentes
])
def test_mensual(pago, vence):
    assert fechas.vence_mensual(pago) == vence


@pytest.mark.parametrize("pago,vence", [
    (date(2026, 9, 16), date(2026, 9, 23)),  # miércoles → miércoles
    (date(2026, 9, 18), date(2026, 9, 23)),  # viernes → miércoles
    (date(2026, 9, 19), date(2026, 9, 25)),  # sábado → viernes
    (date(2026, 9, 22), date(2026, 9, 25)),  # martes → viernes
    (date(2026, 11, 20), date(2026, 11, 25)),
    (date(2026, 11, 24), date(2026, 11, 27)),
    (date(2026, 7, 1), date(2026, 7, 8)),
])
def test_bisemanal(pago, vence):
    assert fechas.vence_bisemanal(pago) == vence


def test_trimestral():
    assert fechas.vence_trimestral(2026, 3) == date(2026, 11, 2)  # 31 oct sábado → lunes 2 nov
    assert fechas.vence_trimestral(2026, 4) == date(2027, 2, 1)  # 31 ene domingo
    assert fechas.vence_trimestral(2026, 1) == date(2026, 4, 30)
    assert fechas.rango_trimestre(2026, 2) == (date(2026, 4, 1), date(2026, 6, 30))
