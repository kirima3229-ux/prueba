"""Registro de pagos por servicios prestados con su retención."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import transaction

from .calculo import ResultadoRetencion, Tratamiento, calcular_retencion
from .models import ConfigRetencionServicios, EstadoVerificacion, PagoServicio, ProveedorServicios, acumulado_del_anio


class ErrorPago(Exception):
    pass


@dataclass
class Calculo:
    resultado: ResultadoRetencion
    config: ConfigRetencionServicios
    avisos: list = field(default_factory=list)


def calcular(proveedor: ProveedorServicios, fecha: date, monto: Decimal, exento: bool = False,
             acumulado_extra: Decimal = Decimal("0")) -> Calculo:
    """
    Calcula la retención de un pago sin guardarlo. `acumulado_extra` suma
    pagos aún no guardados (por ejemplo, filas anteriores de una importación).
    """
    config = ConfigRetencionServicios.objects.filter(anio=fecha.year).first()
    if config is None:
        raise ErrorPago(
            f"No hay configuración de retención por servicios prestados para {fecha.year}. "
            "Un administrador debe crearla antes de registrar pagos de ese año."
        )
    avisos = []
    if config.estado != EstadoVerificacion.VERIFICADO:
        avisos.append(f"La tasa y la exención de {fecha.year} están POR VERIFICAR.")
    if exento:
        tratamiento, tasa_parcial = Tratamiento.EXENTO_PAGO, None
    else:
        tratamiento, tasa_parcial = proveedor.tratamiento_en(fecha)
        if proveedor.relevo != ProveedorServicios.Relevo.NINGUNO and not proveedor.relevo_vigente(fecha):
            avisos.append("El relevo del proveedor no está vigente en la fecha del pago: se aplica la tasa general.")
    resultado = calcular_retencion(
        monto=monto,
        acumulado_previo=acumulado_del_anio(proveedor, fecha.year) + acumulado_extra,
        tasa_general=config.tasa_general,
        exencion_anual=config.exencion_anual,
        tratamiento=tratamiento,
        tasa_relevo_parcial=tasa_parcial,
    )
    return Calculo(resultado=resultado, config=config, avisos=avisos)


def registrar(*, proveedor, fecha, monto, usuario, exento=False, motivo_exencion="", referencia="",
              descripcion="", metodo=PagoServicio.Metodo.CHEQUE, numero_cheque="",
              origen=PagoServicio.Origen.MANUAL, periodo_nomina=None) -> tuple[PagoServicio, list]:
    if exento and not motivo_exencion.strip():
        raise ErrorPago("Indique el motivo por el que el pago está exento de retención.")
    if not proveedor.activo:
        raise ErrorPago("El proveedor está inactivo.")
    with transaction.atomic():
        # Bloquea al proveedor: dos pagos simultáneos no pueden usar la misma exención.
        ProveedorServicios.objects.select_for_update().filter(pk=proveedor.pk).first()
        calculo = calcular(proveedor, fecha, monto, exento=exento)
        r = calculo.resultado
        pago = PagoServicio.objects.create(
            compania=proveedor.compania,
            proveedor=proveedor,
            fecha=fecha,
            referencia=referencia,
            descripcion=descripcion,
            metodo=metodo,
            numero_cheque=numero_cheque,
            origen=origen,
            periodo_nomina=periodo_nomina,
            monto=r.monto,
            acumulado_previo=r.acumulado_previo,
            exencion_aplicada=r.exencion_aplicada,
            base_sujeta=r.base_sujeta,
            tasa_aplicada=r.tasa,
            tratamiento=r.tratamiento,
            retencion=r.retencion,
            neto=r.neto,
            explicacion=r.explicacion,
            motivo_exencion=motivo_exencion.strip() if exento else "",
            config_verificada=calculo.config.estado == EstadoVerificacion.VERIFICADO,
            creado_por=usuario,
        )
    return pago, calculo.avisos
