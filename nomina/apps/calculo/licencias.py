"""
Vacaciones, licencia por enfermedad y bono de Navidad (Python puro).

Las reglas vienen de la configuración por año (ReglaLicencia, ReglaBonoNavidad).
Las horas de licencia se guardan en horas: días × horas por día.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

CERO = Decimal("0")
CIEN = Decimal("100")


def redondear(valor, lugares="0.01") -> Decimal:
    return Decimal(valor).quantize(Decimal(lugares), rounding=ROUND_HALF_UP)


def _aniversario(fecha: date, anio: int) -> date:
    try:
        return fecha.replace(year=anio)
    except ValueError:  # 29 de febrero en año no bisiesto
        return date(anio, 3, 1)


def anios_de_servicio(fecha_empleo: date, al: date) -> Decimal:
    """
    Años de servicio: entero en la fecha exacta del aniversario y con fracción
    desde el día siguiente ("el primer año más un día" ya es más de 1 año).
    """
    if al <= fecha_empleo:
        return CERO
    anios = al.year - fecha_empleo.year
    ultimo = _aniversario(fecha_empleo, fecha_empleo.year + anios)
    if ultimo > al:
        anios -= 1
        ultimo = _aniversario(fecha_empleo, fecha_empleo.year + anios)
    siguiente = _aniversario(fecha_empleo, fecha_empleo.year + anios + 1)
    fraccion = Decimal((al - ultimo).days) / Decimal((siguiente - ultimo).days)
    return Decimal(anios) + fraccion


# --- Licencias ------------------------------------------------------------------------


@dataclass(frozen=True)
class ReglaLicencia:
    tipo: str
    regimen: str
    tamano: str
    anios_desde: Decimal
    anios_hasta: Decimal | None
    horas_minimas_mes: Decimal
    dias_por_mes: Decimal


@dataclass(frozen=True)
class Acumulacion:
    tipo: str
    horas: Decimal
    explicacion: str


def tamano_patrono(numero_empleados: int, limite_pequeno: int) -> str:
    return "pequeno" if numero_empleados <= limite_pequeno else "grande"


def regla_aplicable(reglas, tipo, regimen, tamano, anios) -> ReglaLicencia | None:
    for r in reglas:
        if r.tipo != tipo or r.regimen != regimen or r.tamano != tamano:
            continue
        # Ley 4-2017: cada tramo empieza "a partir del año X más un día", así que el
        # mes del aniversario exacto todavía pertenece al tramo anterior.
        desde_ok = anios >= 0 if r.anios_desde == 0 else anios > r.anios_desde
        hasta_ok = r.anios_hasta is None or anios <= r.anios_hasta
        if desde_ok and hasta_ok:
            return r
    return None


def acumular_mes(
    *, tipo, regimen, numero_empleados, limite_pequeno, fecha_empleo, fin_de_mes, horas_trabajadas,
    horas_por_dia, reglas, balance_actual=CERO, tope_horas=None,
) -> Acumulacion:
    """Horas de licencia que se acumulan en un mes (0 si no llega a las horas mínimas o al tope)."""
    nombre = "vacaciones" if tipo == "vacaciones" else "enfermedad"
    tamano = tamano_patrono(numero_empleados, limite_pequeno)
    anios = anios_de_servicio(fecha_empleo, fin_de_mes)
    regla = regla_aplicable(reglas, tipo, regimen, tamano, anios)
    if regla is None:
        return Acumulacion(tipo, CERO, f"No hay regla de {nombre} para este régimen/tamaño/antigüedad.")
    horas_trabajadas = Decimal(horas_trabajadas)
    if horas_trabajadas < regla.horas_minimas_mes:
        return Acumulacion(
            tipo, CERO,
            f"Trabajó {horas_trabajadas} h en el mes; se requieren {regla.horas_minimas_mes} h para acumular {nombre}.",
        )
    horas = redondear(regla.dias_por_mes * Decimal(horas_por_dia))
    texto = (
        f"{regla.dias_por_mes} día(s) × {horas_por_dia} h = {horas} h de {nombre} "
        f"({anios:.1f} años de servicio; {horas_trabajadas} h trabajadas; patrono "
        f"{'pequeño' if tamano == 'pequeno' else 'de más de ' + str(limite_pequeno) + ' empleados'})."
    )
    if tope_horas is not None:
        disponible = max(CERO, Decimal(tope_horas) - Decimal(balance_actual))
        if horas > disponible:
            texto += f" Tope de {tope_horas} h: se acumulan solo {disponible} h."
            horas = disponible
    return Acumulacion(tipo, horas, texto)


def tope_horas(tipo, *, dias_por_mes_actual, horas_por_dia, tope_vacaciones_meses, tope_enfermedad_dias):
    if tipo == "vacaciones":
        return redondear(Decimal(dias_por_mes_actual) * Decimal(horas_por_dia) * tope_vacaciones_meses)
    return redondear(Decimal(tope_enfermedad_dias) * Decimal(horas_por_dia))


# --- Bono de Navidad ---------------------------------------------------------------


@dataclass(frozen=True)
class ReglaBono:
    regimen: str
    mes_inicio_periodo: int
    horas_minimas: Decimal
    umbral_empleados: int
    porcentaje_grande: Decimal
    tope_grande: Decimal
    porcentaje_pequeno: Decimal
    tope_pequeno: Decimal
    tope_salario: Decimal | None


@dataclass(frozen=True)
class ResultadoBono:
    elegible: bool
    monto: Decimal
    explicacion: str


def periodo_bono(anio: int, mes_inicio: int = 10) -> tuple[date, date]:
    """Período del bono que se paga en diciembre de `anio` (p. ej. 1-oct-2025 a 30-sep-2026)."""
    from calendar import monthrange

    inicio = date(anio - 1, mes_inicio, 1)
    mes_fin = mes_inicio - 1 or 12
    anio_fin = anio if mes_inicio > 1 else anio - 1
    return inicio, date(anio_fin, mes_fin, monthrange(anio_fin, mes_fin)[1])


def calcular_bono(*, regla: ReglaBono, numero_empleados: int, horas_trabajadas, salario) -> ResultadoBono:
    horas_trabajadas, salario = Decimal(horas_trabajadas), Decimal(salario)
    if horas_trabajadas < regla.horas_minimas:
        return ResultadoBono(
            False, CERO,
            f"Trabajó {horas_trabajadas} h en el período; se requieren {regla.horas_minimas} h. No tiene derecho.",
        )
    grande = numero_empleados > regla.umbral_empleados
    porcentaje = regla.porcentaje_grande if grande else regla.porcentaje_pequeno
    tope = regla.tope_grande if grande else regla.tope_pequeno
    base = min(salario, regla.tope_salario) if regla.tope_salario is not None else salario
    calculado = redondear(base * porcentaje / CIEN)
    monto = min(calculado, tope)
    texto = (
        f"Patrono de {numero_empleados} empleados ({'más' if grande else 'hasta'} {regla.umbral_empleados}): "
        f"{porcentaje.normalize():f}% × ${base:,.2f}"
        + (f" (salario tope ${regla.tope_salario:,.2f})" if regla.tope_salario is not None and salario > regla.tope_salario else "")
        + f" = ${calculado:,.2f}"
        + (f"; máximo ${tope:,.2f}" if calculado > tope else "")
        + f". Bono: ${monto:,.2f}."
    )
    return ResultadoBono(True, monto, texto)
