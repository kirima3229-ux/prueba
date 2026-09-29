"""Talonarios de pago en PDF (ReportLab), con acumulados del año y balances de licencias."""

import io
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.companias.logo import escala, para_pdf
from apps.licencias.models import saldo

from .servicios import acumulados_por_concepto

AZUL = colors.HexColor("#0b3a63")
GRIS = colors.HexColor("#eef1f5")


def _dinero(valor) -> str:
    valor = Decimal(valor)
    return f"-${-valor:,.2f}" if valor < 0 else f"${valor:,.2f}"


def _tabla_conceptos(titulo, lineas, ytd, grupo):
    # Varias líneas del mismo concepto (p. ej. horas extra de distintos tipos) se suman en una fila.
    por_concepto = {}
    for linea in lineas:
        nombre, monto = por_concepto.get(linea.codigo, (linea.nombre, Decimal("0")))
        por_concepto[linea.codigo] = (nombre, monto + linea.monto)
    filas = [[titulo, "Actual", "Acumulado del año"]]
    for codigo, (nombre, monto) in por_concepto.items():
        filas.append([nombre, _dinero(monto), _dinero(ytd.get((grupo, codigo), 0))])
    total = sum((m for _, m in por_concepto.values()), Decimal("0"))
    total_ytd = sum((ytd.get((grupo, c), Decimal("0")) for c in por_concepto), Decimal("0"))
    filas.append(["Total", _dinero(total), _dinero(total_ytd)])
    tabla = Table(filas, colWidths=[3.3 * inch, 1.5 * inch, 1.7 * inch])
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GRIS),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("LINEABOVE", (0, -1), (-1, -1), 0.5, colors.grey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
    ]))
    return tabla


def _encabezado(compania, estilos, logo):
    titulo = estilos["Title"].clone("titulo", fontSize=14, textColor=AZUL, spaceAfter=2, alignment=0)
    texto = [Paragraph(compania.nombre, titulo)]
    direccion = " ".join(p for p in [compania.direccion_linea1, compania.ciudad, compania.estado, compania.codigo_postal] if p)
    if direccion:
        texto.append(Paragraph(direccion, estilos["Normal"]))
    if logo is None:
        return texto
    w, h = escala(logo.ancho, logo.alto, 1.8 * inch, 0.75 * inch)
    tabla = Table([[Image(io.BytesIO(logo.datos), width=w, height=h), texto]], colWidths=[w + 0.15 * inch, None])
    tabla.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (0, 0), 0)]))
    return [tabla]


def _talonario(resultado, estilos, logo=None):
    periodo = resultado.periodo
    compania = periodo.compania
    ytd = acumulados_por_concepto(resultado)
    lineas = list(resultado.lineas.all())
    elementos = _encabezado(compania, estilos, logo)
    if periodo.tipo == "reverso":
        elementos.append(Paragraph("<b>REVERSO</b> — este documento anula un pago anterior.", estilos["Normal"]))
    elementos.append(Spacer(1, 8))

    encabezado = Table([
        ["Empleado", f"{resultado.empleado_nombre} (núm. {resultado.numero_empleado})", "Período",
         f"{periodo.fecha_inicio:%m/%d/%Y} – {periodo.fecha_fin:%m/%d/%Y}"],
        ["SSN", f"XXX-XX-{resultado.ssn_ultimos4}", "Fecha de pago", f"{periodo.fecha_pago:%m/%d/%Y}"],
        ["Departamento", resultado.departamento or "—", "Tarifa",
         f"${resultado.tarifa:,.2f} {'por hora' if resultado.tipo_pago == 'hora' else 'por período'}"],
    ], colWidths=[1.1 * inch, 2.6 * inch, 1.1 * inch, 1.7 * inch])
    encabezado.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, -1), colors.whitesmoke),
    ]))
    elementos += [encabezado, Spacer(1, 10)]

    for titulo_tabla, grupo in (("Ingresos", "ingreso"), ("Retenciones", "retencion"), ("Deducciones", "deduccion")):
        del_grupo = [l for l in lineas if l.grupo == grupo and l.monto]
        if del_grupo or grupo != "deduccion":
            elementos += [_tabla_conceptos(titulo_tabla, del_grupo, ytd, grupo), Spacer(1, 8)]

    neto_ytd = (
        sum((v for (g, _), v in ytd.items() if g == "ingreso"), Decimal("0"))
        - sum((v for (g, _), v in ytd.items() if g in ("retencion", "deduccion")), Decimal("0"))
    )
    neto = Table([["NETO A PAGAR", _dinero(resultado.neto), _dinero(neto_ytd)]],
                 colWidths=[3.3 * inch, 1.5 * inch, 1.7 * inch])
    neto.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("BACKGROUND", (0, 0), (-1, -1), GRIS),
        ("BOX", (0, 0), (-1, -1), 0.8, AZUL),
    ]))
    elementos += [neto, Spacer(1, 10)]

    horas_dia = Decimal("8")
    vac, enf = saldo(resultado.empleado, "vacaciones"), saldo(resultado.empleado, "enfermedad")
    balances = Table([
        ["Balances de licencia", "Horas", "Días"],
        ["Vacaciones", f"{vac:,.2f}", f"{vac / horas_dia:,.2f}"],
        ["Enfermedad", f"{enf:,.2f}", f"{enf / horas_dia:,.2f}"],
    ], colWidths=[3.3 * inch, 1.5 * inch, 1.7 * inch])
    balances.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GRIS), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    elementos += [balances, Spacer(1, 6),
                  Paragraph(f"Horas trabajadas en el período: {resultado.horas_trabajadas:,.2f}", estilos["Normal"])]
    return elementos


def generar_pdf(resultados) -> bytes:
    """Un PDF con un talonario por página."""
    salida = io.BytesIO()
    doc = SimpleDocTemplate(salida, pagesize=letter, leftMargin=0.8 * inch, rightMargin=0.8 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch, title="Talonarios de pago")
    estilos = getSampleStyleSheet()
    elementos = []
    logo = para_pdf(resultados[0].periodo.compania) if resultados else None
    for i, resultado in enumerate(resultados):
        if i:
            elementos.append(PageBreak())
        elementos += _talonario(resultado, estilos, logo)
    doc.build(elementos)
    return salida.getvalue()
