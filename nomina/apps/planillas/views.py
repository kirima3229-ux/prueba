"""Planillas de gobierno: hojas de trabajo en pantalla, PDF y Excel, y registro de radicaciones."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.auditoria.servicios import Accion, registrar
from apps.core import fechas
from apps.core.permisos import requiere_compania
from apps.core.tablas import Tabla, exportar
from apps.empleados.forms import FechaInput

from . import datos
from .models import Radicacion

CERO = Decimal("0")
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]


@dataclass(frozen=True)
class Tipo:
    codigo: str
    nombre: str
    agencia: str
    periodicidad: str  # anual | trimestral | poliza
    con_identificacion: bool = False  # tiene un archivo para la agencia con SSN / identificación completa


TIPOS = [
    Tipo("r1b", "499 R-1B · Retención trimestral", "Hacienda", "trimestral"),
    Tipo("941", "941 · Seguro Social y Medicare", "IRS", "trimestral"),
    Tipo("dtrh", "Desempleo e incapacidad (SINOT)", "DTRH", "trimestral", True),
    Tipo("choferil", "Seguro Choferil", "DTRH", "trimestral", True),
    Tipo("w2pr", "499R-2/W-2PR · Comprobantes de retención", "Hacienda / SSA", "anual", True),
    Tipo("r3", "499R-3 · Reconciliación anual", "Hacienda", "anual"),
    Tipo("940", "940 · Desempleo federal (FUTA)", "IRS", "anual"),
    Tipo("servicios", "480.6SP · Servicios prestados", "Hacienda", "anual", True),
    Tipo("cfse", "CFSE · Nómina por clasificación", "CFSE", "poliza"),
]
POR_CODIGO = {t.codigo: t for t in TIPOS}


def vencimiento(tipo: Tipo, anio, trimestre):
    if tipo.periodicidad == "trimestral":
        return fechas.vence_trimestral(anio, trimestre)
    if tipo.codigo in ("w2pr", "r3", "940"):
        return fechas.proximo_laborable(date(anio + 1, 1, 31))
    if tipo.codigo == "servicios":
        return fechas.proximo_laborable(date(anio + 1, 2, 28))
    return None


def _ssn(empleado, completo):
    if completo:
        digitos = empleado.ssn.revelar() if empleado.ssn else ""
        return f"{digitos[:3]}-{digitos[3:5]}-{digitos[5:]}" if len(digitos) == 9 else digitos
    return f"XXX-XX-{empleado.ssn_ultimos4}"


# --- Tablas de cada planilla ---------------------------------------------------------


def _t_w2pr(compania, anio, trimestre, completo):
    filas_datos = datos.w2pr(compania, anio)
    columnas = [("Núm.", "corto"), ("Empleado", "texto"), ("SSN", "corto"), ("Sueldos", "dinero"),
                ("Comisiones", "dinero"), ("Concesiones", "dinero"), ("Propinas", "dinero"),
                ("Total tributable", "dinero"), ("Reembolsos", "dinero"), ("Indemnización (exenta)", "dinero"),
                ("Otros exentos", "dinero"), ("Aportaciones antes de PR", "dinero"), ("Sujeto a retención", "dinero"),
                ("Contribución retenida", "dinero"),
                ("Salarios SS", "dinero"), ("Propinas SS", "dinero"), ("SS retenido", "dinero"),
                ("Salarios Medicare", "dinero"), ("Medicare retenido", "dinero")]
    filas = [[d.empleado.numero_empleado, d.empleado.nombre_completo, _ssn(d.empleado, completo), d.sueldos,
              d.comisiones, d.concesiones, d.propinas, d.total_tributable, d.reembolsos, d.indemnizacion,
              d.otros_exentos, d.total_aportaciones, d.sujeto_pr, d.retenido_pr, d.salarios_ss, d.propinas_ss, d.retenido_ss,
              d.salarios_medicare, d.retenido_medicare] for d in filas_datos]
    totales = ["", f"TOTAL ({len(filas)})", ""] + [sum((f[i] for f in filas), CERO) for i in range(3, len(columnas))]
    notas = ["Casillas del formulario POR VERIFICAR con el 499R-2/W-2PR del año. Las aportaciones antes de PR son las "
             "deducciones marcadas así (planes cualificados, Sección 125); revise en qué casilla va cada una.",
             "El archivo electrónico EFW2PR (Publicación 25-01 de Hacienda) se genera cuando se incorpore la "
             "especificación oficial."]
    detalle = [f"{d.empleado.nombre_completo}: " + ", ".join(f"{k} ${v:,.2f}" for k, v in d.aportaciones.items())
               for d in filas_datos if d.aportaciones]
    return Tabla(columnas, filas, totales if filas else None, notas + detalle)


def _t_r1b(compania, anio, trimestre, completo):
    meses = datos.r1b(compania, anio, trimestre)
    filas = [[MESES[m.mes - 1].capitalize(), m.pagado, m.sujeto, m.retenido, fechas.vence_mensual(date(anio, m.mes, 1))]
             for m in meses]
    totales = ["TOTAL DEL TRIMESTRE", sum((m.pagado for m in meses), CERO), sum((m.sujeto for m in meses), CERO),
               sum((m.retenido for m in meses), CERO), None]
    return Tabla([("Mes", "texto"), ("Salarios pagados", "dinero"), ("Sujeto a retención", "dinero"),
                  ("Contribución retenida", "dinero"), ("Depósito mensual vence", "fecha")], filas, totales,
                 ["Salarios pagados excluye reembolsos. Si la compañía deposita bisemanalmente, vea las fechas en "
                  "Nómina → Impuestos a pagar. Líneas de la planilla POR VERIFICAR."])


def _t_r3(compania, anio, trimestre, completo):
    filas = []
    total = [CERO, CERO, CERO]
    for t in range(1, 5):
        meses = datos.r1b(compania, anio, t)
        valores = [sum((getattr(m, c) for m in meses), CERO) for c in ("pagado", "sujeto", "retenido")]
        total = [a + b for a, b in zip(total, valores)]
        filas.append([f"Trimestre {t} (499 R-1B)", *valores])
    w2 = datos.w2pr(compania, anio)
    w2_total = [sum((d.total_tributable + d.otros_exentos + d.indemnizacion for d in w2), CERO),
                sum((d.sujeto_pr for d in w2), CERO), sum((d.retenido_pr for d in w2), CERO)]
    filas.append(["Total de los W-2PR", *w2_total])
    diferencia = [a - b for a, b in zip(total, w2_total)]
    notas = ["Los totales trimestrales y los de los comprobantes deben coincidir antes de radicar."]
    if any(diferencia):
        notas.insert(0, "⚠ HAY DIFERENCIAS entre los trimestres y los W-2PR: revíselas.")
    return Tabla([("Concepto", "texto"), ("Pagado", "dinero"), ("Sujeto a retención", "dinero"),
                  ("Retenido", "dinero")], filas, ["Diferencia (trimestres − W-2PR)", *diferencia], notas)


def _t_941(compania, anio, trimestre, completo):
    p = datos.f941(compania, anio, trimestre)
    filas = [
        ["1", f"Empleados que recibieron pago en el período que incluye el 12 del último mes: {p.empleados_12}",
         None, None],
        ["2", "Salarios, propinas y otra compensación (sólo si hay retención federal)", p.salarios, None],
        ["3", "Contribución federal retenida", None, p.retencion_federal],
        ["5a", "Salarios sujetos al Seguro Social × 12.4%", p.salarios_ss, p.l5a],
        ["5b", "Propinas sujetas al Seguro Social × 12.4%", p.propinas_ss, p.l5b],
        ["5c", "Salarios y propinas sujetos al Medicare × 2.9%", p.salarios_medicare, p.l5c],
        ["5d", "Sujeto al Medicare adicional × 0.9%", p.sujeto_medicare_adicional, p.l5d],
        ["5e", "Total Seguro Social y Medicare", None, p.l5e],
        ["6", "Total antes de ajustes", None, p.l6],
        ["7", "Ajuste por fracciones de centavo", None, p.l7],
        ["10", "Total después de ajustes", None, p.l10],
        ["12", "Total después de créditos", None, p.l10],
    ]
    semanal = compania.frecuencia_deposito_federal == "bisemanal"
    if semanal:
        filas += [["Anejo B", f"Obligación del día {f:%m/%d/%Y}", None, v] for f, v in p.por_dia]
    else:
        filas += [["16", f"Obligación de {MESES[m - 1]}", None, v] for m, v in p.por_mes]
    filas.append(["", "Total de la obligación del trimestre (debe ser igual a la línea 12)", None, p.total_mensual])
    notas = ["Depositante " + ("bisemanal: complete el Anejo B (Schedule B)." if semanal else "mensual: línea 16."),
             "Líneas 13 (depósitos) a 15 y los créditos se completan con los pagos hechos. Líneas POR VERIFICAR "
             "con el formulario 941 / 941 (sp) del año."]
    if p.total_mensual != p.l10:
        notas.insert(0, "⚠ La obligación del trimestre no cuadra con la línea 12.")
    return Tabla([("Línea", "corto"), ("Descripción", "texto"), ("Columna 1", "dinero"), ("Columna 2", "dinero")],
                 filas, None, notas)


def _t_940(compania, anio, trimestre, completo):
    p = datos.f940(compania, anio)
    filas = [
        ["3", "Pagos totales a empleados", p.pagos_totales],
        ["4", "Pagos exentos de FUTA", p.pagos_exentos],
        ["5", f"Pagos en exceso de ${p.tope:,.0f} por empleado", p.exceso_7000],
        ["6", "Subtotal (4 + 5)", p.l6],
        ["7", "Salarios sujetos a FUTA (3 − 6)", p.l7],
        ["8", f"FUTA antes de ajustes (7 × {p.tasa}%)", p.l8],
    ]
    filas += [["16", f"Obligación del trimestre {t}", v] for t, v in p.por_trimestre]
    notas = ["Puerto Rico no es estado de reducción de crédito para el año (POR VERIFICAR). Si lo acumulado sin "
             "depositar es $500 o menos, se pasa al próximo trimestre."]
    if p.futa_calculado != p.l8:
        notas.insert(0, f"Nota: lo calculado en las nóminas suma ${p.futa_calculado:,.2f}; la diferencia con la línea 8 "
                        "es de redondeo o de salarios de otros años.")
    return Tabla([("Línea", "corto"), ("Descripción", "texto"), ("Monto", "dinero")], filas, None, notas)


def _t_dtrh(compania, anio, trimestre, completo):
    filas_datos, meses = datos.dtrh(compania, anio, trimestre)
    columnas = [("SSN", "corto"), ("Empleado", "texto"), ("Salarios del trimestre", "dinero"),
                ("Tributable desempleo", "dinero"), ("Tributable SINOT", "dinero"), ("SUTA", "dinero"),
                ("Aportación especial", "dinero"), ("SINOT empleado", "dinero"), ("SINOT patrono", "dinero")]
    filas = [[_ssn(f.empleado, completo), f.empleado.nombre_completo, f.salarios, f.tributable_desempleo,
              f.tributable_sinot, f.suta, f.aportacion_especial, f.sinot_empleado, f.sinot_patrono] for f in filas_datos]
    totales = ["", f"TOTAL ({len(filas)})"] + [sum((f[i] for f in filas), CERO) for i in range(2, len(columnas))]
    notas = ["Empleados en nómina el día 12: " + ", ".join(f"{MESES[m - 1]} {n}" for m, n in meses) + ".",
             "Topes anuales: desempleo y SINOT según Configuración del año. El archivo para subir al DTRH se "
             "genera cuando se incorpore el formato oficial (muestra pendiente)."]
    return Tabla(columnas, filas, totales if filas else None, notas)


def _t_choferil(compania, anio, trimestre, completo):
    filas_datos = datos.choferil(compania, anio, trimestre)
    filas = [[_ssn(f.empleado, completo), f.empleado.nombre_completo, Decimal(f.semanas), f.empleado_monto,
              f.patrono_monto, f.empleado_monto + f.patrono_monto] for f in filas_datos]
    totales = ["", f"TOTAL ({len(filas)})"] + [sum((f[i] for f in filas), CERO) for i in range(2, 6)]
    return Tabla([("SSN", "corto"), ("Empleado", "texto"), ("Semanas", "horas"), ("Empleado $", "dinero"),
                  ("Patrono $", "dinero"), ("Total", "dinero")], filas, totales if filas else None,
                 ["Semanas según cada nómina (cuota fija semanal POR VERIFICAR)."])


def _t_cfse(compania, anio, trimestre, completo):
    desde, hasta = datos.anio_poliza_cfse(anio)
    filas_datos = datos.cfse(compania, desde, hasta)
    filas = [[f.clasificacion, f.descripcion, Decimal(f.empleados), f.nomina, f.tasa, f.prima] for f in filas_datos]
    totales = ["TOTAL", "", None, sum((f.nomina for f in filas_datos), CERO), None,
               sum((f.prima for f in filas_datos), CERO)]
    return Tabla([("Clasificación", "corto"), ("Descripción", "texto"), ("Empleados", "horas"),
                  ("Nómina", "dinero"), ("Tasa por $100", "horas"), ("Prima (provisión)", "dinero")],
                 filas, totales if filas else None,
                 [f"Año de la póliza: {desde:%m/%d/%Y} al {hasta:%m/%d/%Y} (POR VERIFICAR con la póliza). "
                  "La clasificación es la que tenía el empleado al pagarse la nómina."])


def _t_servicios(compania, anio, trimestre, completo):
    filas_datos = datos.servicios_anual(compania, anio)

    def ident(p):
        if completo and p.identificacion:
            return p.identificacion.revelar()
        return p.identificacion_enmascarada

    filas = [[f.proveedor.numero, f.proveedor.nombre_mostrar, ident(f.proveedor), Decimal(f.pagos), f.pagado,
              f.retenido] for f in filas_datos]
    totales = ["", f"TOTAL ({len(filas)})", "", sum((f[3] for f in filas), CERO),
               sum((f.pagado for f in filas_datos), CERO), sum((f.retenido for f in filas_datos), CERO)]
    return Tabla([("Núm.", "corto"), ("Proveedor", "texto"), ("Identificación", "corto"), ("Pagos", "horas"),
                  ("Total pagado", "dinero"), ("Retenido", "dinero")], filas, totales if filas else None,
                 ["Base de la declaración informativa 480.6SP de cada proveedor. El archivo trimestral de servicios "
                  "prestados se genera cuando se incorpore el formato (pendiente)."])


CONSTRUCTORES = {"w2pr": _t_w2pr, "r1b": _t_r1b, "r3": _t_r3, "941": _t_941, "940": _t_940, "dtrh": _t_dtrh,
                 "choferil": _t_choferil, "cfse": _t_cfse, "servicios": _t_servicios}


# --- Vistas --------------------------------------------------------------------------


class RadicacionForm(forms.ModelForm):
    class Meta:
        model = Radicacion
        fields = ["fecha", "confirmacion", "monto", "notas"]
        widgets = {"fecha": FechaInput()}


def _periodo_solicitado(request, tipo):
    hoy = timezone.localdate()
    try:
        anio = int(request.GET.get("anio") or request.POST.get("anio") or 0)
    except ValueError:
        anio = 0
    try:
        trimestre = int(request.GET.get("trimestre") or request.POST.get("trimestre") or 0)
    except ValueError:
        trimestre = 0
    anterior = fechas.trimestre_de(hoy) - 1
    if not 2000 <= anio <= 2100:
        if tipo.periodicidad == "trimestral":
            anio = hoy.year if anterior else hoy.year - 1
        elif tipo.periodicidad == "poliza":
            anio = hoy.year - 1 if hoy.month < 7 else hoy.year
        else:
            anio = hoy.year - 1 if hoy.month <= 2 else hoy.year
    if tipo.periodicidad == "trimestral":
        if not 1 <= trimestre <= 4:
            trimestre = anterior or 4
    else:
        trimestre = None
    return anio, trimestre


def _etiqueta(tipo, anio, trimestre):
    if tipo.periodicidad == "trimestral":
        return f"trimestre {trimestre} de {anio}"
    if tipo.periodicidad == "poliza":
        return f"póliza {anio}-{anio + 1}"
    return f"año {anio}"


def _hay_datos(compania, tipo, anio, trimestre):
    if tipo.codigo == "servicios":
        from apps.servicios.models import PagoServicio

        return PagoServicio.objects.filter(compania=compania, anio=anio).exclude(estado="anulado").exists()
    if tipo.periodicidad == "trimestral":
        desde, hasta = fechas.rango_trimestre(anio, trimestre)
    elif tipo.periodicidad == "poliza":
        desde, hasta = datos.anio_poliza_cfse(anio)
    else:
        desde, hasta = date(anio, 1, 1), date(anio, 12, 31)
    return datos.resultados(compania, desde, hasta).exists()


@requiere_compania
def inicio(request):
    hoy = timezone.localdate()
    anio = int(request.GET["anio"]) if request.GET.get("anio", "").isdigit() else hoy.year
    radicadas = {(r.tipo, r.anio, r.trimestre) for r in Radicacion.objects.filter(compania=request.compania)}
    filas = []
    for tipo in TIPOS:
        periodos = [(anio, t) for t in range(1, 5)] if tipo.periodicidad == "trimestral" else [(anio, None)]
        for a, t in periodos:
            vence = vencimiento(tipo, a, t)
            radicada = (tipo.codigo, a, t) in radicadas
            filas.append({"tipo": tipo, "anio": a, "trimestre": t, "etiqueta": _etiqueta(tipo, a, t), "vence": vence,
                          "radicada": radicada, "con_datos": _hay_datos(request.compania, tipo, a, t),
                          "vencida": vence is not None and vence < hoy and not radicada})
    return render(request, "planillas/inicio.html", {"filas": filas, "anio": anio})


@requiere_compania
def planilla(request, codigo):
    tipo = POR_CODIGO.get(codigo)
    if tipo is None:
        raise Http404
    anio, trimestre = _periodo_solicitado(request, tipo)
    etiqueta = _etiqueta(tipo, anio, trimestre)
    compania = request.compania
    radicaciones = Radicacion.objects.filter(compania=compania, tipo=tipo.codigo, anio=anio, trimestre=trimestre)
    form = RadicacionForm(request.POST or None)
    if request.method == "POST":
        if not request.user.puede_editar:
            raise PermissionDenied("No tiene permiso para esta acción.")
        if form.is_valid():
            radicacion = form.save(commit=False)
            radicacion.compania, radicacion.tipo, radicacion.anio, radicacion.trimestre = (
                compania, tipo.codigo, anio, trimestre)
            radicacion.registrado_por = request.user
            radicacion.save()
            registrar(request, Accion.PLANILLA_RADICADA, objeto=radicacion,
                      descripcion=f"{tipo.nombre} — {etiqueta}: confirmación {radicacion.confirmacion}")
            messages.success(request, "Radicación registrada.")
            return redirect(f"{request.path}?anio={anio}" + (f"&trimestre={trimestre}" if trimestre else ""))
    formato = request.GET.get("formato")
    completo = formato == "agencia"
    if completo:
        if not tipo.con_identificacion:
            raise Http404
        if not request.user.puede_editar:
            raise PermissionDenied("No tiene permiso para descargar datos completos.")
    tabla = CONSTRUCTORES[tipo.codigo](compania, anio, trimestre, completo)
    nombre = f"{tipo.codigo}_{anio}" + (f"_T{trimestre}" if trimestre else "")
    if formato in ("xlsx", "pdf", "agencia"):
        registrar(request, Accion.ARCHIVO_GENERADO,
                  descripcion=f"{tipo.nombre} ({etiqueta}) "
                              + ("Excel para la agencia con identificación completa" if completo else formato.upper()))
        return exportar(tabla, "xlsx" if completo else formato, titulo=tipo.nombre, compania=compania,
                        subtitulo=f"{tipo.agencia} · {etiqueta}", hoja=tipo.codigo,
                        nombre_archivo=nombre + ("_agencia" if completo else ""))
    filas, totales = tabla.para_pantalla()
    return render(request, "planillas/planilla.html", {
        "tipo": tipo, "anio": anio, "trimestre": trimestre, "etiqueta": etiqueta,
        "vence": vencimiento(tipo, anio, trimestre), "columnas": tabla.columnas, "filas": filas, "totales": totales,
        "notas": tabla.notas, "radicaciones": radicaciones, "form": form, "tipos": TIPOS,
    })
