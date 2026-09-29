import pytest
from django.db import DatabaseError, connection, transaction
from django.urls import reverse

from apps.auditoria.models import Accion, ErrorInmutable, RegistroAuditoria
from apps.auditoria.servicios import HASH_INICIAL, registrar, verificar_cadena

from .conftest import crear_empleado


@pytest.mark.django_db
def test_cadena_de_hashes():
    primero = registrar(accion=Accion.LOGIN, descripcion="uno")
    segundo = registrar(accion=Accion.LOGOUT, descripcion="dos")
    assert primero.hash_anterior == HASH_INICIAL
    assert segundo.hash_anterior == primero.hash
    ok, total, problemas = verificar_cadena()
    assert ok and total == 2 and not problemas


@pytest.mark.django_db
def test_modelo_no_permite_modificar_ni_borrar():
    registro = registrar(accion=Accion.LOGIN)
    registro.descripcion = "alterado"
    with pytest.raises(ErrorInmutable):
        registro.save()
    with pytest.raises(ErrorInmutable):
        registro.delete()
    with pytest.raises(ErrorInmutable):
        RegistroAuditoria.objects.all().update(descripcion="x")
    with pytest.raises(ErrorInmutable):
        RegistroAuditoria.objects.all().delete()


@pytest.mark.django_db
def test_base_de_datos_rechaza_update_y_delete():
    registro = registrar(accion=Accion.LOGIN)
    tabla = RegistroAuditoria._meta.db_table
    for sql in (f"UPDATE {tabla} SET descripcion = 'x' WHERE id = %s", f"DELETE FROM {tabla} WHERE id = %s"):
        with pytest.raises(DatabaseError):
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(sql, [registro.pk])
    assert RegistroAuditoria.objects.filter(pk=registro.pk, descripcion="").exists()


@pytest.mark.django_db
def test_verificacion_detecta_alteracion():
    registrar(accion=Accion.LOGIN, descripcion="original")
    registrar(accion=Accion.LOGOUT)
    tabla = RegistroAuditoria._meta.db_table
    # Simula a alguien con acceso directo a la base que desactiva la protección.
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            cursor.execute(f"ALTER TABLE {tabla} DISABLE TRIGGER auditoria_sin_cambios")
        else:
            cursor.execute("DROP TRIGGER auditoria_sin_update")
        cursor.execute(f"UPDATE {tabla} SET descripcion = 'alterado' WHERE descripcion = 'original'")
    ok, _total, problemas = verificar_cadena()
    assert not ok
    assert any("alterado" in p for p in problemas)


@pytest.mark.django_db
def test_cambio_de_empleado_registrado_sin_datos_sensibles(cliente_preparador, compania, preparador):
    empleado = crear_empleado(compania, ssn="123456789")
    from tests.test_roles import DATOS_EMPLEADO

    datos = {**DATOS_EMPLEADO, "numero_empleado": "100", "nombre": "Juan Carlos", "ssn_nuevo": "456-78-9123",
             "apellido_paterno": "Del Pueblo", "fecha_empleo": "2020-05-01", "tarifa": "11.00"}
    respuesta = cliente_preparador.post(reverse("empleados:editar", args=[empleado.pk]), datos)
    assert respuesta.status_code == 302
    registro = RegistroAuditoria.objects.get(accion=Accion.EMPLEADO_MODIFICADO)
    assert registro.usuario == preparador
    assert registro.ip == "127.0.0.1"
    assert registro.compania_id == compania.pk
    assert registro.cambios["nombre"] == {"antes": "Juan", "despues": "Juan Carlos"}
    assert registro.cambios["tarifa"]["despues"] == "11.0000"
    assert registro.cambios["ssn"] == {"modificado": True, "sensible": True}
    texto = str(registro.cambios) + registro.descripcion
    for secreto in ("123456789", "456789123", "456-78-9123"):
        assert secreto not in texto
