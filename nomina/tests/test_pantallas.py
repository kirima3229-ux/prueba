"""Cada pantalla carga sin errores para los roles que tienen acceso."""

import pytest
from django.urls import reverse

from apps.auditoria.servicios import Accion, registrar
from apps.companias.models import ClasificacionCFSE, Departamento, TasasCompania

from .conftest import crear_empleado


@pytest.fixture
def datos(compania, admin):
    depto = Departamento.objects.create(compania=compania, nombre="Cocina")
    cfse = ClasificacionCFSE.objects.create(compania=compania, codigo="9079", descripcion="Restaurantes")
    tasas = TasasCompania.objects.create(
        compania=compania, anio=2026, suta_tasa="2.4", aportacion_especial_tasa="1",
        sinot_empleado_tasa="0.3", sinot_patrono_tasa="0.3",
    )
    empleado = crear_empleado(compania, departamento=depto, clasificacion_cfse=cfse)
    from datetime import date

    from .test_servicios import crear_proveedor

    proveedor = crear_proveedor(compania, relevo="parcial", relevo_porcentaje="5.00", relevo_vigente_hasta=date(2020, 1, 1))
    entidad = crear_proveedor(compania, numero="P-2", tipo="ein", identificacion="661234567", tipo_persona="entidad", nombre="ACME LLC", apellido_paterno="")
    inactivo = crear_empleado(compania, numero="101", ssn="234567890", activo=False)
    from decimal import Decimal

    from apps.servicios import pagos

    pago, _ = pagos.registrar(proveedor=entidad, fecha=date.today(), monto=Decimal("1500"), usuario=admin, numero_cheque="1")
    anulado, _ = pagos.registrar(proveedor=entidad, fecha=date.today(), monto=Decimal("200"), usuario=admin, numero_cheque="2")
    anulado.estado = "anulado"
    anulado.save(update_fields=["estado"])
    from apps.servicios import depositos

    deposito = depositos.registrar(compania=compania, desde=date(2000, 1, 1), hasta=date.today(),
                                   fecha_deposito=date.today(), confirmacion="X", usuario=admin)
    registrar(accion=Accion.LOGIN, usuario=admin, descripcion="prueba", cambios={"campo": {"antes": 1, "despues": 2}})
    from apps.nomina import servicios as nomina

    periodo = nomina.crear_periodo(compania=compania, inicio=date(2026, 9, 7), fin=date(2026, 9, 13),
                                   fecha_pago=date(2026, 9, 18), usuario=admin)
    periodo.entradas.filter(empleado=empleado).update(horas_regulares=40)
    nomina.calcular_periodo(periodo, usuario=admin)
    return {"periodo": periodo, "compania": compania, "depto": depto, "cfse": cfse, "tasas": tasas, "empleado": empleado, "inactivo": inactivo, "proveedor": proveedor, "entidad": entidad, "pago": pago, "anulado": anulado, "deposito": deposito}


def _pantallas(d, admin):
    c, e = d["compania"], d["empleado"]
    return [
        reverse("inicio"),
        reverse("cuentas:cambiar_contrasena"),
        reverse("cuentas:configurar_2fa"),
        reverse("companias:lista"),
        reverse("companias:detalle", args=[c.pk]),
        reverse("companias:catalogo_nuevo", args=[c.pk, "departamentos"]),
        reverse("companias:catalogo_editar", args=[c.pk, "departamentos", d["depto"].pk]),
        reverse("companias:catalogo_nuevo", args=[c.pk, "cfse"]),
        reverse("companias:catalogo_editar", args=[c.pk, "cfse", d["cfse"].pk]),
        reverse("empleados:lista"),
        reverse("empleados:lista") + "?estado=todos&q=Juan",
        reverse("empleados:nuevo"),
        reverse("empleados:detalle", args=[e.pk]),
        reverse("empleados:detalle", args=[d["inactivo"].pk]),
        reverse("empleados:editar", args=[e.pk]),
        reverse("empleados:terminar", args=[e.pk]),
        reverse("empleados:importar"),
        reverse("servicios:lista"),
        reverse("servicios:lista") + "?estado=todos&q=Luis",
        reverse("servicios:nuevo"),
        reverse("servicios:detalle", args=[d["proveedor"].pk]),
        reverse("servicios:detalle", args=[d["entidad"].pk]),
        reverse("servicios:editar", args=[d["proveedor"].pk]),
        reverse("servicios:importar_proveedores"),
        reverse("servicios:pagos"),
        reverse("servicios:pagos") + "?estado=todos&anio=2026&proveedor=" + str(d["entidad"].pk),
        reverse("servicios:pago_nuevo"),
        reverse("servicios:pago_nuevo") + "?proveedor=" + str(d["entidad"].pk),
        reverse("servicios:pago_detalle", args=[d["pago"].pk]),
        reverse("servicios:pago_detalle", args=[d["anulado"].pk]),
        reverse("servicios:importar_pagos"),
        reverse("servicios:resumen"),
        reverse("servicios:trimestral"),
        reverse("servicios:trimestral") + "?anio=2026&trimestre=1",
        reverse("servicios:depositos"),
        reverse("servicios:deposito_nuevo"),
        reverse("servicios:deposito_nuevo") + "?desde=2026-01-01&hasta=2026-12-31",
        reverse("servicios:deposito_detalle", args=[d["deposito"].pk]),
        reverse("calculo:simulador"),
        reverse("calculo:simulador") + "?empleado=" + str(e.pk),
        reverse("calculo:mesada"),
        reverse("calculo:mesada") + "?empleado=" + str(e.pk),
        reverse("licencias:balances"),
        reverse("licencias:balances") + "?formato=xlsx",
        reverse("licencias:acumular"),
        reverse("licencias:acumular") + "?anio=2026&mes=9",
        reverse("licencias:empleado", args=[e.pk]),
        reverse("licencias:bono"),
        reverse("licencias:bono") + "?anio=2026",
        reverse("nomina:lista"),
        reverse("nomina:nuevo"),
        reverse("nomina:detalle", args=[d["periodo"].pk]),
        reverse("nomina:entrada", args=[d["periodo"].pk, d["periodo"].entradas.get(empleado=e).pk]),
        reverse("nomina:talonarios", args=[d["periodo"].pk]),
        reverse("nomina:registro", args=[d["periodo"].pk]),
        reverse("nomina:deducciones_empleado", args=[e.pk]),
        reverse("nomina:cheques", args=[d["periodo"].pk]),
        reverse("nomina:formato_cheque"),
        reverse("nomina:reportes"),
        reverse("planillas:inicio"),
        reverse("planillas:planilla", args=["941"]),
        reverse("planillas:planilla", args=["w2pr"]) + "?anio=2026",
        reverse("planillas:planilla", args=["cfse"]),
        reverse("nomina:deposito_directo", args=[d["periodo"].pk]),
        reverse("nomina:importar_horas", args=[d["periodo"].pk]),
        reverse("nomina:servicios", args=[d["periodo"].pk]),
        reverse("nomina:reportes") + "?reporte=costo&agrupar=departamento&rango=anio&anio=2026",
        reverse("nomina:reportes") + "?reporte=impuestos&rango=rango&desde=2026-01-01&hasta=2026-12-31",
        reverse("nomina:reportes") + "?reporte=empleados&rango=trimestre&anio=2026&trimestre=3&formato=pdf",
        reverse("nomina:prueba_alineacion"),
    ], [
        reverse("nomina:configuracion_nacha"),
        reverse("nomina:cuentas_contables"),
        reverse("parametros:inicio"),
        reverse("parametros:anio", args=[2026]),
        reverse("parametros:minimo_nuevo"),
        reverse("parametros:ingreso_nuevo"),
        reverse("parametros:deduccion_nuevo"),
        reverse("companias:tasa_cfse_nueva", args=[c.pk, d["cfse"].pk]),
        reverse("servicios:config_lista"),
        reverse("servicios:config_nueva"),
        reverse("cuentas:usuarios"),
        reverse("cuentas:usuario_nuevo"),
        reverse("cuentas:usuario_editar", args=[admin.pk]),
        reverse("cuentas:usuario_contrasena", args=[admin.pk]),
        reverse("companias:nueva"),
        reverse("companias:editar", args=[c.pk]),
        reverse("companias:tasas_nuevas", args=[c.pk]),
        reverse("companias:tasas_editar", args=[c.pk, d["tasas"].pk]),
        reverse("auditoria:lista"),
        reverse("auditoria:lista") + "?accion=login&desde=2020-01-01&hasta=2030-12-31&compania=" + str(c.pk),
    ]


@pytest.mark.django_db
def test_pantallas_admin(cliente_admin, admin, datos):
    comunes, solo_admin = _pantallas(datos, admin)
    for url in comunes + solo_admin:
        respuesta = cliente_admin.get(url)
        assert respuesta.status_code == 200, url
    respuesta = cliente_admin.post(reverse("auditoria:verificar"))
    assert "íntegra" in respuesta.content.decode()


@pytest.mark.django_db
def test_pantallas_preparador(cliente_preparador, admin, datos):
    comunes, solo_admin = _pantallas(datos, admin)
    for url in comunes:
        assert cliente_preparador.get(url).status_code == 200, url
    for url in solo_admin:
        assert cliente_preparador.get(url).status_code == 403, url
