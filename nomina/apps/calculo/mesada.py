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


# --- Liquidación por terminación ------------------------------------------------------

HORAS_ANUALES_JORNADA_COMPLETA = Decimal("2080")  # 52 semanas × 40 horas


def salario_base_por_horas(tarifa_hora, horas_30_dias) -> Decimal:
    """Ley 4-2017: salario de los 30 días consecutivos con más horas regulares del último año."""
    return redondear(Decimal(tarifa_hora) * Decimal(horas_30_dias))


def tarifa_para_liquidacion(*, tipo_pago, tarifa, horas_regulares_periodo, salario_mensual, salario_minimo=None):
    """
    Tarifa por hora para pagar el balance de vacaciones:
    - por hora: su tarifa;
    - asalariado: salario del período ÷ horas del período, o si no hay horas,
      salario mensual × 12 ÷ 2,080;
    nunca por debajo del salario mínimo (empleados con propinas).
    Devuelve (tarifa, explicación).
    """
    if tipo_pago == "hora":
        valor, texto = Decimal(tarifa), f"su tarifa de ${Decimal(tarifa):,.2f} por hora"
    elif horas_regulares_periodo:
        valor = Decimal(tarifa) / Decimal(horas_regulares_periodo)
        texto = f"${Decimal(tarifa):,.2f} ÷ {horas_regulares_periodo} h del período = ${redondear(valor):,.2f} por hora"
    else:
        valor = Decimal(salario_mensual) * 12 / HORAS_ANUALES_JORNADA_COMPLETA
        texto = f"${Decimal(salario_mensual):,.2f} × 12 ÷ 2,080 h = ${redondear(valor):,.2f} por hora"
    if salario_minimo is not None and valor < Decimal(salario_minimo):
        valor = Decimal(salario_minimo)
        texto += f"; se paga al salario mínimo de ${valor:,.2f}"
    return valor, texto


@dataclass(frozen=True)
class Liquidacion:
    mesada: ResultadoMesada
    horas_vacaciones: Decimal
    pago_vacaciones: Decimal
    explicacion_vacaciones: str
    horas_enfermedad: Decimal
    pago_enfermedad: Decimal = CERO
    explicacion_enfermedad: str = ""

    @property
    def total(self) -> Decimal:
        return self.mesada.monto + self.pago_vacaciones + self.pago_enfermedad


def liquidar(*, mesada: ResultadoMesada, horas_vacaciones, horas_enfermedad, tarifa_hora, texto_tarifa,
             pagar_enfermedad=False) -> Liquidacion:
    """
    Vacaciones acumuladas siempre se liquidan. La licencia por enfermedad no se
    paga usualmente al terminar; solo se incluye si se pide (`pagar_enfermedad`).
    """
    horas_vacaciones = max(CERO, Decimal(horas_vacaciones))
    horas_enfermedad = max(CERO, Decimal(horas_enfermedad))
    pago = redondear(horas_vacaciones * Decimal(tarifa_hora))
    texto = f"{horas_vacaciones} h de vacaciones acumuladas × {texto_tarifa} = ${pago:,.2f}."
    pago_enf, texto_enf = CERO, "No se incluye (no es lo usual al terminar el empleo)."
    if pagar_enfermedad:
        pago_enf = redondear(horas_enfermedad * Decimal(tarifa_hora))
        texto_enf = f"{horas_enfermedad} h de enfermedad acumuladas × {texto_tarifa} = ${pago_enf:,.2f} (incluido a solicitud)."
    return Liquidacion(mesada, horas_vacaciones, pago, texto, horas_enfermedad, pago_enf, texto_enf)
