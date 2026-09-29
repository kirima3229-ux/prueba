"""
Fechas de vencimiento de depósitos y planillas.

Reglas (POR VERIFICAR con las publicaciones vigentes del IRS, Hacienda y el DTRH):
- Mensual: el día 15 del mes siguiente al pago.
- Bisemanal (semiweekly del IRS): pagos de miércoles a viernes vencen el miércoles siguiente;
  de sábado a martes, el viernes siguiente.
- Trimestral: el último día del mes siguiente al trimestre.
Si la fecha cae en sábado, domingo o feriado federal, pasa al próximo día laborable.
Los feriados sólo de Puerto Rico no están incluidos.
"""

import calendar
from datetime import date, timedelta


def _enesimo_dia_semana(anio, mes, dia_semana, n):
    """n-ésimo (1..5) día de la semana (0 = lunes) del mes; n = -1 es el último."""
    if n > 0:
        primero = date(anio, mes, 1)
        return primero + timedelta(days=(dia_semana - primero.weekday()) % 7 + 7 * (n - 1))
    ultimo = date(anio, mes, calendar.monthrange(anio, mes)[1])
    return ultimo - timedelta(days=(ultimo.weekday() - dia_semana) % 7)


def _observado(fecha):
    if fecha.weekday() == 5:
        return fecha - timedelta(days=1)
    if fecha.weekday() == 6:
        return fecha + timedelta(days=1)
    return fecha


def feriados_federales(anio: int) -> set[date]:
    fijos = [date(anio, 1, 1), date(anio, 6, 19), date(anio, 7, 4), date(anio, 11, 11), date(anio, 12, 25)]
    moviles = [
        _enesimo_dia_semana(anio, 1, 0, 3),   # Martin Luther King
        _enesimo_dia_semana(anio, 2, 0, 3),   # Presidentes
        _enesimo_dia_semana(anio, 5, 0, -1),  # Recordación
        _enesimo_dia_semana(anio, 9, 0, 1),   # Trabajo
        _enesimo_dia_semana(anio, 10, 0, 2),  # Colón
        _enesimo_dia_semana(anio, 11, 3, 4),  # Acción de Gracias
    ]
    return {_observado(f) for f in fijos} | set(moviles)


def es_laborable(fecha: date) -> bool:
    return fecha.weekday() < 5 and fecha not in feriados_federales(fecha.year)


def proximo_laborable(fecha: date) -> date:
    while not es_laborable(fecha):
        fecha += timedelta(days=1)
    return fecha


def vence_mensual(fecha_pago: date) -> date:
    anio, mes = (fecha_pago.year + 1, 1) if fecha_pago.month == 12 else (fecha_pago.year, fecha_pago.month + 1)
    return proximo_laborable(date(anio, mes, 15))


def vence_bisemanal(fecha_pago: date) -> date:
    dia = fecha_pago.weekday()
    if dia in (2, 3, 4):  # miércoles a viernes → miércoles siguiente
        vence = fecha_pago + timedelta(days=(2 - dia) % 7 or 7)
    else:  # sábado a martes → viernes siguiente
        vence = fecha_pago + timedelta(days=(4 - dia) % 7)
    return proximo_laborable(vence)


def trimestre_de(fecha: date) -> int:
    return (fecha.month - 1) // 3 + 1


def rango_trimestre(anio: int, trimestre: int) -> tuple[date, date]:
    mes_fin = trimestre * 3
    return date(anio, mes_fin - 2, 1), date(anio, mes_fin, calendar.monthrange(anio, mes_fin)[1])


def rango_mes(anio: int, mes: int) -> tuple[date, date]:
    return date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])


def vence_trimestral(anio: int, trimestre: int) -> date:
    _, fin = rango_trimestre(anio, trimestre)
    mes = fin.month + 1 if fin.month < 12 else 1
    anio_v = anio if fin.month < 12 else anio + 1
    return proximo_laborable(date(anio_v, mes, calendar.monthrange(anio_v, mes)[1]))
