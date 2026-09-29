from datetime import date

import pytest
from django.urls import reverse

from apps.empleados.models import Empleado

from .conftest import crear_empleado
from .test_roles import DATOS_EMPLEADO


@pytest.mark.django_db
def test_detalle_nunca_muestra_ssn_completo(cliente_preparador, compania):
    empleado = crear_empleado(compania, ssn="123456789")
    empleado.deposito_directo = True
    empleado.banco_ruta = "021502011"
    empleado.asignar_cuenta_bancaria("000111222333")
    empleado.save()
    for url in (
        reverse("empleados:detalle", args=[empleado.pk]),
        reverse("empleados:editar", args=[empleado.pk]),
        reverse("empleados:lista"),
    ):
        html = cliente_preparador.get(url).content.decode()
        assert "123456789" not in html and "123-45-6789" not in html
        assert "000111222333" not in html
    html = cliente_preparador.get(reverse("empleados:detalle", args=[empleado.pk])).content.decode()
    assert "XXX-XX-6789" in html
    assert "••••2333" in html


@pytest.mark.django_db
def test_ssn_duplicado_en_la_compania(cliente_preparador, compania):
    crear_empleado(compania, numero="1", ssn="234567890")
    respuesta = cliente_preparador.post(reverse("empleados:nuevo"), DATOS_EMPLEADO)
    assert respuesta.status_code == 200
    assert "Ya existe un empleado con este SSN" in respuesta.content.decode()


@pytest.mark.django_db
def test_mismo_ssn_en_otra_compania_es_permitido(compania, otra_compania):
    crear_empleado(compania, numero="1", ssn="234567890")
    crear_empleado(otra_compania, numero="1", ssn="234567890")
    assert Empleado.objects.count() == 2


@pytest.mark.django_db
def test_editar_sin_ssn_lo_conserva(cliente_preparador, compania):
    empleado = crear_empleado(compania, numero="200", ssn="234567890")
    datos = {**DATOS_EMPLEADO, "ssn_nuevo": "", "nombre": "Mariela"}
    assert cliente_preparador.post(reverse("empleados:editar", args=[empleado.pk]), datos).status_code == 302
    empleado.refresh_from_db()
    assert empleado.nombre == "Mariela"
    assert empleado.ssn.revelar() == "234567890"


@pytest.mark.parametrize(
    "fecha,esperado",
    [(date(2017, 1, 25), "anterior"), (date(2017, 1, 26), "ley4"), (date(2024, 1, 1), "ley4")],
)
def test_regimen_automatico_por_fecha(fecha, esperado):
    assert Empleado(fecha_empleo=fecha).regimen_efectivo == esperado


def test_regimen_manual_prevalece():
    empleado = Empleado(fecha_empleo=date(2020, 1, 1), regimen_laboral="anterior")
    assert empleado.regimen_efectivo == "anterior"
    assert empleado.regimen_es_manual


@pytest.mark.django_db
def test_terminar_y_reactivar(cliente_preparador, compania):
    empleado = crear_empleado(compania)
    respuesta = cliente_preparador.post(
        reverse("empleados:terminar", args=[empleado.pk]),
        {"fecha_terminacion": "2026-06-30", "razon_terminacion": "renuncia"},
    )
    assert respuesta.status_code == 302
    empleado.refresh_from_db()
    assert not empleado.activo and empleado.fecha_terminacion == date(2026, 6, 30)
    cliente_preparador.post(reverse("empleados:reactivar", args=[empleado.pk]))
    empleado.refresh_from_db()
    assert empleado.activo and empleado.fecha_terminacion is None


@pytest.mark.django_db
def test_busqueda_htmx(cliente_preparador, compania):
    crear_empleado(compania, numero="1", ssn="234567890", nombre="Carmen")
    crear_empleado(compania, numero="2", ssn="345678901", nombre="Pedro")
    respuesta = cliente_preparador.get(reverse("empleados:lista"), {"q": "Carm"}, HTTP_HX_REQUEST="true")
    html = respuesta.content.decode()
    assert "Carmen" in html and "Pedro" not in html
    assert "<html" not in html  # solo el fragmento de la tabla
    respuesta = cliente_preparador.get(reverse("empleados:lista"), {"q": "8901"}, HTTP_HX_REQUEST="true")
    assert "Pedro" in respuesta.content.decode()
