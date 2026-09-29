"""Emisión, anulación y reemisión de cheques de nómina."""

from django.db import transaction
from django.utils import timezone

from .models import Cheque, FormatoCheque, PeriodoNomina


class ErrorCheque(Exception):
    pass


def formato_de(compania) -> FormatoCheque:
    return FormatoCheque.objects.get_or_create(compania=compania)[0]


def vigente(resultado):
    return next((c for c in resultado.cheques.all() if c.estado == Cheque.Estado.EMITIDO), None)


def por_cheque_sugerido(resultado) -> bool:
    """Por defecto se emite cheque a quien no cobra por depósito directo."""
    return resultado.neto > 0 and not resultado.empleado.deposito_directo


def _exigir_periodo(periodo):
    if periodo.estado != PeriodoNomina.Estado.CERRADA or periodo.tipo == PeriodoNomina.Tipo.REVERSO:
        raise ErrorCheque("Sólo se emiten cheques de una nómina aprobada y cerrada.")


def _numeros_libres(compania, primero, cantidad):
    numeros = list(range(primero, primero + cantidad))
    usados = sorted(Cheque.objects.filter(compania=compania, numero__in=numeros).values_list("numero", flat=True))
    if usados:
        raise ErrorCheque(f"Los números de cheque {', '.join(map(str, usados))} ya se usaron.")
    return numeros


@transaction.atomic
def emitir(periodo, resultados, primer_numero, usuario, fecha=None):
    """Asigna números consecutivos a partir de `primer_numero` (debe coincidir con el papel)."""
    _exigir_periodo(periodo)
    if primer_numero is None or primer_numero < 1:
        raise ErrorCheque("Indique el número del primer cheque.")
    resultados = sorted(resultados, key=lambda r: (r.empleado_nombre, r.pk))
    if not resultados:
        raise ErrorCheque("Seleccione al menos un empleado.")
    for r in resultados:
        if r.periodo_id != periodo.pk:
            raise ErrorCheque("El resultado no pertenece a este período.")
        if r.neto <= 0:
            raise ErrorCheque(f"{r.empleado_nombre}: el neto no es mayor que cero.")
        if r.cheques.filter(estado=Cheque.Estado.EMITIDO).exists():
            raise ErrorCheque(f"{r.empleado_nombre} ya tiene un cheque emitido en este período.")
    formato = FormatoCheque.objects.select_for_update().get(pk=formato_de(periodo.compania).pk)
    numeros = _numeros_libres(periodo.compania, primer_numero, len(resultados))
    cheques = [
        Cheque.objects.create(
            compania=periodo.compania, periodo=periodo, resultado=r, numero=n, fecha=fecha or periodo.fecha_pago,
            monto=r.neto, beneficiario=r.empleado_nombre, emitido_por=usuario,
        )
        for r, n in zip(resultados, numeros)
    ]
    # El papel sigue en orden: el próximo cheque es el siguiente al último que se usó.
    formato.siguiente_numero = numeros[-1] + 1
    formato.save(update_fields=["siguiente_numero"])
    return cheques


def anular(cheque, motivo, usuario):
    if cheque.estado != Cheque.Estado.EMITIDO:
        raise ErrorCheque("El cheque ya está anulado.")
    if not (motivo or "").strip():
        raise ErrorCheque("Indique el motivo de la anulación.")
    cheque.estado = Cheque.Estado.ANULADO
    cheque.motivo_anulacion = motivo.strip()[:300]
    cheque.anulado_en = timezone.now()
    cheque.anulado_por = usuario
    cheque.save()
    return cheque


@transaction.atomic
def reemitir(cheque, motivo, usuario, numero=None):
    """Anula el cheque (p. ej. se dañó al imprimir o se perdió) y emite otro con un número nuevo."""
    anular(cheque, motivo, usuario)
    if numero is None:
        numero = formato_de(cheque.compania).siguiente_numero
    hoy = timezone.localdate()
    fecha = max(cheque.fecha, hoy)
    return emitir(cheque.periodo, [cheque.resultado], numero, usuario, fecha=fecha)[0]


def anular_del_periodo(periodo, motivo, usuario):
    """Al reversar una nómina, sus cheques vigentes quedan anulados."""
    anulados = []
    for cheque in periodo.cheques.filter(estado=Cheque.Estado.EMITIDO):
        anulados.append(anular(cheque, f"Nómina reversada: {motivo}", usuario))
    return anulados
