"""
Calculadora de mesada (Ley 80-1976) — referencia para terminaciones.

- La mesada solo aplica a despidos sin justa causa, fuera del período probatorio.
- El "salario mensual base" lo indica el usuario según la regla de su régimen:
  antes de Ley 4-2017, el salario más alto de los últimos 3 años; Ley 4-2017, el
  de los 30 días consecutivos con más horas regulares del último año.
- Semana de sueldo = salario mensual × 12 ÷ 52.
- Los años de servicio para las semanas son años completos; el tramo se escoge
  con la antigüedad exacta ("a partir del año X más un día").
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .licencias import anios_de_servicio

CERO = Decimal("0")


def redondear(valor) -> Decimal:
    return Decimal(valor).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ReglaMesada:
    regimen: str
    anios_desde: Decimal
    anios_hasta: Decimal | None
    meses_sueldo: Decimal
    semanas_por_anio: Decimal
    tope_meses: Decimal | None


@dataclass(frozen=True)
class ResultadoMesada:
    aplica: bool
    monto: Decimal
    anios_servicio: Decimal
    anios_completos: int
    explicacion: str


def regla_aplicable(reglas, regimen, anios) -> ReglaMesada | None:
    for r in reglas:
        if r.regimen != regimen:
            continue
        desde_ok = anios >= 0 if r.anios_desde == 0 else anios > r.anios_desde
        hasta_ok = r.anios_hasta is None or anios <= r.anios_hasta
        if desde_ok and hasta_ok:
            return r
    return None


def calcular_mesada(
    *, regimen: str, fecha_empleo: date, fecha_despido: date, salario_mensual, reglas,
    periodo_probatorio: bool = False,
) -> ResultadoMesada:
    salario_mensual = Decimal(salario_mensual)
    anios = anios_de_servicio(fecha_empleo, fecha_despido)
    completos = int(anios)
    if periodo_probatorio:
        return ResultadoMesada(False, CERO, anios, completos,
                               "Despido durante el período probatorio: no aplica mesada.")
    if fecha_despido <= fecha_empleo:
        return ResultadoMesada(False, CERO, anios, completos, "La fecha de despido debe ser posterior a la de empleo.")
    regla = regla_aplicable(reglas, regimen, anios)
    if regla is None:
        return ResultadoMesada(False, CERO, anios, completos, "No hay regla de mesada para este régimen y antigüedad.")

    semanal = salario_mensual * 12 / 52
    parte_meses = regla.meses_sueldo * salario_mensual
    semanas = regla.semanas_por_anio * completos
    parte_semanas = semanas * semanal
    total = parte_meses + parte_semanas
    lineas = [
        f"Servicio: {anios:.2f} años ({completos} completos). Salario mensual base ${salario_mensual:,.2f}; "
        f"semanal ${redondear(semanal):,.2f} (× 12 ÷ 52).",
        f"{regla.meses_sueldo.normalize():f} meses × ${salario_mensual:,.2f} = ${redondear(parte_meses):,.2f}.",
        f"{regla.semanas_por_anio.normalize():f} semana(s) × {completos} año(s) = {semanas.normalize():f} semanas × "
        f"${redondear(semanal):,.2f} = ${redondear(parte_semanas):,.2f}.",
    ]
    if regla.tope_meses is not None:
        tope = regla.tope_meses * salario_mensual
        if total > tope:
            lineas.append(f"Tope de {regla.tope_meses.normalize():f} meses de sueldo: ${redondear(tope):,.2f}.")
            total = tope
    total = redondear(total)
    lineas.append(f"Mesada: ${total:,.2f}.")
    return ResultadoMesada(True, total, anios, completos, "\n".join(lineas))
