"""
Reportes de nómina sobre las nóminas cerradas (incluye los reversos, que restan) por fecha de pago.

Todos los montos salen de los resultados guardados al cerrar; nada se recalcula.
"""

from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Sum

from apps.core import fechas

from .models import LineaResultado, ResultadoNomina
from .servicios import ESTADOS_CERRADOS

CERO = Decimal("0")
CIEN = Decimal("100")


def q(valor) -> Decimal:
    """Las sumas de SQLite traen decimales de más: todo se redondea a centavos."""
    return Decimal(valor or 0).quantize(Decimal("0.01"))


def porcentaje(parte, total) -> Decimal | None:
    return (Decimal(parte) * CIEN / total).quantize(Decimal("0.01")) if total else None


def resultados(compania, desde, hasta):
    return ResultadoNomina.objects.filter(
        periodo__compania=compania, periodo__estado__in=ESTADOS_CERRADOS,
        periodo__fecha_pago__gte=desde, periodo__fecha_pago__lte=hasta,
    )


def lineas(compania, desde, hasta):
    return LineaResultado.objects.filter(
        resultado__periodo__compania=compania, resultado__periodo__estado__in=ESTADOS_CERRADOS,
        resultado__periodo__fecha_pago__gte=desde, resultado__periodo__fecha_pago__lte=hasta,
    )


# --- Resumen por concepto -------------------------------------------------------------


@dataclass
class Resumen:
    grupos: dict = field(default_factory=dict)  # grupo → [(codigo, nombre, monto, % del bruto)]
    totales: dict = field(default_factory=dict)
    empleados: int = 0
    nominas: int = 0

    @property
    def costo_total(self):
        return self.totales.get("ingreso", CERO) + self.totales.get("patronal", CERO)


def resumen(compania, desde, hasta) -> Resumen:
    datos = (
        lineas(compania, desde, hasta).values("grupo", "codigo").annotate(total=Sum("monto"))
        .order_by("grupo", "codigo")
    )
    nombres = dict(
        lineas(compania, desde, hasta).values_list("codigo", "nombre").order_by("codigo").distinct()
    )
    r = Resumen()
    for grupo in ("ingreso", "retencion", "deduccion", "patronal"):
        filas = [(d["codigo"], nombres.get(d["codigo"], d["codigo"]), q(d["total"])) for d in datos
                 if d["grupo"] == grupo and q(d["total"])]
        r.grupos[grupo] = filas
        r.totales[grupo] = sum((f[2] for f in filas), CERO)
    bruto = r.totales["ingreso"]
    r.grupos = {g: [(c, n, m, porcentaje(m, bruto)) for c, n, m in filas] for g, filas in r.grupos.items()}
    base = resultados(compania, desde, hasta)
    r.empleados = base.values("empleado").distinct().count()
    r.nominas = base.filter(periodo__estado="cerrada").exclude(periodo__tipo="reverso").values("periodo").distinct().count()
    return r


# --- Por empleado ----------------------------------------------------------------------

COLUMNAS_RETENCION = [
    ("retencion_pr", "Ret. PR"), ("ss_empleado", "Seguro Social"), ("medicare_empleado", "Medicare"),
    ("medicare_adicional", "Medicare adic."), ("sinot_empleado", "SINOT"), ("choferil_empleado", "Choferil"),
]


def por_empleado(compania, desde, hasta):
    """Acumulado por empleado en el rango (con el rango del año, es el acumulado del año)."""
    filas = OrderedDict()
    base = resultados(compania, desde, hasta).order_by("empleado_nombre")
    for r in base.values("empleado", "empleado_nombre", "numero_empleado", "ssn_ultimos4", "departamento"):
        filas.setdefault(r["empleado"], {**r, "horas": CERO, "bruto": CERO, "retenciones": {}, "otras_retenciones": CERO,
                                         "deducciones": CERO, "neto": CERO, "patronal": CERO})
    totales = base.values("empleado").annotate(
        horas=Sum("horas_trabajadas"), bruto=Sum("bruto"), deducciones=Sum("total_deducciones"), neto=Sum("neto"),
        patronal=Sum("total_patronal"),
    )
    for t in totales:
        fila = filas[t["empleado"]]
        for campo in ("horas", "bruto", "deducciones", "neto", "patronal"):
            fila[campo] = q(t[campo])
    codigos = {c for c, _ in COLUMNAS_RETENCION}
    for l in (lineas(compania, desde, hasta).filter(grupo="retencion")
              .values("resultado__empleado", "codigo").annotate(total=Sum("monto"))):
        fila = filas[l["resultado__empleado"]]
        if l["codigo"] in codigos:
            fila["retenciones"][l["codigo"]] = q(l["total"])
        else:
            fila["otras_retenciones"] += q(l["total"])
    salida = []
    for fila in filas.values():
        fila["columnas"] = [fila["retenciones"].get(c, CERO) for c, _ in COLUMNAS_RETENCION]
        fila["costo"] = fila["bruto"] + fila["patronal"]
        fila["pct_patronal"] = porcentaje(fila["patronal"], fila["bruto"])
        salida.append(fila)
    return salida


# --- Costo patronal ------------------------------------------------------------------


def costo_patronal(compania, desde, hasta, agrupar="empleado"):
    """
    Costo del patrono por empleado o por departamento: salario bruto + cada aportación, con el
    porcentaje de cada aportación sobre el bruto al lado del monto.
    """
    campo = "empleado" if agrupar == "empleado" else "departamento"
    conceptos = OrderedDict(
        lineas(compania, desde, hasta).filter(grupo="patronal").values_list("codigo", "nombre")
        .order_by("orden", "codigo").distinct()
    )
    grupos = defaultdict(lambda: {"nombre": "", "bruto": CERO, "patronal": defaultdict(lambda: CERO)})
    for r in resultados(compania, desde, hasta).values(campo).annotate(bruto=Sum("bruto")):
        grupos[r[campo]]["bruto"] = q(r["bruto"])
    for r in resultados(compania, desde, hasta).values(campo, "empleado_nombre").distinct():
        grupos[r[campo]]["nombre"] = (r["empleado_nombre"] if agrupar == "empleado"
                                      else r["departamento"] or "Sin departamento")
    for l in (lineas(compania, desde, hasta).filter(grupo="patronal")
              .values(f"resultado__{campo}", "codigo").annotate(total=Sum("monto"))):
        grupos[l[f"resultado__{campo}"]]["patronal"][l["codigo"]] += q(l["total"])
    filas = []
    for g in sorted(grupos.values(), key=lambda g: g["nombre"]):
        patronal = sum(g["patronal"].values(), CERO)
        filas.append({
            "nombre": g["nombre"], "bruto": g["bruto"],
            "conceptos": [(g["patronal"][c], porcentaje(g["patronal"][c], g["bruto"])) for c in conceptos],
            "patronal": patronal, "pct_patronal": porcentaje(patronal, g["bruto"]),
            "costo": g["bruto"] + patronal,
        })
    bruto = sum((f["bruto"] for f in filas), CERO)
    por_concepto = [sum((f["conceptos"][i][0] for f in filas), CERO) for i in range(len(conceptos))]
    patronal = sum(por_concepto, CERO)
    total = {
        "bruto": bruto, "conceptos": [(m, porcentaje(m, bruto)) for m in por_concepto],
        "patronal": patronal, "pct_patronal": porcentaje(patronal, bruto), "costo": bruto + patronal,
    }
    costo_total = total["costo"]
    for f in filas:
        f["pct_del_total"] = porcentaje(f["costo"], costo_total)
    return list(conceptos.values()), filas, total


# --- Impuestos y aportaciones a pagar --------------------------------------------------


@dataclass
class Obligacion:
    agencia: str
    concepto: str
    formulario: str
    periodo: str
    monto: Decimal
    vence: date | None
    nota: str = ""


OBLIGACIONES = [
    # (agencia, concepto, formulario, códigos, frecuencia)
    ("Hacienda", "Retención de contribución sobre ingresos", "Depósito SURI / 499 R-1", ["retencion_pr"], "hacienda"),
    ("IRS", "Seguro Social y Medicare (empleado y patrono)", "Depósito EFTPS / 941-PR",
     ["ss_empleado", "ss_patrono", "medicare_empleado", "medicare_patrono", "medicare_adicional", "retencion_federal"],
     "federal"),
    ("IRS", "Desempleo federal (FUTA)", "Depósito EFTPS / 940", ["futa"], "futa"),
    ("DTRH", "Desempleo estatal y aportación especial", "Planilla trimestral de desempleo e incapacidad",
     ["suta", "aportacion_especial"], "trimestral"),
    ("DTRH", "Incapacidad (SINOT) empleado y patrono", "Planilla trimestral de desempleo e incapacidad",
     ["sinot_empleado", "sinot_patrono"], "trimestral"),
    ("DTRH", "Seguro Choferil empleado y patrono", "Planilla trimestral de Seguro Choferil",
     ["choferil_empleado", "choferil_patrono"], "trimestral"),
    ("CFSE", "Seguro del Estado (provisión)", "Declaración de nómina / póliza", ["cfse"], "cfse"),
]


def impuestos(compania, desde, hasta) -> list[Obligacion]:
    """Lo que hay que depositar por las nóminas pagadas en el rango, agrupado por fecha de vencimiento."""
    por_fecha = (
        lineas(compania, desde, hasta).values("codigo", "resultado__periodo__fecha_pago").annotate(total=Sum("monto"))
    )
    montos = defaultdict(lambda: CERO)  # (codigo, fecha_pago) → monto
    for d in por_fecha:
        montos[(d["codigo"], d["resultado__periodo__fecha_pago"])] += q(d["total"])
    salida = []
    for agencia, concepto, formulario, codigos, frecuencia in OBLIGACIONES:
        agrupado = OrderedDict()
        for (codigo, fecha_pago), monto in sorted(montos.items(), key=lambda x: x[0][1]):
            if codigo not in codigos:
                continue
            clave, periodo, vence = _vencimiento(compania, frecuencia, fecha_pago)
            anterior = agrupado.get(clave)
            agrupado[clave] = (periodo, vence, (anterior[2] if anterior else CERO) + monto)
        for periodo, vence, monto in agrupado.values():
            if monto:
                salida.append(Obligacion(agencia, concepto, formulario, periodo, monto, vence, _nota(frecuencia)))
    salida.extend(_servicios_prestados(compania, desde, hasta))
    return salida


def _vencimiento(compania, frecuencia, fecha_pago):
    if frecuencia == "hacienda":
        frecuencia = "bisemanal" if compania.frecuencia_deposito == "bisemanal" else "mensual"
    elif frecuencia == "federal":
        frecuencia = "bisemanal" if compania.frecuencia_deposito_federal == "bisemanal" else "mensual"
    if frecuencia == "bisemanal":
        return fecha_pago, f"Pago del {fecha_pago:%m/%d/%Y}", fechas.vence_bisemanal(fecha_pago)
    if frecuencia == "mensual":
        return (fecha_pago.year, fecha_pago.month), f"{fecha_pago:%m/%Y}", fechas.vence_mensual(fecha_pago)
    trimestre = fechas.trimestre_de(fecha_pago)
    etiqueta = f"Trimestre {trimestre}/{fecha_pago.year}"
    if frecuencia == "cfse":
        return (fecha_pago.year, trimestre), etiqueta, None
    return (fecha_pago.year, trimestre), etiqueta, fechas.vence_trimestral(fecha_pago.year, trimestre)


def _nota(frecuencia):
    return {
        "federal": "Depositante mensual con menos de $2,500 en el trimestre puede pagar con la planilla 941. "
                   "Si acumula $100,000 o más en un día, se deposita el próximo día laborable.",
        "futa": "Si lo acumulado sin depositar es $500 o menos, pasa al próximo trimestre.",
        "cfse": "Se paga según la póliza de la CFSE (año julio–junio); es una provisión.",
    }.get(frecuencia, "")


def _servicios_prestados(compania, desde, hasta):
    from apps.servicios.models import PagoServicio

    pagos = (
        PagoServicio.objects.filter(compania=compania, fecha__gte=desde, fecha__lte=hasta, retencion__gt=0)
        .exclude(estado="anulado").values("fecha").annotate(total=Sum("retencion")).order_by("fecha")
    )
    agrupado = OrderedDict()
    for p in pagos:
        clave, periodo, vence = _vencimiento(compania, "hacienda", p["fecha"])
        anterior = agrupado.get(clave)
        agrupado[clave] = (periodo, vence, (anterior[2] if anterior else CERO) + q(p["total"]))
    return [
        Obligacion("Hacienda", "Retención de servicios prestados (10%)", "Depósito SURI / 480.6SP", periodo, monto,
                   vence, "Detalle y depósitos en Servicios.")
        for periodo, vence, monto in agrupado.values()
    ]
