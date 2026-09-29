"""
Datos de las planillas de gobierno, calculados de las nóminas cerradas (por fecha de pago; los reversos restan).

Nada se recalcula: se suman los resultados y las líneas guardadas al cerrar cada nómina. Las casillas y líneas
de cada formulario siguen las instrucciones publicadas y están POR VERIFICAR contra el formulario del año.
"""

import re
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Count, Sum

from apps.core import fechas
from apps.nomina.models import LineaResultado, PeriodoNomina, ResultadoNomina
from apps.nomina.servicios import ESTADOS_CERRADOS

CERO = Decimal("0")
CENTAVO = Decimal("0.01")


def q(valor) -> Decimal:
    return Decimal(valor or 0).quantize(CENTAVO)


def resultados(compania, desde, hasta):
    return ResultadoNomina.objects.filter(
        periodo__compania=compania, periodo__estado__in=ESTADOS_CERRADOS,
        periodo__fecha_pago__gte=desde, periodo__fecha_pago__lte=hasta,
    )


def lineas(compania, desde, hasta):
    return LineaResultado.objects.filter(resultado__in=resultados(compania, desde, hasta))


def _por_empleado_y_codigo(compania, desde, hasta, **filtro):
    """{(empleado_id, grupo, codigo): monto} y {(empleado_id, grupo, codigo): base}."""
    montos, bases = defaultdict(lambda: CERO), defaultdict(lambda: CERO)
    for d in (lineas(compania, desde, hasta).filter(**filtro)
              .values("resultado__empleado", "grupo", "codigo").annotate(total=Sum("monto"), base=Sum("base"))):
        clave = (d["resultado__empleado"], d["grupo"], d["codigo"])
        montos[clave] += q(d["total"])
        bases[clave] += q(d["base"])
    return montos, bases


def _empleados(compania, desde, hasta):
    """{empleado_id: Empleado} de los que cobraron en el rango, ordenados por nombre."""
    from apps.empleados.models import Empleado

    ids = resultados(compania, desde, hasta).values_list("empleado", flat=True).distinct()
    return OrderedDict(
        (e.pk, e) for e in Empleado.objects.filter(pk__in=ids).order_by("apellido_paterno", "apellido_materno", "nombre")
    )


def empleados_al_12(compania, anio, mes) -> int:
    """Empleados con pago en un período de nómina que incluye el día 12 del mes (941 línea 1 y DTRH)."""
    dia = date(anio, mes, 12)
    return (
        ResultadoNomina.objects.filter(
            periodo__compania=compania, periodo__estado=PeriodoNomina.Estado.CERRADA,
            periodo__fecha_inicio__lte=dia, periodo__fecha_fin__gte=dia, bruto__gt=0,
        )
        .exclude(periodo__tipo=PeriodoNomina.Tipo.REVERSO)
        .values("empleado").distinct().count()
    )


# --- 499R-2/W-2PR ------------------------------------------------------------------------

CATEGORIAS_INGRESO = {"comisiones": "comisiones", "propinas": "propinas", "reembolso": "reembolsos",
                      "mesada": "indemnizacion"}


@dataclass
class DatosW2:
    empleado: object
    sueldos: Decimal = CERO
    comisiones: Decimal = CERO
    concesiones: Decimal = CERO
    propinas: Decimal = CERO
    reembolsos: Decimal = CERO
    indemnizacion: Decimal = CERO  # mesada: exenta de contribución (POR VERIFICAR)
    otros_exentos: Decimal = CERO
    retenido_pr: Decimal = CERO
    sujeto_pr: Decimal = CERO  # lo que se usó para la retención (bruto tributable menos deducciones antes de PR)
    aportaciones: dict = field(default_factory=dict)  # deducciones antes de la retención de PR, por concepto
    salarios_ss: Decimal = CERO
    propinas_ss: Decimal = CERO
    retenido_ss: Decimal = CERO
    salarios_medicare: Decimal = CERO
    retenido_medicare: Decimal = CERO

    @property
    def total_tributable(self) -> Decimal:
        return self.sueldos + self.comisiones + self.concesiones + self.propinas

    @property
    def total_aportaciones(self) -> Decimal:
        return sum(self.aportaciones.values(), CERO)


def w2pr(compania, anio) -> list[DatosW2]:
    from apps.parametros.models import ConceptoDeduccion, ConceptoIngreso

    desde, hasta = date(anio, 1, 1), date(anio, 12, 31)
    tributa_pr = dict(ConceptoIngreso.objects.values_list("codigo", "tributable_pr"))
    antes_pr = {c.codigo: c.nombre for c in ConceptoDeduccion.objects.filter(antes_de_pr=True)}
    tributa_ss = dict(ConceptoIngreso.objects.values_list("codigo", "tributable_ss"))
    montos, bases = _por_empleado_y_codigo(compania, desde, hasta)
    trib = {d["empleado"]: d for d in resultados(compania, desde, hasta)
            .values("empleado").annotate(med=Sum("trib_medicare"), pr=Sum("trib_pr"))}
    salida = []
    for pk, emp in _empleados(compania, desde, hasta).items():
        d = DatosW2(emp)
        propinas_ss = CERO
        for (e, grupo, codigo), monto in montos.items():
            if e != pk or not monto:
                continue
            if grupo == "ingreso":
                categoria = CATEGORIAS_INGRESO.get(codigo)
                if categoria is None:
                    categoria = "sueldos" if tributa_pr.get(codigo, True) else "otros_exentos"
                setattr(d, categoria, getattr(d, categoria) + monto)
                if codigo == "propinas" and tributa_ss.get(codigo, True):
                    propinas_ss += monto
            elif grupo == "retencion":
                if codigo == "retencion_pr":
                    d.retenido_pr += monto
                elif codigo == "ss_empleado":
                    d.retenido_ss += monto
                elif codigo in ("medicare_empleado", "medicare_adicional"):
                    d.retenido_medicare += monto
            elif grupo == "deduccion" and codigo in antes_pr:
                d.aportaciones[antes_pr[codigo]] = d.aportaciones.get(antes_pr[codigo], CERO) + monto
        # Base del Seguro Social realmente usada en cada nómina (ya con el tope anual); las propinas van aparte.
        total_ss = bases[(pk, "retencion", "ss_empleado")]
        d.propinas_ss = min(propinas_ss, total_ss)
        d.salarios_ss = total_ss - d.propinas_ss
        d.salarios_medicare = q(trib.get(pk, {}).get("med"))
        d.sujeto_pr = q(trib.get(pk, {}).get("pr"))
        salida.append(d)
    return salida


# --- 499R-1B (trimestral de retención) ---------------------------------------------------


@dataclass
class Mes:
    anio: int
    mes: int
    pagado: Decimal = CERO
    sujeto: Decimal = CERO
    retenido: Decimal = CERO


def r1b(compania, anio, trimestre) -> list[Mes]:
    desde, _ = fechas.rango_trimestre(anio, trimestre)
    salida = []
    for mes in range(desde.month, desde.month + 3):
        inicio, fin = fechas.rango_mes(anio, mes)
        base = resultados(compania, inicio, fin)
        t = base.aggregate(sujeto=Sum("trib_pr"))
        retenido = lineas(compania, inicio, fin).filter(codigo="retencion_pr").aggregate(t=Sum("monto"))["t"]
        pagado = (lineas(compania, inicio, fin).filter(grupo="ingreso").exclude(codigo="reembolso")
                  .aggregate(t=Sum("monto"))["t"])
        salida.append(Mes(anio, mes, q(pagado), q(t["sujeto"]), q(retenido)))
    return salida


# --- 941 -----------------------------------------------------------------------------------

TASA_SS = Decimal("0.124")
TASA_MEDICARE = Decimal("0.029")
TASA_MEDICARE_ADICIONAL = Decimal("0.009")
CODIGOS_941 = ("ss_empleado", "ss_patrono", "medicare_empleado", "medicare_patrono", "medicare_adicional",
               "retencion_federal")


@dataclass
class Planilla941:
    anio: int
    trimestre: int
    empleados_12: int
    salarios: Decimal  # línea 2 (sólo si hay retención federal)
    retencion_federal: Decimal  # línea 3
    salarios_ss: Decimal  # 5a col. 1
    propinas_ss: Decimal  # 5b col. 1
    salarios_medicare: Decimal  # 5c col. 1
    sujeto_medicare_adicional: Decimal  # 5d col. 1
    retenido_real: Decimal  # lo que realmente se retuvo y aportó (para la línea 7)
    por_mes: list  # [(mes, obligación)]
    por_dia: list  # [(fecha de pago, obligación)] (Schedule B)

    @property
    def l5a(self):
        return q(self.salarios_ss * TASA_SS)

    @property
    def l5b(self):
        return q(self.propinas_ss * TASA_SS)

    @property
    def l5c(self):
        return q(self.salarios_medicare * TASA_MEDICARE)

    @property
    def l5d(self):
        return q(self.sujeto_medicare_adicional * TASA_MEDICARE_ADICIONAL)

    @property
    def l5e(self):
        return self.l5a + self.l5b + self.l5c + self.l5d

    @property
    def l6(self):
        return self.retencion_federal + self.l5e

    @property
    def l7(self):
        """Ajuste por fracciones de centavo: lo realmente calculado en cada nómina menos la línea 6."""
        return self.retenido_real - self.l6

    @property
    def l10(self):
        return self.l6 + self.l7

    @property
    def total_mensual(self):
        return sum((m for _, m in self.por_mes), CERO)


def f941(compania, anio, trimestre) -> Planilla941:
    desde, hasta = fechas.rango_trimestre(anio, trimestre)
    datos = w2pr_rango(compania, desde, hasta)
    montos = defaultdict(lambda: CERO)
    for d in lineas(compania, desde, hasta).filter(codigo__in=CODIGOS_941).values("codigo").annotate(t=Sum("monto")):
        montos[d["codigo"]] = q(d["t"])
    adicional_base = q(lineas(compania, desde, hasta).filter(codigo="medicare_adicional").aggregate(t=Sum("base"))["t"])
    por_fecha = OrderedDict()
    for d in (lineas(compania, desde, hasta).filter(codigo__in=CODIGOS_941)
              .values("resultado__periodo__fecha_pago").annotate(t=Sum("monto"))
              .order_by("resultado__periodo__fecha_pago")):
        fecha = d["resultado__periodo__fecha_pago"]
        por_fecha[fecha] = por_fecha.get(fecha, CERO) + q(d["t"])
    por_mes = [(m, sum((v for f, v in por_fecha.items() if f.month == m), CERO))
               for m in range(desde.month, desde.month + 3)]
    federal = montos["retencion_federal"]
    return Planilla941(
        anio=anio, trimestre=trimestre, empleados_12=empleados_al_12(compania, anio, desde.month + 2),
        salarios=sum((d.total_tributable for d in datos), CERO) if federal else CERO, retencion_federal=federal,
        salarios_ss=sum((d.salarios_ss for d in datos), CERO), propinas_ss=sum((d.propinas_ss for d in datos), CERO),
        salarios_medicare=sum((d.salarios_medicare for d in datos), CERO), sujeto_medicare_adicional=adicional_base,
        retenido_real=sum(montos.values(), CERO), por_mes=por_mes, por_dia=list(por_fecha.items()),
    )


def w2pr_rango(compania, desde, hasta) -> list[DatosW2]:
    """Mismos datos del W-2PR para un rango (trimestre)."""
    from apps.parametros.models import ConceptoIngreso

    tributa_ss = dict(ConceptoIngreso.objects.values_list("codigo", "tributable_ss"))
    salida = []
    base = resultados(compania, desde, hasta)
    tr = {d["empleado"]: d for d in base.values("empleado").annotate(ss=Sum("trib_ss"), med=Sum("trib_medicare"))}
    propinas = defaultdict(lambda: CERO)
    if tributa_ss.get("propinas", True):
        for d in (lineas(compania, desde, hasta).filter(codigo="propinas", grupo="ingreso")
                  .values("resultado__empleado").annotate(t=Sum("monto"))):
            propinas[d["resultado__empleado"]] = q(d["t"])
    # Base del SS realmente usada (con el tope anual aplicado en cada nómina).
    base_ss = {d["resultado__empleado"]: q(d["t"]) for d in lineas(compania, desde, hasta).filter(codigo="ss_empleado")
               .values("resultado__empleado").annotate(t=Sum("base"))}
    for pk, emp in _empleados(compania, desde, hasta).items():
        d = DatosW2(emp)
        total_ss = base_ss.get(pk, CERO)
        d.propinas_ss = min(propinas[pk], total_ss)
        d.salarios_ss = total_ss - d.propinas_ss
        d.salarios_medicare = q(tr.get(pk, {}).get("med"))
        salida.append(d)
    return salida


# --- 940 -----------------------------------------------------------------------------------


@dataclass
class Planilla940:
    anio: int
    pagos_totales: Decimal  # línea 3
    pagos_exentos: Decimal  # línea 4
    exceso_7000: Decimal  # línea 5
    tope: Decimal
    tasa: Decimal
    futa_calculado: Decimal  # suma de las líneas FUTA de cada nómina
    por_trimestre: list  # [(trimestre, obligación)] línea 16

    @property
    def l6(self):
        return self.pagos_exentos + self.exceso_7000

    @property
    def l7(self):
        return self.pagos_totales - self.l6

    @property
    def l8(self):
        return q(self.l7 * self.tasa / 100)


def f940(compania, anio) -> Planilla940:
    from apps.parametros.models import ParametrosAnuales

    p = ParametrosAnuales.objects.filter(anio=anio).first()
    tope = p.futa_tope if p else Decimal("7000")
    tasa = p.futa_tasa if p else Decimal("0.6")
    desde, hasta = date(anio, 1, 1), date(anio, 12, 31)
    base = resultados(compania, desde, hasta)
    pagos = q(lineas(compania, desde, hasta).filter(grupo="ingreso").aggregate(t=Sum("monto"))["t"])
    sujetos = {d["empleado"]: q(d["t"]) for d in base.values("empleado").annotate(t=Sum("trib_futa"))}
    total_sujeto = sum(sujetos.values(), CERO)
    exceso = sum((max(CERO, v - tope) for v in sujetos.values()), CERO)
    futa = lineas(compania, desde, hasta).filter(codigo="futa")
    por_trimestre = []
    for t in range(1, 5):
        a, b = fechas.rango_trimestre(anio, t)
        por_trimestre.append((t, q(futa.filter(resultado__periodo__fecha_pago__gte=a,
                                               resultado__periodo__fecha_pago__lte=b).aggregate(s=Sum("monto"))["s"])))
    return Planilla940(anio, pagos, pagos - total_sujeto, exceso, tope, tasa,
                       q(futa.aggregate(s=Sum("monto"))["s"]), por_trimestre)


# --- DTRH: desempleo e incapacidad (trimestral) ----------------------------------------


@dataclass
class FilaDTRH:
    empleado: object
    salarios: Decimal
    tributable_desempleo: Decimal
    tributable_sinot: Decimal
    suta: Decimal
    aportacion_especial: Decimal
    sinot_empleado: Decimal
    sinot_patrono: Decimal


def dtrh(compania, anio, trimestre) -> tuple[list[FilaDTRH], list]:
    desde, hasta = fechas.rango_trimestre(anio, trimestre)
    montos, bases = _por_empleado_y_codigo(compania, desde, hasta)
    salarios = {d["empleado"]: q(d["t"]) for d in resultados(compania, desde, hasta)
                .values("empleado").annotate(t=Sum("trib_desempleo"))}
    filas = []
    for pk, emp in _empleados(compania, desde, hasta).items():
        filas.append(FilaDTRH(
            emp, salarios.get(pk, CERO),
            bases[(pk, "patronal", "suta")], bases[(pk, "retencion", "sinot_empleado")],
            montos[(pk, "patronal", "suta")], montos[(pk, "patronal", "aportacion_especial")],
            montos[(pk, "retencion", "sinot_empleado")], montos[(pk, "patronal", "sinot_patrono")],
        ))
    meses = [(m, empleados_al_12(compania, anio, m)) for m in range(desde.month, desde.month + 3)]
    return filas, meses


# --- Seguro Choferil (trimestral) ---------------------------------------------------------

_SEMANAS = re.compile(r"(\d+) semana")


@dataclass
class FilaChoferil:
    empleado: object
    semanas: int
    empleado_monto: Decimal
    patrono_monto: Decimal


def choferil(compania, anio, trimestre) -> list[FilaChoferil]:
    desde, hasta = fechas.rango_trimestre(anio, trimestre)
    semanas = defaultdict(int)
    montos = defaultdict(lambda: CERO)
    for l in lineas(compania, desde, hasta).filter(codigo__in=("choferil_empleado", "choferil_patrono")).select_related("resultado"):
        pk = l.resultado.empleado_id
        montos[(pk, l.codigo)] += l.monto
        if l.codigo == "choferil_empleado":
            m = _SEMANAS.search(l.explicacion or "")
            if m:
                semanas[pk] += int(m.group(1)) * (1 if l.monto >= 0 else -1)
    empleados = _empleados(compania, desde, hasta)
    return [FilaChoferil(empleados[pk], semanas[pk], montos[(pk, "choferil_empleado")], montos[(pk, "choferil_patrono")])
            for pk in empleados if montos[(pk, "choferil_empleado")] or montos[(pk, "choferil_patrono")]]


# --- CFSE -----------------------------------------------------------------------------------


@dataclass
class FilaCFSE:
    clasificacion: str
    descripcion: str
    empleados: int
    nomina: Decimal
    tasa: Decimal | None
    prima: Decimal


def cfse(compania, desde, hasta) -> list[FilaCFSE]:
    """Nómina por clasificación de la póliza (la del empleado al pagarse)."""
    from apps.companias.models import ClasificacionCFSE

    descripciones = dict(ClasificacionCFSE.objects.filter(compania=compania).values_list("codigo", "descripcion"))
    base = resultados(compania, desde, hasta)
    filas = []
    for d in base.values("clasificacion_cfse").annotate(nomina=Sum("trib_cfse")).order_by("clasificacion_cfse"):
        codigo = d["clasificacion_cfse"]
        del_grupo = base.filter(clasificacion_cfse=codigo)
        lineas_cfse = LineaResultado.objects.filter(resultado__in=del_grupo, codigo="cfse")
        prima = q(lineas_cfse.aggregate(t=Sum("monto"))["t"])
        tasa = lineas_cfse.exclude(tasa=None).values_list("tasa", flat=True).first()
        filas.append(FilaCFSE(codigo or "Sin clasificación", descripciones.get(codigo, ""),
                              del_grupo.values("empleado").distinct().count(), q(d["nomina"]), tasa, prima))
    return filas


def anio_poliza_cfse(anio_inicio) -> tuple[date, date]:
    """Año de la póliza de la CFSE: 1 de julio al 30 de junio (POR VERIFICAR con la póliza)."""
    return date(anio_inicio, 7, 1), date(anio_inicio + 1, 6, 30)


# --- Servicios prestados (declaración informativa anual 480.6SP) -----------------------


@dataclass
class FilaServicios:
    proveedor: object
    pagado: Decimal
    retenido: Decimal
    pagos: int


def servicios_anual(compania, anio) -> list[FilaServicios]:
    from apps.servicios.models import PagoServicio, ProveedorServicios

    datos = (PagoServicio.objects.filter(compania=compania, anio=anio).exclude(estado="anulado")
             .values("proveedor").annotate(pagado=Sum("monto"), retenido=Sum("retencion"), n=Count("id")))
    proveedores = ProveedorServicios.objects.in_bulk([d["proveedor"] for d in datos])
    filas = [FilaServicios(proveedores[d["proveedor"]], q(d["pagado"]), q(d["retenido"]), d["n"]) for d in datos]
    return sorted(filas, key=lambda f: f.proveedor.nombre_mostrar)
