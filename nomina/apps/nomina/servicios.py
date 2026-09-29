"""Servicios del flujo de nómina: crear período, calcular, cerrar, reversar y acumulados del año."""

import calendar
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.calculo import cargar, motor
from apps.companias.models import TasasCompania
from apps.empleados.models import Empleado
from apps.licencias.models import MovimientoLicencia, saldo

from .models import (
    DeduccionRecurrente,
    EntradaDeduccion,
    EntradaNomina,
    LineaResultado,
    PeriodoNomina,
    ResultadoNomina,
)

CERO = Decimal("0")
ESTADOS_CERRADOS = (PeriodoNomina.Estado.CERRADA, PeriodoNomina.Estado.REVERSADA)


class ErrorNomina(Exception):
    pass


# --- Períodos -----------------------------------------------------------------------


def sugerir_periodo(compania) -> tuple[date, date, date]:
    """Siguiente período según la frecuencia de pago de la compañía: (desde, hasta, fecha de pago)."""
    ultimo = (
        PeriodoNomina.objects.filter(compania=compania)
        .exclude(tipo=PeriodoNomina.Tipo.REVERSO)
        .exclude(tipo=PeriodoNomina.Tipo.ESPECIAL)
        .order_by("-fecha_fin")
        .first()
    )
    frecuencia = compania.frecuencia_pago
    if ultimo is not None:
        inicio = ultimo.fecha_fin + timedelta(days=1)
    else:
        hoy = timezone.localdate()
        inicio = hoy - timedelta(days=hoy.weekday()) if frecuencia in ("semanal", "bisemanal") else hoy.replace(day=1)
    if frecuencia == "semanal":
        fin = inicio + timedelta(days=6)
    elif frecuencia == "bisemanal":
        fin = inicio + timedelta(days=13)
    elif frecuencia == "quincenal":
        ultimo_dia = calendar.monthrange(inicio.year, inicio.month)[1]
        fin = inicio.replace(day=15) if inicio.day <= 15 else inicio.replace(day=ultimo_dia)
    else:
        fin = inicio.replace(day=calendar.monthrange(inicio.year, inicio.month)[1])
    return inicio, fin, fin


def empleados_del_periodo(compania, inicio, fin):
    return (
        Empleado.objects.filter(compania=compania, fecha_empleo__lte=fin)
        .filter(Q(activo=True) | Q(fecha_terminacion__gte=inicio))
        .order_by("apellido_paterno", "nombre")
    )


def crear_periodo(*, compania, inicio, fin, fecha_pago, usuario, tipo=PeriodoNomina.Tipo.REGULAR, descripcion=""):
    if fin < inicio:
        raise ErrorNomina("La fecha final no puede ser anterior a la inicial.")
    with transaction.atomic():
        periodo = PeriodoNomina.objects.create(
            compania=compania, fecha_inicio=inicio, fecha_fin=fin, fecha_pago=fecha_pago, tipo=tipo,
            descripcion=descripcion, creado_por=usuario,
        )
        for emp in empleados_del_periodo(compania, inicio, fin):
            entrada = EntradaNomina.objects.create(periodo=periodo, empleado=emp)
            if tipo == PeriodoNomina.Tipo.REGULAR:
                for ded in emp.deducciones_recurrentes.select_related("concepto"):
                    if ded.vigente_en(fecha_pago):
                        EntradaDeduccion.objects.create(
                            entrada=entrada, concepto=ded.concepto, monto=ded.monto, recurrente=ded,
                            descripcion=ded.notas,
                        )
    return periodo


def marcar_modificado(periodo):
    periodo.exigir_editable()
    if not periodo.requiere_recalculo:
        periodo.requiere_recalculo = True
        periodo.save(update_fields=["requiere_recalculo"])


# --- Acumulados del año --------------------------------------------------------------


def _resultados_cerrados(empleado, anio, excluir_periodo=None, hasta_fecha=None):
    qs = ResultadoNomina.objects.filter(
        empleado=empleado, periodo__estado__in=ESTADOS_CERRADOS, periodo__fecha_pago__year=anio
    )
    if excluir_periodo is not None:
        qs = qs.exclude(periodo=excluir_periodo)
    if hasta_fecha is not None:
        qs = qs.filter(periodo__fecha_pago__lte=hasta_fecha)
    return qs


def acumulados(empleado, anio, excluir_periodo=None) -> motor.Acumulados:
    """Salarios tributables del año en nóminas cerradas (los reversos restan)."""
    t = _resultados_cerrados(empleado, anio, excluir_periodo).aggregate(
        ss=Sum("trib_ss"), medicare=Sum("trib_medicare"), futa=Sum("trib_futa"),
        desempleo=Sum("trib_desempleo"), sinot=Sum("trib_sinot"),
    )
    return motor.Acumulados(**{k: v or CERO for k, v in t.items()})


def acumulados_por_concepto(resultado) -> dict:
    """YTD por (grupo, código) hasta la fecha de pago del resultado, incluyéndolo."""
    periodo = resultado.periodo
    previos = _resultados_cerrados(resultado.empleado, periodo.fecha_pago.year, excluir_periodo=periodo,
                                   hasta_fecha=periodo.fecha_pago)
    filas = (
        LineaResultado.objects.filter(resultado__in=previos)
        .values("grupo", "codigo").annotate(total=Sum("monto"))
    )
    ytd = {(f["grupo"], f["codigo"]): f["total"] for f in filas}
    for linea in resultado.lineas.all():
        clave = (linea.grupo, linea.codigo)
        ytd[clave] = ytd.get(clave, CERO) + linea.monto
    return ytd


# --- Cálculo -------------------------------------------------------------------------


def es_especial(periodo) -> bool:
    return periodo.tipo == PeriodoNomina.Tipo.ESPECIAL


def horas_trabajadas(entrada) -> Decimal:
    """
    Horas trabajadas del período (para licencias y bono). Al asalariado sin horas entradas se le cuentan
    sus horas regulares por período menos las de licencia.
    """
    horas = entrada.horas_trabajadas
    emp = entrada.empleado
    if (emp.tipo_pago != "hora" and not entrada.horas_regulares and emp.horas_regulares_periodo
            and not es_especial(entrada.periodo)):
        regulares = max(CERO, Decimal(emp.horas_regulares_periodo) - entrada.horas_vacaciones - entrada.horas_enfermedad)
        horas += regulares
    return horas


def _motor_para_entrada(entrada, parametros, conceptos, anio):
    emp = entrada.empleado
    especial = es_especial(entrada.periodo)
    tasas = cargar.tasas_compania(entrada.periodo.compania, emp, anio)
    otros = [
        motor.Monto(cargar.concepto_ingreso(i.concepto), i.monto, i.descripcion) for i in entrada.ingresos.all()
    ]
    deducciones = [
        motor.Monto(cargar.tipo_deduccion(d.concepto), d.monto, d.descripcion) for d in entrada.deducciones.all()
    ]
    return motor.calcular(
        empleado=cargar.empleado(emp),
        parametros=parametros,
        tasas=tasas,
        frecuencia=entrada.periodo.compania.frecuencia_pago,
        horas=motor.Horas(
            regulares=entrada.horas_regulares,
            extra_diarias=entrada.horas_extra_diarias,
            extra_semanales=entrada.horas_extra_semanales,
            septimo_dia=entrada.horas_septimo_dia,
            periodo_alimentos=entrada.horas_periodo_alimentos,
            vacaciones=entrada.horas_vacaciones,
            enfermedad=entrada.horas_enfermedad,
        ),
        otros_ingresos=otros,
        deducciones=deducciones,
        acumulados=acumulados(emp, anio, excluir_periodo=entrada.periodo),
        semanas_choferil=entrada.semanas_choferil if entrada.semanas_choferil is not None else (0 if especial else None),
        conceptos=conceptos,
        pagar_salario=not especial,
    ), tasas


def calcular_periodo(periodo, usuario):
    """Calcula (o recalcula) la pre-nómina. Devuelve la lista de errores por empleado."""
    periodo.exigir_editable()
    anio = periodo.fecha_pago.year
    parametros = cargar.parametros(periodo.fecha_pago)
    if not TasasCompania.objects.filter(compania=periodo.compania, anio=anio).exists():
        raise cargar.ConfiguracionFaltante(f"La compañía {periodo.compania} no tiene tasas (SUTA, SINOT) para {anio}.")
    conceptos = cargar.conceptos_ingreso()
    errores = []
    with transaction.atomic():
        periodo.resultados.all().delete()
        entradas = periodo.entradas.filter(incluir=True).select_related("empleado", "empleado__departamento")
        tasas_usadas = None
        for entrada in entradas.prefetch_related("ingresos__concepto", "deducciones__concepto"):
            emp = entrada.empleado
            try:
                r, tasas = _motor_para_entrada(entrada, parametros, conceptos, anio)
            except motor.ErrorCalculo as e:
                errores.append(f"{emp.nombre_completo}: {e}")
                continue
            tasas_usadas = tasas_usadas or tasas
            alertas = list(r.alertas)
            for tipo, horas in (("vacaciones", entrada.horas_vacaciones), ("enfermedad", entrada.horas_enfermedad)):
                if horas and horas > saldo(emp, tipo):
                    alertas.append(f"Balance de {tipo} insuficiente: usa {horas} h y tiene {saldo(emp, tipo)} h.")
            resultado = ResultadoNomina.objects.create(
                periodo=periodo, empleado=emp, empleado_nombre=emp.nombre_completo,
                numero_empleado=emp.numero_empleado, ssn_ultimos4=emp.ssn_ultimos4,
                departamento=str(emp.departamento or ""), regimen=emp.regimen_efectivo, tarifa=emp.tarifa,
                tipo_pago=emp.tipo_pago, horas_trabajadas=horas_trabajadas(entrada),
                bruto=r.bruto, total_retenciones=r.total_retenciones, total_deducciones=r.total_deducciones,
                neto=r.neto, total_patronal=r.total_patronal,
                trib_pr=r.tributables["pr"], trib_ss=r.tributables["ss"], trib_medicare=r.tributables["medicare"],
                trib_futa=r.tributables["futa"], trib_desempleo=r.tributables["desempleo"],
                trib_sinot=r.tributables["sinot"], trib_cfse=r.tributables["cfse"], alertas=alertas,
            )
            orden = 0
            for grupo, lineas in (
                (LineaResultado.Grupo.INGRESO, r.ingresos), (LineaResultado.Grupo.RETENCION, r.retenciones),
                (LineaResultado.Grupo.DEDUCCION, r.deducciones), (LineaResultado.Grupo.PATRONAL, r.patronales),
            ):
                for l in lineas:
                    orden += 1
                    LineaResultado.objects.create(
                        resultado=resultado, grupo=grupo, codigo=l.codigo, nombre=l.nombre, monto=l.monto,
                        base=l.base, tasa=l.tasa, explicacion=l.explicacion, orden=orden,
                    )
        periodo.errores = errores
        periodo.estado = PeriodoNomina.Estado.CALCULADA
        periodo.requiere_recalculo = False
        periodo.calculado_en = timezone.now()
        periodo.calculado_por = usuario
        periodo.parametros_usados = _foto_parametros(parametros, tasas_usadas)
        periodo.save()
    return errores


def _foto_parametros(parametros, tasas):
    """Copia de los parámetros con que se calculó (queda con la nómina cerrada)."""
    datos = {k: str(v) for k, v in asdict(parametros).items() if k not in ("tramos", "horas_extra")}
    datos["tramos"] = [
        {"desde": str(t.desde), "hasta": str(t.hasta) if t.hasta is not None else None,
         "cuota_fija": str(t.cuota_fija), "tasa": str(t.tasa)}
        for t in parametros.tramos
    ]
    datos["horas_extra"] = {k: {c: str(v) for c, v in asdict(r).items()} for k, r in parametros.horas_extra.items()}
    if tasas is not None:
        datos["tasas_compania"] = {k: str(v) for k, v in asdict(tasas).items() if k != "cfse_por_100"}
    return datos


# --- Cierre y reverso ----------------------------------------------------------------


def cerrar_periodo(periodo, usuario):
    if periodo.estado != PeriodoNomina.Estado.CALCULADA:
        raise ErrorNomina("Primero calcule la pre-nómina.")
    if periodo.requiere_recalculo:
        raise ErrorNomina("Hubo cambios después del último cálculo: calcule de nuevo antes de aprobar.")
    if periodo.errores:
        raise ErrorNomina("Hay empleados con errores de cálculo: corríjalos antes de aprobar.")
    if not periodo.resultados.exists():
        raise ErrorNomina("La nómina no tiene resultados.")
    with transaction.atomic():
        for entrada in periodo.entradas.filter(incluir=True).select_related("empleado"):
            for tipo, horas in (("vacaciones", entrada.horas_vacaciones), ("enfermedad", entrada.horas_enfermedad)):
                if horas:
                    MovimientoLicencia.objects.create(
                        empleado=entrada.empleado, tipo=tipo, clase=MovimientoLicencia.Clase.USO,
                        fecha=periodo.fecha_pago, horas=-horas, creado_por=usuario,
                        descripcion=f"Pagado en {periodo}"[:300], periodo_nomina=periodo,
                    )
        periodo.estado = PeriodoNomina.Estado.CERRADA
        periodo.cerrado_en = timezone.now()
        periodo.cerrado_por = usuario
        periodo.save(update_fields=["estado", "cerrado_en", "cerrado_por"])


def reversar_periodo(periodo, motivo, usuario):
    """Crea un período de reverso con todos los montos en negativo y marca el original como reversado."""
    if periodo.estado != PeriodoNomina.Estado.CERRADA or periodo.tipo == PeriodoNomina.Tipo.REVERSO:
        raise ErrorNomina("Solo se reversa una nómina aprobada y cerrada.")
    if not motivo.strip():
        raise ErrorNomina("Indique el motivo del reverso.")
    with transaction.atomic():
        reverso = PeriodoNomina.objects.create(
            compania=periodo.compania, tipo=PeriodoNomina.Tipo.REVERSO, fecha_inicio=periodo.fecha_inicio,
            fecha_fin=periodo.fecha_fin, fecha_pago=periodo.fecha_pago, reverso_de=periodo,
            descripcion=f"Reverso de {periodo}"[:200], motivo_reverso=motivo, estado=PeriodoNomina.Estado.BORRADOR,
            requiere_recalculo=False, parametros_usados=periodo.parametros_usados, creado_por=usuario,
        )
        campos = ["bruto", "total_retenciones", "total_deducciones", "neto", "total_patronal", "horas_trabajadas",
                  "trib_pr", "trib_ss", "trib_medicare", "trib_futa", "trib_desempleo", "trib_sinot", "trib_cfse"]
        for r in periodo.resultados.prefetch_related("lineas"):
            nuevo = ResultadoNomina.objects.create(
                periodo=reverso, empleado=r.empleado, empleado_nombre=r.empleado_nombre,
                numero_empleado=r.numero_empleado, ssn_ultimos4=r.ssn_ultimos4, departamento=r.departamento,
                regimen=r.regimen, tarifa=r.tarifa, tipo_pago=r.tipo_pago,
                alertas=[f"Reverso: {motivo}"], **{c: -getattr(r, c) for c in campos},
            )
            for l in r.lineas.all():
                LineaResultado.objects.create(
                    resultado=nuevo, grupo=l.grupo, codigo=l.codigo, nombre=l.nombre, monto=-l.monto,
                    base=-l.base if l.base is not None else None, tasa=l.tasa,
                    explicacion=f"Reverso de: {l.explicacion}", orden=l.orden,
                )
        # Devuelve las horas de licencia que se habían descontado.
        for mov in periodo.movimientos_licencia.filter(clase=MovimientoLicencia.Clase.USO):
            MovimientoLicencia.objects.create(
                empleado=mov.empleado, tipo=mov.tipo, clase=MovimientoLicencia.Clase.AJUSTE, fecha=periodo.fecha_pago,
                horas=-mov.horas, creado_por=usuario, descripcion=f"Reverso de nómina: {motivo}"[:300],
                periodo_nomina=reverso,
            )
        from .cheques import anular_del_periodo

        anular_del_periodo(periodo, motivo, usuario)
        reverso.estado = PeriodoNomina.Estado.CERRADA
        reverso.cerrado_en = timezone.now()
        reverso.cerrado_por = usuario
        reverso.save(update_fields=["estado", "cerrado_en", "cerrado_por"])
        periodo.estado = PeriodoNomina.Estado.REVERSADA
        periodo.motivo_reverso = motivo
        periodo.save(update_fields=["estado", "motivo_reverso"])
    return reverso


# --- Datos para licencias y bono ------------------------------------------------------

# Ingresos que no son salario para el bono de Navidad (POR VERIFICAR).
NO_SALARIO_BONO = ("reembolso", "propinas", "bono_navidad", "mesada", "vacaciones_liquidadas", "enfermedad_liquidada")


def _cerrados_por_fin_de_periodo(compania, desde, hasta):
    """Por la fecha final del período de nómina; los reversos restan."""
    return ResultadoNomina.objects.filter(
        periodo__compania=compania, periodo__estado__in=ESTADOS_CERRADOS,
        periodo__fecha_fin__gte=desde, periodo__fecha_fin__lte=hasta,
    )


def horas_del_mes(compania, anio: int, mes: int) -> dict:
    """{empleado_id: horas trabajadas} de las nóminas cerradas cuyo período termina en el mes."""
    desde = date(anio, mes, 1)
    hasta = date(anio, mes, calendar.monthrange(anio, mes)[1])
    return {
        d["empleado"]: Decimal(d["horas"]).quantize(Decimal("0.01"))
        for d in _cerrados_por_fin_de_periodo(compania, desde, hasta).values("empleado").annotate(horas=Sum("horas_trabajadas"))
    }


def datos_bono(compania, desde, hasta) -> dict:
    """{empleado_id: (horas, salario)} del período del bono según las nóminas cerradas."""
    base = _cerrados_por_fin_de_periodo(compania, desde, hasta)
    horas = {d["empleado"]: d["h"] for d in base.values("empleado").annotate(h=Sum("horas_trabajadas"))}
    salarios = {
        d["resultado__empleado"]: d["total"]
        for d in LineaResultado.objects.filter(resultado__in=base, grupo=LineaResultado.Grupo.INGRESO)
        .exclude(codigo__in=NO_SALARIO_BONO).values("resultado__empleado").annotate(total=Sum("monto"))
    }
    centavo = Decimal("0.01")
    return {
        emp: (Decimal(horas.get(emp) or 0).quantize(centavo), Decimal(salarios.get(emp) or 0).quantize(centavo))
        for emp in set(horas) | set(salarios)
    }
