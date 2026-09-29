"""Depósito directo: arma el archivo NACHA de una nómina cerrada."""

import hashlib
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.core import fechas

from . import nacha
from .cheques import vigente
from .models import ArchivoBancario, ConfiguracionNACHA, PeriodoNomina


class ErrorDeposito(Exception):
    pass


def configuracion(compania) -> ConfiguracionNACHA | None:
    return ConfiguracionNACHA.objects.filter(compania=compania).first()


def depositos(periodo):
    """Resultados que se pagan por depósito: empleado con depósito directo, neto positivo y sin cheque."""
    return [
        r for r in periodo.resultados.select_related("empleado").prefetch_related("cheques").order_by("empleado_nombre")
        if r.empleado.deposito_directo and r.neto > 0 and not vigente(r)
    ]


def fecha_efectiva_sugerida(periodo):
    """El día de pago si es laborable; si no, el laborable anterior (para que el dinero llegue a tiempo)."""
    fecha = periodo.fecha_pago
    while not fechas.es_laborable(fecha):
        fecha -= timedelta(days=1)
    return fecha


def generar(periodo, fecha_efectiva, usuario) -> tuple[str, ArchivoBancario]:
    if periodo.estado != PeriodoNomina.Estado.CERRADA or periodo.tipo == PeriodoNomina.Tipo.REVERSO:
        raise ErrorDeposito("El archivo se genera de una nómina aprobada y cerrada.")
    config = configuracion(periodo.compania)
    if config is None:
        raise ErrorDeposito("Configure primero los datos del banco para depósito directo.")
    if not fechas.es_laborable(fecha_efectiva):
        raise ErrorDeposito("La fecha efectiva debe ser un día laborable.")
    resultados = depositos(periodo)
    faltan = [r.empleado_nombre for r in resultados if not (r.empleado.banco_ruta and r.empleado.banco_cuenta)]
    if faltan:
        raise ErrorDeposito("Sin ruta o cuenta bancaria: " + ", ".join(faltan) + ".")
    origen = nacha.Origen(
        ruta_banco=config.ruta_banco, nombre_banco=config.nombre_banco, origen_inmediato=config.origen_inmediato,
        identificacion_compania=config.identificacion_compania, nombre_compania=config.nombre_compania,
        descripcion=config.descripcion, balanceado=config.balanceado, ruta_compania=config.ruta_compania,
        cuenta_compania=config.cuenta_compania.revelar() if config.cuenta_compania else "",
        tipo_cuenta_compania=config.tipo_cuenta_compania,
    )
    pagos = [
        nacha.Pago(ruta=r.empleado.banco_ruta, cuenta=r.empleado.banco_cuenta.revelar(),
                   tipo_cuenta=r.empleado.banco_tipo_cuenta, monto=r.neto, identificacion=r.numero_empleado,
                   nombre=r.empleado_nombre)
        for r in resultados
    ]
    try:
        contenido = nacha.generar(origen, pagos, fecha_efectiva, timezone.localtime())
    except nacha.ErrorNACHA as e:
        raise ErrorDeposito(str(e)) from e
    archivo = ArchivoBancario.objects.create(
        periodo=periodo, fecha_efectiva=fecha_efectiva, depositos=len(pagos),
        total=sum((p.monto for p in pagos), Decimal("0")),
        huella=hashlib.sha256(contenido.encode("ascii")).hexdigest(), generado_por=usuario,
    )
    return contenido, archivo
