import pytest
from django.core.exceptions import ValidationError

from apps.core.validadores import normalizar_ein, normalizar_ssn, validar_ruta_bancaria


@pytest.mark.parametrize("valor", ["123-45-6789", "123456789", " 123-45-6789 "])
def test_ssn_valido(valor):
    assert normalizar_ssn(valor) == "123456789"


@pytest.mark.parametrize(
    "valor",
    ["", "12345678", "1234567890", "000-12-3456", "666-12-3456", "900-12-3456", "123-00-4567", "123-45-0000", "abc-de-fghi"],
)
def test_ssn_invalido(valor):
    with pytest.raises(ValidationError):
        normalizar_ssn(valor)


def test_ein():
    assert normalizar_ein("66-0123456") == "660123456"
    with pytest.raises(ValidationError):
        normalizar_ein("66-012345")


def test_ruta_bancaria():
    assert validar_ruta_bancaria("021502011") == "021502011"  # Banco Popular de PR
    with pytest.raises(ValidationError):
        validar_ruta_bancaria("021502012")
    with pytest.raises(ValidationError):
        validar_ruta_bancaria("12345")
