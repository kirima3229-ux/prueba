import pytest
from django.urls import reverse

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.companias.middleware import CLAVE_SESION

from .conftest import crear_empleado

DATOS_EMPLEADO = {
    "numero_empleado": "200",
    "nombre": "María",
    "apellido_paterno": "Rivera",
    "ssn_nuevo": "234-56-7890",
    "fecha_empleo": "2019-03-01",
    "estado": "PR",
    "tipo_pago": "hora",
    "tarifa": "12.00",
    "r4_estado_civil": "soltero",
    "r4_exencion_personal": "completa",
    "r4_dependientes": "0",
    "r4_dependientes_custodia_compartida": "0",
    "r4_concesion_deducciones": "0",
    "r4_retencion_adicional": "0",
    "w4_estado_civil": "single",
    "w4_dependientes": "0",
    "w4_otros_ingresos": "0",
    "w4_deducciones": "0",
    "w4_retencion_adicional": "0",
    "banco_tipo_cuenta": "cheques",
}


@pytest.mark.django_db
class TestSoloLectura:
    def test_puede_ver_empleados(self, cliente_lectura, compania):
        crear_empleado(compania)
        assert cliente_lectura.get(reverse("empleados:lista")).status_code == 200

    def test_no_puede_crear_ni_editar(self, cliente_lectura, compania):
        empleado = crear_empleado(compania)
        assert cliente_lectura.get(reverse("empleados:nuevo")).status_code == 403
        assert cliente_lectura.post(reverse("empleados:nuevo"), DATOS_EMPLEADO).status_code == 403
        assert cliente_lectura.get(reverse("empleados:editar", args=[empleado.pk])).status_code == 403
        assert cliente_lectura.get(reverse("empleados:importar")).status_code == 403
        assert RegistroAuditoria.objects.filter(accion=Accion.ACCESO_DENEGADO).exists()

    def test_no_administra(self, cliente_lectura, compania):
        assert cliente_lectura.get(reverse("cuentas:usuarios")).status_code == 403
        assert cliente_lectura.get(reverse("auditoria:lista")).status_code == 403
        assert cliente_lectura.get(reverse("companias:editar", args=[compania.pk])).status_code == 403


@pytest.mark.django_db
class TestPreparador:
    def test_crea_empleado(self, cliente_preparador, compania):
        respuesta = cliente_preparador.post(reverse("empleados:nuevo"), DATOS_EMPLEADO)
        assert respuesta.status_code == 302, respuesta.context["form"].errors if respuesta.context else ""
        assert compania.empleados.filter(numero_empleado="200").exists()

    def test_no_administra_usuarios_ni_tasas(self, cliente_preparador, compania):
        assert cliente_preparador.get(reverse("cuentas:usuarios")).status_code == 403
        assert cliente_preparador.get(reverse("cuentas:usuario_nuevo")).status_code == 403
        assert cliente_preparador.get(reverse("auditoria:lista")).status_code == 403
        assert cliente_preparador.get(reverse("companias:nueva")).status_code == 403
        assert cliente_preparador.get(reverse("companias:tasas_nuevas", args=[compania.pk])).status_code == 403

    def test_no_ve_companias_no_asignadas(self, cliente_preparador, otra_compania):
        empleado_ajeno = crear_empleado(otra_compania, numero="999", ssn="345678901")
        assert cliente_preparador.get(reverse("companias:detalle", args=[otra_compania.pk])).status_code == 404
        assert cliente_preparador.get(reverse("empleados:detalle", args=[empleado_ajeno.pk])).status_code == 404
        assert cliente_preparador.get(reverse("empleados:editar", args=[empleado_ajeno.pk])).status_code == 404
        lista = cliente_preparador.get(reverse("companias:lista")).content.decode()
        assert "Farmacia Ajena" not in lista

    def test_no_puede_seleccionar_compania_ajena(self, cliente_preparador, compania, otra_compania):
        respuesta = cliente_preparador.post(reverse("companias:seleccionar"), {"compania": otra_compania.pk})
        assert respuesta.status_code == 404
        assert cliente_preparador.session.get(CLAVE_SESION) == compania.pk

    def test_sesion_manipulada_no_da_acceso(self, cliente_preparador, otra_compania):
        crear_empleado(otra_compania, numero="999", ssn="345678901")
        sesion = cliente_preparador.session
        sesion[CLAVE_SESION] = otra_compania.pk
        sesion.save()
        contenido = cliente_preparador.get(reverse("empleados:lista")).content.decode()
        assert "999" not in contenido


@pytest.mark.django_db
class TestAdministrador:
    def test_ve_todas_las_companias(self, cliente_admin, compania, otra_compania):
        contenido = cliente_admin.get(reverse("companias:lista")).content.decode()
        assert "Restaurante El Ejemplo" in contenido and "Farmacia Ajena" in contenido

    def test_crea_usuario_con_contrasena_temporal(self, cliente_admin, compania):
        respuesta = cliente_admin.post(
            reverse("cuentas:usuario_nuevo"),
            {
                "username": "nuevo",
                "first_name": "Ana",
                "last_name": "López",
                "email": "ana@example.com",
                "rol": "preparador",
                "companias": [compania.pk],
                "nueva1": "Temporal-Segura-2026",
                "nueva2": "Temporal-Segura-2026",
            },
        )
        assert respuesta.status_code == 302
        from apps.cuentas.models import Usuario

        nuevo = Usuario.objects.get(username="nuevo")
        assert nuevo.debe_cambiar_contrasena
        assert list(nuevo.companias.all()) == [compania]
        assert RegistroAuditoria.objects.filter(accion=Accion.USUARIO_CREADO).exists()

    def test_no_puede_quitarse_admin(self, cliente_admin, admin):
        respuesta = cliente_admin.post(
            reverse("cuentas:usuario_editar", args=[admin.pk]),
            {"username": "admin", "rol": "preparador", "is_active": "on"},
        )
        assert respuesta.status_code == 200
        admin.refresh_from_db()
        assert admin.es_admin

    def test_tasas_por_verificar_y_verificadas(self, cliente_admin, compania, admin):
        datos = {
            "anio": 2026,
            "suta_tasa": "2.4",
            "aportacion_especial_tasa": "1.0",
            "sinot_empleado_tasa": "0.3",
            "sinot_patrono_tasa": "0.3",
        }
        cliente_admin.post(reverse("companias:tasas_nuevas", args=[compania.pk]), datos)
        tasas = compania.tasas.get(anio=2026)
        assert tasas.estado == "por_verificar"
        cliente_admin.post(
            reverse("companias:tasas_editar", args=[compania.pk, tasas.pk]),
            {**datos, "marcar_verificado": "on"},
        )
        tasas.refresh_from_db()
        assert tasas.estado == "verificado" and tasas.verificado_por == admin
        # Cambiar una tasa sin confirmar la regresa a POR VERIFICAR.
        cliente_admin.post(
            reverse("companias:tasas_editar", args=[compania.pk, tasas.pk]), {**datos, "suta_tasa": "3.1"}
        )
        tasas.refresh_from_db()
        assert tasas.estado == "por_verificar"
        assert RegistroAuditoria.objects.filter(accion=Accion.TASAS_MODIFICADAS).count() == 3
