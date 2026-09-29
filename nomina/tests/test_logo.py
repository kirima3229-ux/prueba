import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.companias import logo
from apps.companias.models import LogoCompania, logo_de
from apps.nomina import cheques, pdf_cheques, servicios, talonario

from .test_cheques import _res, nomina_cerrada  # noqa: F401
from .test_nomina import compania_lista  # noqa: F401


def imagen(formato="PNG", tamano=(400, 150), nombre=None, color=(15, 76, 129)):
    salida = io.BytesIO()
    Image.new("RGB", tamano, color).save(salida, format=formato)
    return SimpleUploadedFile(nombre or f"logo.{formato.lower()}", salida.getvalue())


def test_procesar_png_y_jpg():
    datos, ancho, alto = logo.procesar(imagen())
    assert datos.startswith(b"\x89PNG") and (ancho, alto) == (400, 150)
    datos, *_ = logo.procesar(imagen("JPEG"))
    assert datos.startswith(b"\x89PNG")  # siempre se guarda como PNG nuevo


def test_reduce_imagenes_grandes():
    _, ancho, alto = logo.procesar(imagen(tamano=(3000, 1000)))
    assert (ancho, alto) == (1200, 400)


@pytest.mark.parametrize("archivo,mensaje", [
    (lambda: imagen("GIF"), "PNG o JPG"),
    (lambda: SimpleUploadedFile("logo.png", b"<svg onload=alert(1)></svg>"), "No se pudo leer"),
    (lambda: SimpleUploadedFile("logo.png", b"\x89PNG" + b"0" * 100), "No se pudo leer"),
    (lambda: imagen(tamano=(8, 8)), "pequeña"),
    (lambda: SimpleUploadedFile("logo.png", b"0" * (2 * 1024 * 1024 + 1)), "2 MB"),
])
def test_rechaza(archivo, mensaje):
    with pytest.raises(logo.ErrorLogo, match=mensaje):
        logo.procesar(archivo())


@pytest.mark.django_db
def test_subir_ver_quitar_y_permisos(cliente_admin, cliente_preparador, cliente_lectura, compania, otra_compania):
    subir = reverse("companias:logo_subir", args=[compania.pk])
    assert cliente_preparador.post(subir, {"logo": imagen()}).status_code == 403
    respuesta = cliente_admin.post(subir, {"logo": imagen()})
    assert respuesta.status_code == 302 and logo_de(compania) is not None
    assert RegistroAuditoria.objects.filter(accion=Accion.LOGO_COMPANIA, descripcion__startswith="Logo añadido").exists()
    ver = reverse("companias:logo", args=[compania.pk])
    img = cliente_lectura.get(ver)
    assert img["Content-Type"] == "image/png" and bytes(img.content).startswith(b"\x89PNG")
    assert "Logo para talonarios" in cliente_lectura.get(reverse("companias:detalle", args=[compania.pk])).content.decode()
    # Otra compañía: no se ve.
    assert cliente_lectura.get(reverse("companias:logo", args=[otra_compania.pk])).status_code == 404
    # Archivo inválido: no cambia el logo existente.
    antes = bytes(logo_de(compania).imagen)
    cliente_admin.post(subir, {"logo": SimpleUploadedFile("x.png", b"no es imagen")})
    assert bytes(logo_de(compania).imagen) == antes
    cliente_admin.post(subir, {"logo": imagen(color=(200, 0, 0))})
    assert LogoCompania.objects.count() == 1 and bytes(logo_de(compania).imagen) != antes
    cliente_admin.post(reverse("companias:logo_borrar", args=[compania.pk]))
    assert logo_de(compania) is None
    assert cliente_lectura.get(ver).status_code == 404


def _tiene_imagen(pdf: bytes) -> bool:
    return b"/Subtype /Image" in pdf


@pytest.mark.django_db
def test_logo_en_los_pdf(nomina_cerrada, preparador):  # noqa: F811
    p = nomina_cerrada
    resultados = list(p.resultados.all())
    formato = cheques.formato_de(p.compania)
    assert not _tiene_imagen(talonario.generar_pdf(resultados))
    datos, ancho, alto = logo.procesar(imagen())
    LogoCompania.objects.create(compania=p.compania, imagen=datos, ancho=ancho, alto=alto)
    assert _tiene_imagen(talonario.generar_pdf(resultados))
    emitidos = cheques.emitir(p, [_res(p, "Ana")], 1, preparador)
    assert _tiene_imagen(pdf_cheques.generar_cheques(formato, emitidos))
    assert _tiene_imagen(pdf_cheques.generar_avisos(formato, [_res(p, "Carla")]))
    formato.imprimir_encabezado = True
    assert _tiene_imagen(pdf_cheques.generar_prueba(formato, p.compania))
