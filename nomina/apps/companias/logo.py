"""Validación y normalización del logo de la compañía."""

import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

TAMANO_MAXIMO = 2 * 1024 * 1024  # 2 MB
PIXELES_MAXIMOS = 25_000_000  # evita imágenes «bomba» que agotan la memoria al abrirlas
FORMATOS = {"PNG", "JPEG"}
LADO_MAXIMO = (1200, 600)


class ErrorLogo(Exception):
    pass


def procesar(archivo) -> tuple[bytes, int, int]:
    """Devuelve (PNG, ancho, alto). Acepta PNG o JPG; el resultado se genera de nuevo (sin metadatos)."""
    if archivo.size > TAMANO_MAXIMO:
        raise ErrorLogo("El logo no puede pasar de 2 MB.")
    datos = archivo.read()
    try:
        with Image.open(io.BytesIO(datos)) as imagen:
            if imagen.format not in FORMATOS:
                raise ErrorLogo("El logo debe ser una imagen PNG o JPG.")
            ancho, alto = imagen.size
            if ancho * alto > PIXELES_MAXIMOS:
                raise ErrorLogo("La imagen es demasiado grande (más de 25 megapíxeles).")
            imagen.load()
            imagen = imagen.convert("RGBA")
    except ErrorLogo:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise ErrorLogo("No se pudo leer la imagen. Use un archivo PNG o JPG.")
    if min(imagen.size) < 16:
        raise ErrorLogo("La imagen es demasiado pequeña.")
    imagen.thumbnail(LADO_MAXIMO)
    salida = io.BytesIO()
    imagen.save(salida, format="PNG", optimize=True)
    return salida.getvalue(), imagen.width, imagen.height


@dataclass
class LogoPDF:
    lector: object  # ImageReader, para canvas.drawImage
    datos: bytes  # PNG, para platypus.Image
    ancho: int
    alto: int


def para_pdf(compania) -> LogoPDF | None:
    """El logo listo para ReportLab, o None si la compañía no tiene."""
    from reportlab.lib.utils import ImageReader

    from .models import logo_de

    registro = logo_de(compania)
    if registro is None:
        return None
    datos = bytes(registro.imagen)
    return LogoPDF(ImageReader(io.BytesIO(datos)), datos, registro.ancho, registro.alto)


def escala(ancho, alto, max_ancho, max_alto):
    """Tamaño que cabe en el recuadro sin deformar la imagen."""
    factor = min(max_ancho / ancho, max_alto / alto)
    return ancho * factor, alto * factor
