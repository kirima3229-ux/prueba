"""
Cálculo de la retención en el origen por servicios prestados
(Sección 1062.03 del Código de Rentas Internas de PR).

Reglas (la tasa y la exención vienen de la configuración por año):
- Los primeros $X (exención anual, hoy $500) pagados en el año natural a un
  mismo proveedor no están sujetos a retención; se retiene sobre el exceso.
- Relevo total o declaración jurada (Sección 1062.03(b)): no se retiene.
- Relevo parcial vigente: se retiene el porcentaje del certificado.
- Relevo vencido en la fecha del pago: se retiene la tasa general.
- Un pago marcado "exento" por el usuario (con motivo) no lleva retención.

Todo en Decimal, redondeo al centavo (mitad hacia arriba).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENTAVO = Decimal("0.01")
CIEN = Decimal("100")


class Tratamiento:
    GENERAL = "general"
    RELEVO_PARCIAL = "relevo_parcial"
    RELEVO_TOTAL = "relevo_total"
    DECLARACION_JURADA = "declaracion_jurada"
    EXENTO_PAGO = "exento_pago"

    ETIQUETAS = {
        GENERAL: "Tasa general",
        RELEVO_PARCIAL: "Relevo parcial",
        RELEVO_TOTAL: "Relevo total",
        DECLARACION_JURADA: "Exento — Sección 1062.03(b) (declaración jurada)",
        EXENTO_PAGO: "Pago exento (indicado por el usuario)",
    }
    CHOICES = list(ETIQUETAS.items())


def redondear(valor: Decimal) -> Decimal:
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class ResultadoRetencion:
    monto: Decimal
    acumulado_previo: Decimal
    exencion_aplicada: Decimal
    base_sujeta: Decimal
    tasa: Decimal
    tratamiento: str
    retencion: Decimal
    neto: Decimal
    explicacion: str

    @property
    def tratamiento_etiqueta(self) -> str:
        return Tratamiento.ETIQUETAS[self.tratamiento]


def calcular_retencion(
    *,
    monto: Decimal,
    acumulado_previo: Decimal,
    tasa_general: Decimal,
    exencion_anual: Decimal,
    tratamiento: str = Tratamiento.GENERAL,
    tasa_relevo_parcial: Decimal | None = None,
) -> ResultadoRetencion:
    monto = redondear(monto)
    acumulado_previo = redondear(acumulado_previo)
    if monto <= 0:
        raise ValueError("El monto del pago debe ser mayor que cero.")
    if acumulado_previo < 0:
        raise ValueError("El acumulado previo no puede ser negativo.")

    exencion_restante = max(Decimal("0"), redondear(exencion_anual) - acumulado_previo)
    exencion_aplicada = min(monto, exencion_restante)
    base = monto - exencion_aplicada

    if tratamiento in (Tratamiento.RELEVO_TOTAL, Tratamiento.DECLARACION_JURADA, Tratamiento.EXENTO_PAGO):
        tasa = Decimal("0")
    elif tratamiento == Tratamiento.RELEVO_PARCIAL:
        if tasa_relevo_parcial is None:
            raise ValueError("Falta el porcentaje del relevo parcial.")
        tasa = Decimal(tasa_relevo_parcial)
    else:
        tratamiento = Tratamiento.GENERAL
        tasa = Decimal(tasa_general)

    retencion = redondear(base * tasa / CIEN)
    neto = monto - retencion

    lineas = [
        f"Pago: ${monto:,.2f}. Pagado antes en el año a este proveedor: ${acumulado_previo:,.2f}.",
        f"Exención de los primeros ${redondear(exencion_anual):,.2f} del año: se aplican ${exencion_aplicada:,.2f} a este pago.",
        f"Cantidad sujeta: ${base:,.2f}.",
        f"{Tratamiento.ETIQUETAS[tratamiento]}: {tasa.normalize():f}% × ${base:,.2f} = ${retencion:,.2f} retenido.",
        f"Neto a pagar: ${neto:,.2f}.",
    ]
    return ResultadoRetencion(
        monto=monto,
        acumulado_previo=acumulado_previo,
        exencion_aplicada=exencion_aplicada,
        base_sujeta=base,
        tasa=tasa,
        tratamiento=tratamiento,
        retencion=retencion,
        neto=neto,
        explicacion="\n".join(lineas),
    )


def retencion_esperada(pagos, exencion_anual: Decimal) -> Decimal:
    """
    Recalcula desde cero la retención total de un proveedor en un año
    (pagos activos en el orden en que se registraron, con la tasa que se
    aplicó a cada uno). Sirve para conciliar si se anuló algún pago.
    `pagos` = iterable de (monto, tasa_aplicada).
    """
    acumulado = Decimal("0")
    total = Decimal("0")
    for monto, tasa in pagos:
        restante = max(Decimal("0"), exencion_anual - acumulado)
        base = monto - min(monto, restante)
        total += redondear(base * Decimal(tasa) / CIEN)
        acumulado += monto
    return total
