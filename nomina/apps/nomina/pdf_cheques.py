"""
Cheques de nómina en papel tipo voucher (carta 8.5" × 11": cheque y dos talonarios, perforados a 3.5" y 7").

El papel de cheque trae preimpresos el banco, la línea MICR y el número; el sistema imprime la fecha, el
beneficiario, el monto y el talonario. Las posiciones se calibran por compañía con los ajustes del formato
y la página de prueba de alineación.
"""

import io
from decimal import Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle

from apps.core.letras import monto_en_letras
from apps.licencias.models import saldo

from .servicios import acumulados_por_concepto
from .talonario import _dinero

ALTO_PAGINA = 11 * inch
ALTO_SECCION = 3.5 * inch
ALTO_FILA = 0.14 * inch
MAX_FILAS = 11  # filas de conceptos por tabla del talonario; el resto se agrupa en «Otros»


class _Hoja:
    """Posiciona en pulgadas desde la esquina superior izquierda de una sección, con el ajuste de calibración."""

    def __init__(self, c, formato, seccion):
        self.c = c
        self.dx = float(formato.ajuste_horizontal) * inch
        self.top = ALTO_PAGINA - seccion * ALTO_SECCION - float(formato.ajuste_vertical) * inch

    def xy(self, x, y):
        return x * inch + self.dx, self.top - y * inch

    def texto(self, x, y, texto, tamano=10, negrita=False, derecha=False, centro=False):
        self.c.setFont("Helvetica-Bold" if negrita else "Helvetica", tamano)
        px, py = self.xy(x, y)
        if derecha:
            self.c.drawRightString(px, py, texto)
        elif centro:
            self.c.drawCentredString(px, py, texto)
        else:
            self.c.drawString(px, py, texto)


def _secciones(formato):
    cheque = {"arriba": 0, "medio": 1, "abajo": 2}[formato.posicion]
    return cheque, [s for s in (0, 1, 2) if s != cheque]


def _direccion(empleado):
    ciudad = " ".join(p for p in [empleado.ciudad, empleado.estado, empleado.codigo_postal] if p)
    return [l for l in [empleado.direccion_linea1, empleado.direccion_linea2, ciudad] if l]


def _encabezado_compania(h, compania, numero=None):
    h.texto(0.45, 0.42, compania.nombre, 11, negrita=True)
    ciudad = " ".join(p for p in [compania.ciudad, compania.estado, compania.codigo_postal] if p)
    for i, linea in enumerate(l for l in [compania.direccion_linea1, compania.direccion_linea2, ciudad] if l):
        h.texto(0.45, 0.58 + i * 0.14, linea, 8)
    if numero is not None:
        h.texto(8.05, 0.42, str(numero), 11, negrita=True, derecha=True)


def _cheque(h, formato, cheque, resultado):
    periodo = resultado.periodo
    if formato.imprimir_encabezado:
        _encabezado_compania(h, periodo.compania, cheque.numero)
    h.texto(6.9, 0.95, f"{cheque.fecha:%m/%d/%Y}", 10)
    h.texto(1.0, 1.38, cheque.beneficiario, 10)
    h.texto(7.95, 1.38, f"**{cheque.monto:,.2f}", 11, negrita=True, derecha=True)
    letras = monto_en_letras(cheque.monto, formato.idioma)
    tamano = 9 if len(letras) < 85 else 7.5
    # Asteriscos hasta el final de la línea para que no se pueda añadir texto.
    h.c.setFont("Helvetica", tamano)
    ancho_libre = 7.1 * inch - h.c.stringWidth(letras + " ", "Helvetica", tamano)
    relleno = "*" * max(0, int(ancho_libre / h.c.stringWidth("*", "Helvetica", tamano)))
    h.texto(0.5, 1.75, f"{letras} {relleno}", tamano)
    for i, linea in enumerate([cheque.beneficiario] + _direccion(resultado.empleado)):
        h.texto(1.0, 2.1 + i * 0.15, linea, 9)
    h.texto(0.6, 2.98, f"Nómina {periodo.fecha_inicio:%m/%d/%Y} – {periodo.fecha_fin:%m/%d/%Y}", 8)


def _aviso_deposito(h, resultado):
    empleado = resultado.empleado
    _encabezado_compania(h, resultado.periodo.compania)
    h.texto(4.25, 1.2, "AVISO DE DEPÓSITO DIRECTO", 14, negrita=True, centro=True)
    h.texto(4.25, 1.45, "NO NEGOCIABLE — ESTE DOCUMENTO NO ES UN CHEQUE", 9, centro=True)
    h.texto(0.8, 2.0, f"Depositado a: {resultado.empleado_nombre}", 10)
    cuenta = empleado.cuenta_enmascarada
    h.texto(0.8, 2.2, f"{empleado.banco_nombre or 'Cuenta'} {cuenta}".strip(), 9)
    h.texto(7.95, 2.0, f"${resultado.neto:,.2f}", 12, negrita=True, derecha=True)
    h.texto(7.95, 2.2, f"Fecha: {resultado.periodo.fecha_pago:%m/%d/%Y}", 9, derecha=True)


def _tabla(titulo, filas_datos):
    filas = [[titulo, "Actual", "Año"]] + filas_datos
    tabla = Table(filas, colWidths=[2.1 * inch, 0.75 * inch, 0.85 * inch], rowHeights=ALTO_FILA)
    tabla.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.grey),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
    ]))
    return tabla


def _filas(lineas, ytd, grupos):
    por_concepto = {}
    for l in lineas:
        if l.grupo in grupos:
            nombre, monto = por_concepto.get((l.grupo, l.codigo), (l.nombre, Decimal("0")))
            por_concepto[(l.grupo, l.codigo)] = (nombre, monto + l.monto)
    filas = [[nombre[:40], _dinero(monto), _dinero(ytd.get(clave, 0))] for clave, (nombre, monto) in por_concepto.items()]
    if len(filas) > MAX_FILAS:
        resto = list(por_concepto.items())[MAX_FILAS - 1:]
        filas = filas[:MAX_FILAS - 1] + [[
            "Otros", _dinero(sum((m for _, (_, m) in resto), Decimal("0"))),
            _dinero(sum((ytd.get(k, Decimal("0")) for k, _ in resto), Decimal("0"))),
        ]]
    return filas


def _talonario(h, formato, resultado, datos, rotulo, pago):
    periodo = resultado.periodo
    compania = periodo.compania
    h.texto(0.4, 0.3, compania.nombre, 9, negrita=True)
    h.texto(8.1, 0.3, rotulo, 8, derecha=True)
    h.texto(0.4, 0.48, f"{resultado.empleado_nombre} (núm. {resultado.numero_empleado}) · SSN XXX-XX-{resultado.ssn_ultimos4}"
                       + (f" · {resultado.departamento}" if resultado.departamento else ""), 8)
    h.texto(0.4, 0.62, f"Período {periodo.fecha_inicio:%m/%d/%Y} – {periodo.fecha_fin:%m/%d/%Y} · "
                       f"Pago {periodo.fecha_pago:%m/%d/%Y} · {pago}", 8)
    izquierda = _tabla("Ingresos", datos["ingresos"])
    derecha = _tabla("Retenciones y deducciones", datos["descuentos"])
    for tabla, x in ((izquierda, 0.4), (derecha, 4.4)):
        _, alto = tabla.wrapOn(h.c, 3.8 * inch, 2 * inch)
        px, py = h.xy(x, 0.75)
        tabla.drawOn(h.c, px, py - alto)
    y = 0.8 + 0.14 * (MAX_FILAS + 1) + 0.15
    t = datos["totales"]
    h.texto(0.4, y, f"Bruto {_dinero(resultado.bruto)} (año {_dinero(t['bruto'])})", 8)
    h.texto(3.0, y, f"Descuentos {_dinero(resultado.total_retenciones + resultado.total_deducciones)} "
                    f"(año {_dinero(t['descuentos'])})", 8)
    h.texto(8.1, y, f"NETO {_dinero(resultado.neto)}", 10, negrita=True, derecha=True)
    h.texto(8.1, y + 0.17, f"Neto del año {_dinero(t['bruto'] - t['descuentos'])}", 7, derecha=True)
    h.texto(0.4, y + 0.17, f"Horas trabajadas: {resultado.horas_trabajadas:,.2f} · Balance vacaciones: "
                           f"{datos['vacaciones']:,.2f} h · Enfermedad: {datos['enfermedad']:,.2f} h", 7)


def _datos_talonario(resultado):
    ytd = acumulados_por_concepto(resultado)
    lineas = [l for l in resultado.lineas.all() if l.monto]
    bruto = sum((v for (g, _), v in ytd.items() if g == "ingreso"), Decimal("0"))
    descuentos = sum((v for (g, _), v in ytd.items() if g in ("retencion", "deduccion")), Decimal("0"))
    return {
        "ingresos": _filas(lineas, ytd, ("ingreso",)),
        "descuentos": _filas(lineas, ytd, ("retencion", "deduccion")),
        "totales": {"bruto": bruto, "descuentos": descuentos},
        "vacaciones": saldo(resultado.empleado, "vacaciones"),
        "enfermedad": saldo(resultado.empleado, "enfermedad"),
    }


def _pagina(c, formato, resultado, cheque):
    s_cheque, s_talonarios = _secciones(formato)
    if cheque:
        _cheque(_Hoja(c, formato, s_cheque), formato, cheque, resultado)
        pago = f"Cheque núm. {cheque.numero}" + (f" · {formato.nombre_cuenta}" if formato.nombre_cuenta else "")
    else:
        _aviso_deposito(_Hoja(c, formato, s_cheque), resultado)
        pago = f"Depósito directo {resultado.empleado.cuenta_enmascarada}"
    datos = _datos_talonario(resultado)
    for seccion, rotulo in zip(s_talonarios, ("TALONARIO DEL EMPLEADO", "COPIA PARA EL PATRONO")):
        _talonario(_Hoja(c, formato, seccion), formato, resultado, datos, rotulo, pago)
    c.showPage()


def _documento(titulo):
    salida = io.BytesIO()
    c = canvas.Canvas(salida, pagesize=letter)
    c.setTitle(titulo)
    return salida, c


def generar_cheques(formato, cheques) -> bytes:
    salida, c = _documento("Cheques de nómina")
    for cheque in cheques:
        _pagina(c, formato, cheque.resultado, cheque)
    c.save()
    return salida.getvalue()


def generar_avisos(formato, resultados) -> bytes:
    salida, c = _documento("Avisos de depósito directo")
    for resultado in resultados:
        _pagina(c, formato, resultado, None)
    c.save()
    return salida.getvalue()


def generar_prueba(formato, compania) -> bytes:
    """Página de prueba: se imprime en papel blanco y se pone sobre una hoja de cheques contra la luz."""
    from types import SimpleNamespace
    from datetime import date

    salida, c = _documento("Prueba de alineación")
    s_cheque, _ = _secciones(formato)
    c.setDash(4, 3)
    c.setStrokeColor(colors.grey)
    for y in (ALTO_PAGINA - ALTO_SECCION, ALTO_PAGINA - 2 * ALTO_SECCION):
        c.line(0, y, 8.5 * inch, y)
    c.setDash()
    h = _Hoja(c, formato, s_cheque)
    empleado = SimpleNamespace(direccion_linea1="Calle Ejemplo 123", direccion_linea2="", ciudad="San Juan",
                               estado="PR", codigo_postal="00901")
    periodo = SimpleNamespace(compania=compania, fecha_inicio=date(2026, 1, 1), fecha_fin=date(2026, 1, 7))
    resultado = SimpleNamespace(empleado=empleado, periodo=periodo)
    cheque = SimpleNamespace(numero=formato.siguiente_numero, fecha=date.today(), beneficiario="NOMBRE DEL EMPLEADO",
                             monto=Decimal("1234.56"))
    _cheque(h, formato, cheque, resultado)
    c.setFillColor(colors.red)
    h.texto(4.25, 2.6, "PRUEBA DE ALINEACIÓN — NO NEGOCIABLE", 12, negrita=True, centro=True)
    c.setFillColor(colors.black)
    c.setFont("Helvetica", 8)
    c.drawString(0.5 * inch, 0.35 * inch, "Líneas punteadas = perforaciones a 3.5\" y 7\". Si el texto no cae en su "
                                          "sitio, ajuste las pulgadas en el formato de cheques y vuelva a imprimir.")
    c.showPage()
    c.save()
    return salida.getvalue()
