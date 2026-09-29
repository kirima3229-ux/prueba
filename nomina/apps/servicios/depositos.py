"""Control de depósitos de la retención por servicios prestados."""

import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.companias.models import Compania

from .models import DepositoRetencion, PagoServicio


class ErrorDeposito(Exception):
    pass


def pendientes(compania, desde=None, hasta=None):
    """Pagos activos con retención que todavía no están en un depósito."""
    pagos = PagoServicio.objects.filter(
        compania=compania, estado=PagoServicio.Estado.REGISTRADO, retencion__gt=0, deposito__isnull=True
    )
    if desde:
        pagos = pagos.filter(fecha__gte=desde)
    if hasta:
        pagos = pagos.filter(fecha__lte=hasta)
    return pagos.select_related("proveedor").order_by("fecha", "id")


def total_pendiente(compania, hasta=None) -> Decimal:
    return pendientes(compania, hasta=hasta).aggregate(t=Sum("retencion"))["t"] or Decimal("0")


def periodo_sugerido(compania) -> tuple[date, date]:
    """
    Siguiente período a depositar según la frecuencia de la compañía:
    empieza el día después del último depósito (o en el primer pago pendiente)
    y dura un mes calendario (mensual) o 14 días (bisemanal).
    """
    ultimo = (
        DepositoRetencion.objects.filter(compania=compania, estado=DepositoRetencion.Estado.REGISTRADO)
        .order_by("-hasta")
        .first()
    )
    primer_pendiente = pendientes(compania).first()
    if ultimo is not None:
        desde = ultimo.hasta + timedelta(days=1)
        if primer_pendiente is not None and primer_pendiente.fecha < desde:
            desde = primer_pendiente.fecha
    elif primer_pendiente is not None:
        desde = primer_pendiente.fecha
    else:
        desde = timezone.localdate().replace(day=1)

    if compania.frecuencia_deposito == Compania.FrecuenciaDeposito.BISEMANAL:
        return desde, desde + timedelta(days=13)
    if ultimo is None:
        desde = desde.replace(day=1)
    return desde, desde.replace(day=calendar.monthrange(desde.year, desde.month)[1])


def registrar(*, compania, desde, hasta, fecha_deposito, confirmacion, usuario, notas="") -> DepositoRetencion:
    if hasta < desde:
        raise ErrorDeposito("La fecha final del período no puede ser anterior a la inicial.")
    with transaction.atomic():
        # Bloquea los pagos: no pueden quedar en dos depósitos a la vez.
        incluidos = list(pendientes(compania, desde, hasta).select_for_update(of=("self",)))
        if not incluidos:
            raise ErrorDeposito("No hay retención pendiente de depositar en ese período.")
        deposito = DepositoRetencion.objects.create(
            compania=compania,
            desde=desde,
            hasta=hasta,
            fecha_deposito=fecha_deposito,
            confirmacion=confirmacion,
            notas=notas,
            monto=sum((p.retencion for p in incluidos), Decimal("0")),
            creado_por=usuario,
        )
        for pago in incluidos:
            pago.deposito = deposito
            pago.save(update_fields=["deposito"])
    return deposito


def anular(deposito: DepositoRetencion, motivo: str, usuario):
    if deposito.estado == DepositoRetencion.Estado.ANULADO:
        raise ErrorDeposito("El depósito ya estaba anulado.")
    with transaction.atomic():
        for pago in deposito.pagos.all():
            pago.deposito = None
            pago.save(update_fields=["deposito"])
        deposito.estado = DepositoRetencion.Estado.ANULADO
        deposito.motivo_anulacion = motivo
        deposito.anulado_por = usuario
        deposito.anulado_en = timezone.now()
        deposito.save(update_fields=["estado", "motivo_anulacion", "anulado_por", "anulado_en"])


def trimestre_de(fecha: date) -> int:
    return (fecha.month - 1) // 3 + 1


def rango_trimestre(anio: int, trimestre: int) -> tuple[date, date]:
    inicio = date(anio, 3 * (trimestre - 1) + 1, 1)
    fin_mes = 3 * trimestre
    return inicio, date(anio, fin_mes, calendar.monthrange(anio, fin_mes)[1])
