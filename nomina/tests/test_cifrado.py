import pytest
from django.core.exceptions import FieldError
from django.db import connection

from apps.core import cifrado
from apps.core.campos import DatoSensible
from apps.empleados.models import Empleado

from .conftest import crear_empleado

LLAVES = (
    "1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=,"
    "2:ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8="
)


def test_cifrar_y_descifrar():
    token = cifrado.cifrar("123456789", "prueba.campo")
    assert token.startswith("enc1:2:")
    assert "123456789" not in token
    assert cifrado.descifrar(token, "prueba.campo") == "123456789"


def test_mismo_valor_produce_cifrados_distintos():
    assert cifrado.cifrar("123456789", "c") != cifrado.cifrar("123456789", "c")


def test_contexto_distinto_no_descifra():
    token = cifrado.cifrar("123456789", "empleados.empleado.ssn")
    with pytest.raises(cifrado.ErrorCifrado):
        cifrado.descifrar(token, "empleados.empleado.banco_cuenta")


def test_valor_alterado_no_descifra():
    token = cifrado.cifrar("123456789", "c")
    prefijo, llave, cuerpo = token.split(":")
    alterado = cuerpo[:-4] + ("AAAA" if not cuerpo.endswith("AAAA") else "BBBB")
    with pytest.raises(cifrado.ErrorCifrado):
        cifrado.descifrar(f"{prefijo}:{llave}:{alterado}", "c")


def test_rotacion_de_llaves(settings):
    settings.NOMINA_LLAVES_CIFRADO = LLAVES
    settings.NOMINA_LLAVE_ACTIVA = "1"
    viejo = cifrado.cifrar("secreto", "c")
    assert cifrado.id_llave_de(viejo) == "1"
    settings.NOMINA_LLAVE_ACTIVA = "2"
    nuevo = cifrado.cifrar("secreto", "c")
    assert cifrado.id_llave_de(nuevo) == "2"
    # El valor viejo se sigue leyendo con la llave 1.
    assert cifrado.descifrar(viejo, "c") == "secreto"


def test_llave_desconocida(settings):
    token = cifrado.cifrar("x", "c")
    settings.NOMINA_LLAVES_CIFRADO = "9:" + LLAVES.split(",")[0].split(":")[1]
    settings.NOMINA_LLAVE_ACTIVA = "9"
    with pytest.raises(cifrado.ErrorCifrado):
        cifrado.descifrar(token, "c")


def test_indice_ciego_determinista():
    assert cifrado.indice_ciego("123456789", "ssn") == cifrado.indice_ciego("123456789", "ssn")
    assert cifrado.indice_ciego("123456789", "ssn") != cifrado.indice_ciego("123456780", "ssn")
    assert "123456789" not in cifrado.indice_ciego("123456789", "ssn")


def test_dato_sensible_siempre_enmascarado():
    dato = DatoSensible("123456789")
    assert str(dato) == "••••6789"
    assert "12345" not in repr(dato)
    assert f"{dato}" == "••••6789"
    assert dato.revelar() == "123456789"


@pytest.mark.django_db
def test_ssn_se_guarda_cifrado_en_la_base(compania):
    empleado = crear_empleado(compania, ssn="123456789")
    empleado.asignar_cuenta_bancaria("000111222333")
    empleado.save()
    with connection.cursor() as cursor:
        cursor.execute("SELECT ssn, banco_cuenta FROM empleados_empleado WHERE id = %s", [empleado.pk])
        ssn_crudo, cuenta_cruda = cursor.fetchone()
    assert ssn_crudo.startswith("enc1:") and "123456789" not in ssn_crudo
    assert cuenta_cruda.startswith("enc1:") and "000111222333" not in cuenta_cruda

    recargado = Empleado.objects.get(pk=empleado.pk)
    assert isinstance(recargado.ssn, DatoSensible)
    assert recargado.ssn.revelar() == "123456789"
    assert recargado.ssn_enmascarado == "XXX-XX-6789"


@pytest.mark.django_db
def test_campo_cifrado_no_admite_busquedas(compania):
    with pytest.raises(FieldError):
        list(Empleado.objects.filter(ssn="123456789"))


@pytest.mark.django_db
def test_numeros_patronales_cifrados(compania):
    with connection.cursor() as cursor:
        cursor.execute("SELECT ein, cuenta_patronal_dtrh FROM companias_compania WHERE id = %s", [compania.pk])
        ein, dtrh = cursor.fetchone()
    assert ein.startswith("enc1:") and "660000001" not in ein
    assert dtrh.startswith("enc1:") and "1234567890" not in dtrh
    assert compania.ein_enmascarado == "XX-XXX0001"
