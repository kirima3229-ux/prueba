"""Tabla genérica que se muestra en pantalla y se exporta a Excel o PDF con el mismo contenido."""

from dataclasses import dataclass, field

from django.http import HttpResponse

from . import hojas
from .pdf import tabla_pdf

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@dataclass
class Tabla:
    columnas: list  # [(título, tipo)] tipo: texto | corto | dinero | pct | horas | fecha | numero
    filas: list
    totales: list | None = None
    notas: list = field(default_factory=list)

    def para_pantalla(self):
        filas = [[(formato_celda(v, t), t) for v, (_, t) in zip(fila, self.columnas)] for fila in self.filas]
        totales = ([(formato_celda(v, t), t) for v, (_, t) in zip(self.totales, self.columnas)]
                   if self.totales else None)
        return filas, totales


def formato_celda(valor, tipo):
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
    if tipo == "numero":
        return f"{valor:,}"
    return str(valor)


def exportar(tabla: Tabla, formato: str, *, titulo, subtitulo="", compania=None, nombre_archivo="reporte",
             hoja=None):
    """HttpResponse con la tabla en Excel («xlsx») o PDF («pdf»)."""
    if formato == "xlsx":
        # Cada columna «%» lleva el nombre de la columna que tiene al lado.
        titulos = [c for c, _ in tabla.columnas]
        encabezados = [f"% {titulos[i - 1]}" if t == "%" else t for i, t in enumerate(titulos)]
        contenido = hojas.libro_xlsx((hoja or titulo)[:31], encabezados, tabla.filas, tabla.totales)
        respuesta = HttpResponse(contenido, content_type=XLSX)
        respuesta["Content-Disposition"] = f'attachment; filename="{nombre_archivo}.xlsx"'
        return respuesta

    def fmt(fila):
        return [formato_celda(v, t) for v, (_, t) in zip(fila, tabla.columnas)]

    contenido = tabla_pdf(
        titulo=titulo, subtitulo=subtitulo, compania=compania, encabezados=[c for c, _ in tabla.columnas],
        filas=[fmt(f) for f in tabla.filas], totales=fmt(tabla.totales) if tabla.totales else None,
        notas=tabla.notas, tipos=[t for _, t in tabla.columnas],
    )
    respuesta = HttpResponse(contenido, content_type="application/pdf")
    respuesta["Content-Disposition"] = f'inline; filename="{nombre_archivo}.pdf"'
    return respuesta
