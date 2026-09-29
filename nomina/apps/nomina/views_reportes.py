"""Pantalla de reportes de nómina (pantalla, Excel y PDF)."""

import calendar
from dataclasses import dataclass, field
from datetime import date

from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.auditoria.servicios import Accion, registrar
from apps.core import fechas, hojas
from apps.core.pdf import tabla_pdf
from apps.core.permisos import requiere_compania

from . import reportes

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]
REPORTES = [
    ("resumen", "Resumen por concepto"),
    ("empleados", "Acumulado por empleado"),
    ("costo", "Costo patronal"),
    ("impuestos", "Impuestos a pagar"),
]


@dataclass
class Tabla:
    columnas: list  # [(título, tipo)] tipo: texto | dinero | pct | horas | fecha
    filas: list
    totales: list | None = None
    notas: list = field(default_factory=list)


def _entero(texto, defecto, minimo, maximo):
    try:
        valor = int(texto)
    except (TypeError, ValueError):
        return defecto
    return valor if minimo <= valor <= maximo else defecto


def _fecha(texto):
    try:
        return date.fromisoformat(texto)
    except (TypeError, ValueError):
        return None


def rango_solicitado(get):
    hoy = timezone.localdate()
    rango = get.get("rango") if get.get("rango") in ("mes", "trimestre", "anio", "rango") else "mes"
    anio = _entero(get.get("anio"), hoy.year, 2000, 2100)
    mes = _entero(get.get("mes"), hoy.month, 1, 12)
    trimestre = _entero(get.get("trimestre"), fechas.trimestre_de(hoy), 1, 4)
    if rango == "mes":
        desde, hasta = date(anio, mes, 1), date(anio, mes, calendar.monthrange(anio, mes)[1])
        etiqueta = f"{MESES[mes - 1]} {anio}"
    elif rango == "trimestre":
        desde, hasta = fechas.rango_trimestre(anio, trimestre)
        etiqueta = f"trimestre {trimestre} de {anio}"
    elif rango == "anio":
        desde, hasta = date(anio, 1, 1), date(anio, 12, 31)
        etiqueta = f"año {anio}"
    else:
        desde = _fecha(get.get("desde")) or date(anio, 1, 1)
        hasta = _fecha(get.get("hasta")) or hoy
        if hasta < desde:
            desde, hasta = hasta, desde
        etiqueta = f"{desde:%m/%d/%Y} – {hasta:%m/%d/%Y}"
    return {"rango": rango, "anio": anio, "mes": mes, "trimestre": trimestre, "desde": desde, "hasta": hasta,
            "etiqueta": etiqueta}


def _tabla_resumen(compania, desde, hasta):
    r = reportes.resumen(compania, desde, hasta)
    nombres_grupo = {"ingreso": "Ingresos", "retencion": "Retenciones", "deduccion": "Deducciones",
                     "patronal": "Aportaciones patronales"}
    filas = []
    for grupo, titulo in nombres_grupo.items():
        for _, nombre, monto, pct in r.grupos[grupo]:
            filas.append([titulo, nombre, monto, pct])
        filas.append([titulo, f"Total {titulo.lower()}", r.totales[grupo], reportes.porcentaje(r.totales[grupo],
                                                                                               r.totales["ingreso"])])
    neto = r.totales["ingreso"] - r.totales["retencion"] - r.totales["deduccion"]
    filas.append(["", "Neto pagado a empleados", neto, reportes.porcentaje(neto, r.totales["ingreso"])])
    return Tabla(
        [("Grupo", "texto"), ("Concepto", "texto"), ("Monto", "dinero"), ("% del bruto", "pct")], filas,
        ["", "COSTO TOTAL (bruto + patronal)", r.costo_total, reportes.porcentaje(r.costo_total, r.totales["ingreso"])],
        [f"{r.nominas} nómina(s), {r.empleados} empleado(s). Incluye nóminas cerradas y reversos por fecha de pago."],
    )


def _tabla_empleados(compania, desde, hasta):
    filas_datos = reportes.por_empleado(compania, desde, hasta)
    columnas = ([("Núm.", "corto"), ("Empleado", "texto"), ("SSN", "corto"), ("Horas", "horas"), ("Bruto", "dinero")]
                + [(t, "dinero") for _, t in reportes.COLUMNAS_RETENCION]
                + [("Otras ret.", "dinero"), ("Deducciones", "dinero"), ("Neto", "dinero"), ("Patronal", "dinero"),
                   ("% patronal", "pct"), ("Costo total", "dinero")])
    filas = [
        [f["numero_empleado"], f["empleado_nombre"], f"XXX-XX-{f['ssn_ultimos4']}", f["horas"], f["bruto"]]
        + f["columnas"] + [f["otras_retenciones"], f["deducciones"], f["neto"], f["patronal"], f["pct_patronal"], f["costo"]]
        for f in filas_datos
    ]
    totales = None
    if filas:
        totales = ["", "TOTAL", ""]
        for i, (_, tipo) in enumerate(columnas[3:], start=3):
            totales.append(None if tipo == "pct" else sum((fila[i] for fila in filas), reportes.CERO))
        i_pct = [t for t, _ in columnas].index("% patronal")
        totales[i_pct] = reportes.porcentaje(totales[i_pct - 1], totales[4])
    return Tabla(columnas, filas, totales, ["Con el rango del año completo es el acumulado del año (YTD) de cada empleado."])


def _tabla_costo(compania, desde, hasta, agrupar):
    conceptos, filas_datos, total = reportes.costo_patronal(compania, desde, hasta, agrupar)
    columnas = [("Empleado" if agrupar == "empleado" else "Departamento", "texto"), ("Salario bruto", "dinero")]
    for nombre in conceptos:
        columnas += [(nombre, "dinero"), ("%", "pct")]
    columnas += [("Total patronal", "dinero"), ("%", "pct"), ("Costo total", "dinero"), ("% del costo", "pct")]

    def fila(nombre, d, pct_total):
        valores = [nombre, d["bruto"]]
        for monto, pct in d["conceptos"]:
            valores += [monto, pct]
        return valores + [d["patronal"], d["pct_patronal"], d["costo"], pct_total]

    filas = [fila(f["nombre"], f, f["pct_del_total"]) for f in filas_datos]
    return Tabla(columnas, filas, fila("TOTAL", total, reportes.porcentaje(1, 1)) if filas else None,
                 ["Cada % es sobre el salario bruto; «% del costo» es la parte del costo total de la compañía."])


def _tabla_impuestos(compania, desde, hasta):
    hoy = timezone.localdate()
    obligaciones = reportes.impuestos(compania, desde, hasta)
    filas = []
    for o in sorted(obligaciones, key=lambda o: (o.vence or date.max, o.agencia)):
        if o.vence is None:
            estado = "Según póliza"
        elif o.vence < hoy:
            estado = "Venció"
        else:
            estado = f"En {(o.vence - hoy).days} día(s)"
        filas.append([o.agencia, o.concepto, o.formulario, o.periodo, o.monto, o.vence, estado])
    notas = sorted({f"{o.concepto}: {o.nota}" for o in obligaciones if o.nota})
    notas.append("Fechas y reglas POR VERIFICAR con el IRS, Hacienda y el DTRH. Si la fecha cae en fin de semana o "
                 "feriado federal pasa al próximo día laborable; los feriados sólo de Puerto Rico no se consideran.")
    total = sum((o.monto for o in obligaciones), start=reportes.CERO)
    return Tabla(
        [("Agencia", "texto"), ("Concepto", "texto"), ("Formulario", "texto"), ("Período", "texto"),
         ("Monto", "dinero"), ("Vence", "fecha"), ("Estado", "texto")],
        filas, ["TOTAL", "", "", "", total, None, ""] if filas else None, notas,
    )


def _formato_celda(valor, tipo):
    if valor is None:
        return ""
    if tipo == "pct":
        return f"{valor:,.2f}%"
    if tipo == "fecha":
        return f"{valor:%m/%d/%Y}"
    if tipo == "dinero":
        return f"-${-valor:,.2f}" if valor < 0 else f"${valor:,.2f}"
    if tipo == "horas":
        return f"{valor:,.2f}"
    return str(valor)


@requiere_compania
def reportes_vista(request):
    reporte = request.GET.get("reporte") if request.GET.get("reporte") in dict(REPORTES) else "resumen"
    agrupar = "departamento" if request.GET.get("agrupar") == "departamento" else "empleado"
    r = rango_solicitado(request.GET)
    compania = request.compania
    if reporte == "resumen":
        tabla = _tabla_resumen(compania, r["desde"], r["hasta"])
    elif reporte == "empleados":
        tabla = _tabla_empleados(compania, r["desde"], r["hasta"])
    elif reporte == "costo":
        tabla = _tabla_costo(compania, r["desde"], r["hasta"], agrupar)
    else:
        tabla = _tabla_impuestos(compania, r["desde"], r["hasta"])
    titulo = dict(REPORTES)[reporte] + (" por departamento" if reporte == "costo" and agrupar == "departamento" else "")
    formato = request.GET.get("formato")
    nombre_archivo = f"{reporte}_{r['desde']:%Y%m%d}_{r['hasta']:%Y%m%d}"
    if formato in ("xlsx", "pdf"):
        registrar(request, Accion.ARCHIVO_GENERADO, descripcion=f"Reporte {titulo} ({r['etiqueta']}) {formato.upper()}")
    if formato == "xlsx":
        # Cada columna «%» lleva el nombre de la columna de dinero que tiene al lado.
        titulos = [c for c, _ in tabla.columnas]
        encabezados = [f"% {titulos[i - 1]}" if t == "%" else t for i, t in enumerate(titulos)]
        contenido = hojas.libro_xlsx(titulo[:31], encabezados, tabla.filas, tabla.totales)
        respuesta = HttpResponse(contenido,
                                 content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre_archivo}.xlsx"'
        return respuesta
    if formato == "pdf":
        def fmt(fila):
            return [_formato_celda(v, t) for v, (_, t) in zip(fila, tabla.columnas)]

        contenido = tabla_pdf(
            titulo=titulo, subtitulo=f"Nóminas pagadas del {r['desde']:%m/%d/%Y} al {r['hasta']:%m/%d/%Y}",
            compania=compania, encabezados=[c for c, _ in tabla.columnas], filas=[fmt(f) for f in tabla.filas],
            totales=fmt(tabla.totales) if tabla.totales else None, notas=tabla.notas,
            tipos=[t for _, t in tabla.columnas],
        )
        respuesta = HttpResponse(contenido, content_type="application/pdf")
        respuesta["Content-Disposition"] = f'inline; filename="{nombre_archivo}.pdf"'
        return respuesta
    filas = [[(_formato_celda(v, t), t) for v, (_, t) in zip(fila, tabla.columnas)] for fila in tabla.filas]
    totales = ([(_formato_celda(v, t), t) for v, (_, t) in zip(tabla.totales, tabla.columnas)]
               if tabla.totales else None)
    consulta = request.GET.copy()
    consulta.pop("formato", None)
    return render(request, "nomina/reportes.html", {
        "reportes": REPORTES, "reporte": reporte, "titulo": titulo, "agrupar": agrupar, "r": r,
        "columnas": tabla.columnas, "filas": filas, "totales": totales, "notas": tabla.notas,
        "meses": list(enumerate(MESES, start=1)), "consulta": consulta.urlencode(),
    })
