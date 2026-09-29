"""Reportes tabulares en PDF (carta horizontal) con encabezado de compañía y pie de página."""

import io

from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

AZUL = colors.HexColor("#0b3a63")
GRIS = colors.HexColor("#eef1f5")


def _texto(valor):
    from decimal import Decimal

    if valor is None:
        return ""
    if isinstance(valor, Decimal):
        return f"{valor:,.2f}"
    return str(valor)


PESOS = {"texto": 2.0, "corto": 0.8, "dinero": 1.0, "horas": 0.75, "pct": 0.72, "fecha": 0.9}


def tabla_pdf(*, titulo, subtitulo="", compania=None, encabezados, filas, totales=None, notas=(), tipos=None) -> bytes:
    """`tipos` (texto, dinero, horas, pct, fecha) decide el ancho y la alineación de cada columna."""
    salida = io.BytesIO()
    doc = SimpleDocTemplate(salida, pagesize=landscape(letter), leftMargin=0.4 * inch, rightMargin=0.4 * inch,
                            topMargin=0.5 * inch, bottomMargin=0.5 * inch, title=titulo)
    estilos = getSampleStyleSheet()
    elementos = []
    if compania is not None:
        elementos.append(Paragraph(f"<b>{compania.nombre}</b>", estilos["Normal"]))
    elementos.append(Paragraph(titulo, estilos["Title"].clone("t", alignment=0, fontSize=14, textColor=AZUL, spaceAfter=2)))
    if subtitulo:
        elementos.append(Paragraph(subtitulo, estilos["Normal"]))
    elementos.append(Spacer(1, 8))
    tamano = 8 if len(encabezados) <= 10 else 6.5 if len(encabezados) <= 16 else 5.5
    estilo_celda = estilos["Normal"].clone("c", fontSize=tamano, leading=tamano + 1.5)
    tipos = tipos or ["texto"] + ["dinero"] * (len(encabezados) - 1)
    estilo_derecha = estilo_celda.clone("d", alignment=2)

    def celda(valor, tipo, negrita=False):
        texto = _texto(valor).replace("&", "&amp;").replace("<", "&lt;")
        if negrita:
            texto = f"<b>{texto}</b>"
        return Paragraph(texto, estilo_celda if tipo in ("texto", "corto") else estilo_derecha)

    datos = [[celda(e, t, True) for e, t in zip(encabezados, tipos)]]
    datos += [[celda(v, t) for v, t in zip(fila, tipos)] for fila in filas]
    if totales:
        datos.append([celda(v, t, True) for v, t in zip(totales, tipos)])
    ancho_total = 10.2 * inch
    pesos = [PESOS.get(t, 1.0) for t in tipos]
    anchos = [ancho_total * p / sum(pesos) for p in pesos]
    tabla = Table(datos, colWidths=anchos, repeatRows=1)
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), GRIS), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3), ("RIGHTPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fb")]),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]
    if totales:
        estilo += [("LINEABOVE", (0, -1), (-1, -1), 0.8, AZUL)]
    tabla.setStyle(TableStyle(estilo))
    elementos.append(tabla)
    for nota in notas:
        elementos += [Spacer(1, 4), Paragraph(nota, estilos["Normal"].clone("n", fontSize=7.5))]

    def pie(canvas, doc_):
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        canvas.drawString(0.4 * inch, 0.3 * inch, f"Generado {timezone.localtime():%m/%d/%Y %I:%M %p}")
        canvas.drawRightString(10.6 * inch, 0.3 * inch, f"Página {doc_.page}")
        canvas.restoreState()

    doc.build(elementos, onFirstPage=pie, onLaterPages=pie)
    return salida.getvalue()
