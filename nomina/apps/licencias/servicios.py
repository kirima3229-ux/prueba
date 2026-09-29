"""Acumulación de vacaciones/enfermedad, movimientos de balance y bono de Navidad."""

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.calculo import cargar
from apps.calculo import licencias as calculo
from apps.empleados.models import Empleado

from .models import BonoNavidad, MovimientoLicencia, TipoLicencia, saldo

CERO = Decimal("0")


class ErrorLicencia(Exception):
    pass


def empleados_del_mes(compania, anio: int, mes: int):
    """Empleados que trabajaron alguna parte del mes."""
    inicio = date(anio, mes, 1)
    fin = date(anio, mes, calendar.monthrange(anio, mes)[1])
    return (
        Empleado.objects.filter(compania=compania, fecha_empleo__lte=fin)
        .exclude(fecha_terminacion__lt=inicio)
        .order_by("apellido_paterno", "nombre")
    ), inicio, fin


@dataclass
class FilaAcumulacion:
    empleado: Empleado
    horas_trabajadas: Decimal
    vacaciones: calculo.Acumulacion | None = None
    enfermedad: calculo.Acumulacion | None = None
    ya_acumulado: bool = False


@dataclass
class ResultadoAcumulacion:
    filas: list = field(default_factory=list)
    verificado: bool = False
    guardado: bool = False


def acumular_mes(compania, anio: int, mes: int, horas: dict, usuario=None, guardar=False) -> ResultadoAcumulacion:
    """`horas` = {empleado_id: horas trabajadas en el mes}. Sin horas, no se procesa al empleado."""
    p = cargar.parametros_anio(anio)
    reglas = cargar.reglas_licencia(p)
    empleados, inicio, fin = empleados_del_mes(compania, anio, mes)
    resultado = ResultadoAcumulacion(verificado=p.verificado)
    with transaction.atomic():
        for emp in empleados:
            if emp.pk not in horas or horas[emp.pk] is None:
                continue
            fila = FilaAcumulacion(emp, Decimal(horas[emp.pk]))
            fila.ya_acumulado = MovimientoLicencia.objects.filter(
                empleado=emp, clase=MovimientoLicencia.Clase.ACUMULACION, periodo=inicio
            ).exists()
            tamano = calculo.tamano_patrono(compania.numero_empleados, p.limite_patrono_pequeno_licencias)
            anios = calculo.anios_de_servicio(emp.fecha_empleo, fin)
            for tipo in (TipoLicencia.VACACIONES, TipoLicencia.ENFERMEDAD):
                regla = calculo.regla_aplicable(reglas, tipo, emp.regimen_efectivo, tamano, anios)
                tope = None
                if regla is not None:
                    tope = calculo.tope_horas(
                        tipo, dias_por_mes_actual=regla.dias_por_mes, horas_por_dia=p.horas_por_dia,
                        tope_vacaciones_meses=p.tope_vacaciones_meses, tope_enfermedad_dias=p.tope_enfermedad_dias,
                    )
                acumulacion = calculo.acumular_mes(
                    tipo=tipo, regimen=emp.regimen_efectivo, numero_empleados=compania.numero_empleados,
                    limite_pequeno=p.limite_patrono_pequeno_licencias, fecha_empleo=emp.fecha_empleo,
                    fin_de_mes=fin, horas_trabajadas=fila.horas_trabajadas, horas_por_dia=p.horas_por_dia,
                    reglas=reglas, balance_actual=saldo(emp, tipo), tope_horas=tope,
                )
                setattr(fila, tipo, acumulacion)
                if guardar and not fila.ya_acumulado:
                    MovimientoLicencia.objects.create(
                        empleado=emp, tipo=tipo, clase=MovimientoLicencia.Clase.ACUMULACION, fecha=fin,
                        periodo=inicio, horas=acumulacion.horas, horas_trabajadas=fila.horas_trabajadas,
                        descripcion=acumulacion.explicacion[:300], creado_por=usuario,
                    )
            resultado.filas.append(fila)
        resultado.guardado = guardar
    return resultado


def registrar_movimiento(*, empleado, tipo, clase, horas, fecha, descripcion, usuario) -> MovimientoLicencia:
    horas = Decimal(horas)
    if clase == MovimientoLicencia.Clase.ACUMULACION:
        raise ErrorLicencia("Las acumulaciones se registran con el proceso mensual.")
    if clase in (MovimientoLicencia.Clase.USO, MovimientoLicencia.Clase.LIQUIDACION):
        if horas <= 0:
            raise ErrorLicencia("Indique las horas usadas como un número positivo.")
        disponible = saldo(empleado, tipo)
        if horas > disponible:
            raise ErrorLicencia(f"No tiene balance suficiente: disponible {disponible} h.")
        horas = -horas
    if clase == MovimientoLicencia.Clase.SALDO_INICIAL and horas < 0:
        raise ErrorLicencia("El saldo inicial no puede ser negativo.")
    if horas == 0:
        raise ErrorLicencia("Las horas no pueden ser cero.")
    if clase == MovimientoLicencia.Clase.AJUSTE and not descripcion.strip():
        raise ErrorLicencia("Explique el motivo del ajuste.")
    return MovimientoLicencia.objects.create(
        empleado=empleado, tipo=tipo, clase=clase, horas=horas, fecha=fecha, descripcion=descripcion,
        creado_por=usuario,
    )


# --- Bono de Navidad ---------------------------------------------------------------


@dataclass
class FilaBono:
    empleado: Empleado
    horas: Decimal
    salario: Decimal
    resultado: calculo.ResultadoBono
    pagado: bool = False


def calcular_bonos(compania, anio: int, datos: dict, usuario=None, guardar=False):
    """`datos` = {empleado_id: (horas, salario)} del período del bono."""
    p = cargar.parametros_anio(anio)
    reglas = {r: cargar.regla_bono(p, r) for r in ("anterior", "ley4")}
    desde, hasta = calculo.periodo_bono(anio, reglas["ley4"].mes_inicio_periodo)
    empleados = (
        Empleado.objects.filter(compania=compania, fecha_empleo__lte=hasta)
        .exclude(fecha_terminacion__lt=desde)
        .order_by("apellido_paterno", "nombre")
    )
    filas = []
    with transaction.atomic():
        for emp in empleados:
            if emp.pk not in datos:
                continue
            horas, salario = (Decimal(v) for v in datos[emp.pk])
            regla = reglas[emp.regimen_efectivo]
            resultado = calculo.calcular_bono(
                regla=regla, numero_empleados=compania.numero_empleados, horas_trabajadas=horas, salario=salario
            )
            existente = BonoNavidad.objects.filter(empleado=emp, anio=anio).first()
            fila = FilaBono(emp, horas, salario, resultado, pagado=bool(existente and existente.estado == "pagado"))
            if guardar and not fila.pagado:
                BonoNavidad.objects.update_or_create(
                    empleado=emp, anio=anio,
                    defaults=dict(
                        compania=compania, periodo_desde=desde, periodo_hasta=hasta, regimen=emp.regimen_efectivo,
                        numero_empleados=compania.numero_empleados, horas=horas, salario=salario,
                        elegible=resultado.elegible, monto=resultado.monto, explicacion=resultado.explicacion,
                        parametros_verificados=p.verificado, calculado_por=usuario,
                    ),
                )
            filas.append(fila)
    return filas, (desde, hasta), p.verificado
