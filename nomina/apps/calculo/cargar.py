"""Convierte la configuración guardada en la base de datos en datos para el motor."""

from datetime import date

from apps.companias.models import EstadoVerificacion, TasaCFSE, TasasCompania
from apps.parametros.models import ConceptoDeduccion, ConceptoIngreso, ParametrosAnuales, SalarioMinimo

from . import motor


class ConfiguracionFaltante(motor.ErrorCalculo):
    pass


def salario_minimo_en(fecha: date):
    return SalarioMinimo.objects.filter(vigente_desde__lte=fecha).order_by("-vigente_desde").first()


def parametros(fecha: date) -> motor.Parametros:
    p = ParametrosAnuales.objects.prefetch_related("tramos", "reglas_horas_extra").filter(anio=fecha.year).first()
    if p is None:
        raise ConfiguracionFaltante(f"No hay parámetros de nómina para {fecha.year}. Un administrador debe crearlos.")
    tramos = tuple(motor.Tramo(t.desde, t.hasta, t.cuota_fija, t.tasa) for t in p.tramos.all())
    if not tramos:
        raise ConfiguracionFaltante(f"La tabla de retención de {fecha.year} no tiene tramos.")
    minimo = salario_minimo_en(fecha)
    return motor.Parametros(
        anio=p.anio,
        ss_tasa_empleado=p.ss_tasa_empleado,
        ss_tasa_patrono=p.ss_tasa_patrono,
        ss_tope=p.ss_tope,
        medicare_tasa_empleado=p.medicare_tasa_empleado,
        medicare_tasa_patrono=p.medicare_tasa_patrono,
        medicare_adicional_tasa=p.medicare_adicional_tasa,
        medicare_adicional_umbral=p.medicare_adicional_umbral,
        futa_tasa=p.futa_tasa,
        futa_tope=p.futa_tope,
        desempleo_tope=p.desempleo_tope,
        sinot_tope=p.sinot_tope,
        choferil_empleado_semanal=p.choferil_empleado_semanal,
        choferil_patrono_semanal=p.choferil_patrono_semanal,
        exencion_personal_individuo=p.exencion_personal_individuo,
        exencion_personal_casado=p.exencion_personal_casado,
        exencion_dependiente=p.exencion_dependiente,
        exencion_dependiente_custodia=p.exencion_dependiente_custodia,
        exencion_veterano=p.exencion_veterano,
        tramos=tramos,
        horas_extra={
            r.regimen: motor.ReglaHorasExtra(r.diario, r.semanal, r.septimo_dia, r.periodo_alimentos)
            for r in p.reglas_horas_extra.all()
        },
        salario_minimo=minimo.tarifa_hora if minimo else None,
        verificado=p.verificado and (minimo is None or minimo.verificado),
    )


def tasas_compania(compania, empleado, anio: int) -> motor.TasasCompania:
    t = TasasCompania.objects.filter(compania=compania, anio=anio).first()
    if t is None:
        raise ConfiguracionFaltante(f"La compañía {compania} no tiene tasas (SUTA, SINOT) para {anio}.")
    cfse = None
    cfse_verificada = True
    if empleado.clasificacion_cfse_id:
        tasa = TasaCFSE.objects.filter(clasificacion_id=empleado.clasificacion_cfse_id, anio=anio).first()
        if tasa is not None:
            cfse = tasa.tasa_por_100
            cfse_verificada = tasa.estado == EstadoVerificacion.VERIFICADO
    return motor.TasasCompania(
        suta=t.suta_tasa,
        aportacion_especial=t.aportacion_especial_tasa,
        sinot_empleado=t.sinot_empleado_tasa,
        sinot_patrono=t.sinot_patrono_tasa,
        cfse_por_100=cfse,
        verificadas=t.estado == EstadoVerificacion.VERIFICADO and cfse_verificada,
    )


def concepto_ingreso(c: ConceptoIngreso) -> motor.Concepto:
    return motor.Concepto(
        c.codigo, c.nombre, pr=c.tributable_pr, ss=c.tributable_ss, medicare=c.tributable_medicare,
        futa=c.tributable_futa, desempleo=c.tributable_desempleo, sinot=c.tributable_sinot, cfse=c.tributable_cfse,
    )


def conceptos_ingreso() -> dict:
    return {c.codigo: concepto_ingreso(c) for c in ConceptoIngreso.objects.filter(activo=True)}


def tipo_deduccion(c: ConceptoDeduccion) -> motor.TipoDeduccion:
    return motor.TipoDeduccion(
        c.codigo, c.nombre, antes_de_pr=c.antes_de_pr, antes_de_federal=c.antes_de_federal,
        antes_de_fica=c.antes_de_fica,
    )


def empleado(e) -> motor.Empleado:
    return motor.Empleado(
        regimen=e.regimen_efectivo,
        tipo_pago=e.tipo_pago,
        tarifa=e.tarifa,
        horas_regulares_periodo=e.horas_regulares_periodo,
        aplica_choferil=e.aplica_choferil,
        recibe_propinas=e.recibe_propinas,
        r4_estado_civil=e.r4_estado_civil,
        r4_exencion_personal=e.r4_exencion_personal,
        r4_dependientes=e.r4_dependientes,
        r4_dependientes_custodia_compartida=e.r4_dependientes_custodia_compartida,
        r4_veterano=e.r4_veterano,
        r4_concesion_deducciones=e.r4_concesion_deducciones,
        r4_retencion_adicional=e.r4_retencion_adicional,
        w4_aplica=e.w4_aplica,
    )
