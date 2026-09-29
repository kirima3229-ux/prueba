"""
Copias del W-2 federal para el empleado (B, C y 2) en una hoja carta, como formulario sustituto.

La copia A (para el SSA) no sale de aquí: se radica en Business Services Online del SSA (W-2 Online o archivo
EFW2). En las copias del empleado el SSN va truncado (permitido desde los reglamentos del IRS de 2017).
"""

import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

COPIAS = [
    ("Copy B—To Be Filed With Employee's FEDERAL Tax Return."),
    ("Copy C—For EMPLOYEE'S RECORDS."),
    ("Copy 2—To Be Filed With Employee's State, City, or Local Income Tax Return."),
]
ALTO = 3.55 * inch
ANCHO = 7.7 * inch
X0 = 0.4 * inch


def _dinero(valor):
    return f"{valor:,.2f}" if valor else ""


class _Formulario:
    def __init__(self, c, arriba):
        self.c = c
        self.arriba = arriba

    def celda(self, x, y, w, h, etiqueta, valor="", tamano=8, derecha=False, lineas=None):
        """x, y, w, h en pulgadas desde la esquina superior izquierda del formulario."""
        c = self.c
        px, py = X0 + x * inch, self.arriba - (y + h) * inch
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.5)
        c.rect(px, py, w * inch, h * inch)
        c.setFont("Helvetica", 5.5)
        c.drawString(px + 2, py + h * inch - 7, etiqueta)
        c.setFont("Helvetica", tamano)
        for i, linea in enumerate([l for l in (lineas or [valor]) if l]):
            base = py + h * inch - 17 - i * (tamano + 1.5)
            if derecha:
                c.drawRightString(px + w * inch - 4, base, linea)
            else:
                c.drawString(px + 4, base, linea)


def _copia(c, arriba, d, compania, anio, rotulo):
    f = _Formulario(c, arriba)
    emp = d.empleado
    ein = compania.ein.revelar() if hasattr(compania.ein, "revelar") else str(compania.ein or "")
    ein = f"{ein[:2]}-{ein[2:]}" if len(ein) == 9 else ein
    ciudad = " ".join(p for p in [compania.ciudad, compania.estado, compania.codigo_postal] if p)
    ciudad_emp = " ".join(p for p in [emp.ciudad, emp.estado, emp.codigo_postal] if p)
    izquierda = 3.85
    derecha = ANCHO / inch - izquierda
    medio = derecha / 2
    # Columna izquierda
    f.celda(0, 0, izquierda, 0.32, "a  Employee's social security number", f"XXX-XX-{emp.ssn_ultimos4}")
    f.celda(0, 0.32, izquierda, 0.32, "b  Employer identification number (EIN)", ein)
    f.celda(0, 0.64, izquierda, 0.78, "c  Employer's name, address, and ZIP code",
            lineas=[compania.nombre, compania.direccion_linea1, compania.direccion_linea2, ciudad])
    f.celda(0, 1.42, izquierda, 0.28, "d  Control number", str(emp.numero_empleado))
    apellidos = " ".join(p for p in [emp.apellido_paterno, emp.apellido_materno] if p)
    f.celda(0, 1.70, izquierda, 0.36, "e  Employee's first name and initial      Last name", f"{emp.nombre}   {apellidos}")
    f.celda(0, 2.06, izquierda, 0.66, "f  Employee's address and ZIP code",
            lineas=[emp.direccion_linea1, emp.direccion_linea2, ciudad_emp])
    # Columna derecha: casillas 1–14
    x = izquierda
    filas = [
        (("1  Wages, tips, other compensation", d.c1_salarios), ("2  Federal income tax withheld", d.c2_retencion_federal)),
        (("3  Social security wages", d.c3_salarios_ss), ("4  Social security tax withheld", d.c4_ss_retenido)),
        (("5  Medicare wages and tips", d.c5_salarios_medicare), ("6  Medicare tax withheld", d.c6_medicare_retenido)),
        (("7  Social security tips", d.c7_propinas_ss), ("8  Allocated tips", None)),
        (("9", None), ("10  Dependent care benefits", None)),
    ]
    y = 0
    for (et1, v1), (et2, v2) in filas:
        f.celda(x, y, medio, 0.32, et1, _dinero(v1) if v1 is not None else "", derecha=True)
        f.celda(x + medio, y, medio, 0.32, et2, _dinero(v2) if v2 is not None else "", derecha=True)
        y += 0.32
    codigos = list(d.c12.items())[:4]
    f.celda(x, y, medio, 0.32, "11  Nonqualified plans")
    f.celda(x, y + 0.32, medio, 0.42, "13  Retirement plan", "X" if d.c13_plan_retiro else "")
    f.celda(x, y + 0.74, medio, 0.38, "14  Other",
            lineas=[f"{k} {v:,.2f}" for k, v in list(d.c14.items())[:2]], tamano=7)
    for i, letra in enumerate("abcd"):
        codigo, monto = codigos[i] if i < len(codigos) else ("", None)
        f.celda(x + medio, y + i * 0.28, medio, 0.28, f"12{letra}  Code  {codigo}", _dinero(monto), derecha=True)
    # Fila inferior: estado y local
    y = 2.72
    anchos = [(1.7, "15  State   Employer's state ID number", f"PR   {ein}"),
              (1.3, "16  State wages, tips, etc.", _dinero(d.c16_salarios_estatales)),
              (1.0, "17  State income tax", _dinero(d.c17_retencion_estatal)),
              (1.3, "18  Local wages, tips, etc.", ""), (1.0, "19  Local income tax", ""),
              (ANCHO / inch - 6.3, "20  Locality name", "")]
    xx = 0
    for w, etiqueta, valor in anchos:
        f.celda(xx, y, w, 0.34, etiqueta, valor, derecha=etiqueta[:2] in ("16", "17"))
        xx += w
    c.setFont("Helvetica-Bold", 10)
    c.drawString(X0, arriba - 3.25 * inch, f"Form W-2  Wage and Tax Statement  {anio}")
    c.setFont("Helvetica", 6)
    c.drawRightString(X0 + ANCHO, arriba - 3.22 * inch, rotulo)
    c.drawRightString(X0 + ANCHO, arriba - 3.32 * inch, "Department of the Treasury—Internal Revenue Service")


def generar(datos, compania, anio, comprimir=True) -> bytes:
    salida = io.BytesIO()
    c = canvas.Canvas(salida, pagesize=letter, pageCompression=1 if comprimir else 0)
    c.setTitle(f"W-2 {anio}")
    for d in datos:
        for i, rotulo in enumerate(COPIAS):
            _copia(c, letter[1] - 0.3 * inch - i * ALTO, d, compania, anio, rotulo)
        c.showPage()
    c.save()
    return salida.getvalue()
