from datetime import date, timedelta

import pytest
from django.db import connection
from django.urls import reverse

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.servicios.models import ProveedorServicios

BASE = {
    "numero": "P-1",
    "tipo_persona": "individuo",
    "nombre": "Luis",
    "apellido_paterno": "Méndez",
    "tipo_identificacion": "ssn",
    "identificacion_nueva": "123-45-6789",
    "estado": "PR",
    "descripcion_servicio": "Contabilidad",
    "relevo": "ninguno",
    "banco_tipo_cuenta": "cheques",
}


def crear_proveedor(compania, numero="P-1", tipo="ssn", identificacion="123456789", **extra):
    datos = dict(compania=compania, numero=numero, nombre="Luis", apellido_paterno="Méndez")
    datos.update(extra)
    proveedor = ProveedorServicios(**datos)
    proveedor.asignar_identificacion(tipo, identificacion)
    proveedor.save()
    return proveedor


@pytest.mark.django_db
def test_crear_individuo_con_ssn_cifrado(cliente_preparador, compania):
    respuesta = cliente_preparador.post(reverse("servicios:nuevo"), BASE)
    assert respuesta.status_code == 302
    proveedor = ProveedorServicios.objects.get(numero="P-1")
    assert proveedor.identificacion.revelar() == "123456789"
    assert proveedor.identificacion_enmascarada == "XXX-XX-6789"
    with connection.cursor() as cursor:
        cursor.execute("SELECT identificacion FROM servicios_proveedorservicios WHERE id = %s", [proveedor.pk])
        crudo = cursor.fetchone()[0]
    assert crudo.startswith("enc1:") and "123456789" not in crudo
    html = cliente_preparador.get(reverse("servicios:detalle", args=[proveedor.pk])).content.decode()
    assert "123456789" not in html and "123-45-6789" not in html
    assert "XXX-XX-6789" in html
    assert RegistroAuditoria.objects.filter(accion=Accion.PROVEEDOR_CREADO).exists()


@pytest.mark.django_db
def test_crear_entidad_con_ein(cliente_preparador, compania):
    datos = {**BASE, "tipo_persona": "entidad", "nombre": "Servicios Técnicos del Caribe LLC",
             "apellido_paterno": "", "tipo_identificacion": "ein", "identificacion_nueva": "66-1234567"}
    assert cliente_preparador.post(reverse("servicios:nuevo"), datos).status_code == 302
    proveedor = ProveedorServicios.objects.get()
    assert proveedor.identificacion_enmascarada == "XX-XXX4567"
    assert proveedor.nombre_mostrar == "Servicios Técnicos del Caribe LLC"


@pytest.mark.django_db
def test_validaciones(cliente_preparador, compania):
    url = reverse("servicios:nuevo")
    # EIN con formato de SSN no es válido y viceversa.
    r = cliente_preparador.post(url, {**BASE, "tipo_identificacion": "ein", "identificacion_nueva": "123-45-6789"})
    assert "EIN debe tener 9 dígitos" in r.content.decode()
    # Individuo sin apellido.
    r = cliente_preparador.post(url, {**BASE, "apellido_paterno": ""})
    assert "Requerido para individuos" in r.content.decode()
    # Relevo parcial exige porcentaje y vigencia.
    r = cliente_preparador.post(url, {**BASE, "relevo": "parcial"})
    contenido = r.content.decode()
    assert "Indique el porcentaje" in contenido and "Indique hasta cuándo" in contenido
    assert ProveedorServicios.objects.count() == 0


@pytest.mark.django_db
def test_identificacion_duplicada(cliente_preparador, compania):
    crear_proveedor(compania)
    r = cliente_preparador.post(reverse("servicios:nuevo"), {**BASE, "numero": "P-2"})
    assert "Ya existe un proveedor con esta identificación" in r.content.decode()


@pytest.mark.django_db
def test_relevo_vencido(compania):
    vigente = crear_proveedor(compania, relevo="total", relevo_vigente_hasta=date.today() + timedelta(days=30))
    vencido = crear_proveedor(
        compania, numero="P-2", identificacion="234567890",
        relevo="parcial", relevo_porcentaje="5.00", relevo_vigente_hasta=date.today() - timedelta(days=1),
    )
    sin_relevo = crear_proveedor(compania, numero="P-3", identificacion="345678901")
    assert vigente.relevo_vigente() and not vigente.relevo_vencido
    assert not vencido.relevo_vigente() and vencido.relevo_vencido
    assert not sin_relevo.relevo_vigente() and not sin_relevo.relevo_vencido


@pytest.mark.django_db
def test_relevo_vencido_aparece_en_inicio(cliente_preparador, compania):
    crear_proveedor(compania, relevo="total", relevo_vigente_hasta=date.today() - timedelta(days=1))
    assert "Certificados de relevo vencidos" in cliente_preparador.get(reverse("inicio")).content.decode()


@pytest.mark.django_db
def test_editar_registra_cambios_sin_identificacion(cliente_preparador, compania):
    proveedor = crear_proveedor(compania)
    datos = {**BASE, "identificacion_nueva": "234-56-7890", "descripcion_servicio": "Auditoría"}
    assert cliente_preparador.post(reverse("servicios:editar", args=[proveedor.pk]), datos).status_code == 302
    registro = RegistroAuditoria.objects.get(accion=Accion.PROVEEDOR_MODIFICADO)
    assert registro.cambios["identificacion"] == {"modificado": True, "sensible": True}
    assert registro.cambios["descripcion_servicio"] == {"antes": "", "despues": "Auditoría"}
    assert "234567890" not in str(registro.cambios) and "123456789" not in str(registro.cambios)


@pytest.mark.django_db
def test_desactivar_y_reactivar(cliente_preparador, compania):
    proveedor = crear_proveedor(compania)
    cliente_preparador.post(reverse("servicios:cambiar_estado", args=[proveedor.pk]))
    proveedor.refresh_from_db()
    assert not proveedor.activo
    cliente_preparador.post(reverse("servicios:cambiar_estado", args=[proveedor.pk]))
    proveedor.refresh_from_db()
    assert proveedor.activo


@pytest.mark.django_db
def test_permisos(cliente_lectura, cliente_preparador, compania, otra_compania):
    propio = crear_proveedor(compania)
    ajeno = crear_proveedor(otra_compania, numero="X-1")
    # Solo lectura: ve pero no crea ni edita.
    assert cliente_lectura.get(reverse("servicios:lista")).status_code == 200
    assert cliente_lectura.get(reverse("servicios:detalle", args=[propio.pk])).status_code == 200
    assert cliente_lectura.get(reverse("servicios:nuevo")).status_code == 403
    assert cliente_lectura.get(reverse("servicios:editar", args=[propio.pk])).status_code == 403
    assert cliente_lectura.post(reverse("servicios:cambiar_estado", args=[propio.pk])).status_code == 403
    # Preparador: no ve proveedores de compañías no asignadas.
    assert cliente_preparador.get(reverse("servicios:detalle", args=[ajeno.pk])).status_code == 404
    assert cliente_preparador.get(reverse("servicios:editar", args=[ajeno.pk])).status_code == 404


@pytest.mark.django_db
def test_busqueda(cliente_preparador, compania):
    crear_proveedor(compania, descripcion_servicio="Plomería")
    crear_proveedor(compania, numero="P-2", identificacion="234567890", nombre="Rosa", descripcion_servicio="Limpieza")
    html = cliente_preparador.get(reverse("servicios:lista"), {"q": "plom"}, HTTP_HX_REQUEST="true").content.decode()
    assert "Luis" in html and "Rosa" not in html
