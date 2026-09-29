import re

from django.core.exceptions import ValidationError


def solo_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def normalizar_ssn(valor: str) -> str:
    """Devuelve el SSN en 9 dígitos o lanza ValidationError."""
    texto = (valor or "").strip()
    if not re.fullmatch(r"\d{3}-?\d{2}-?\d{4}", texto):
        raise ValidationError("El SSN debe tener 9 dígitos (###-##-####).")
    digitos = solo_digitos(texto)
    area, grupo, serie = digitos[:3], digitos[3:5], digitos[5:]
    if area in ("000", "666") or area.startswith("9"):
        raise ValidationError("El SSN no es válido: el área (primeros 3 dígitos) no puede ser 000, 666 ni 9XX.")
    if grupo == "00":
        raise ValidationError("El SSN no es válido: el grupo (dígitos 4-5) no puede ser 00.")
    if serie == "0000":
        raise ValidationError("El SSN no es válido: la serie (últimos 4) no puede ser 0000.")
    return digitos


def formato_ssn_enmascarado(ultimos4: str) -> str:
    return f"XXX-XX-{ultimos4}" if ultimos4 else ""


def normalizar_ein(valor: str) -> str:
    texto = (valor or "").strip()
    if not re.fullmatch(r"\d{2}-?\d{7}", texto):
        raise ValidationError("El EIN debe tener 9 dígitos (##-#######).")
    return solo_digitos(texto)


def validar_ruta_bancaria(valor: str) -> str:
    """Número de ruta ABA de 9 dígitos con dígito verificador."""
    digitos = solo_digitos(valor)
    if len(digitos) != 9:
        raise ValidationError("El número de ruta debe tener 9 dígitos.")
    d = [int(c) for c in digitos]
    suma = 3 * (d[0] + d[3] + d[6]) + 7 * (d[1] + d[4] + d[7]) + (d[2] + d[5] + d[8])
    if suma % 10 != 0:
        raise ValidationError("El número de ruta no es válido (dígito verificador incorrecto).")
    return digitos


def validar_cuenta_bancaria(valor: str) -> str:
    texto = (valor or "").strip().replace(" ", "").replace("-", "")
    if not re.fullmatch(r"[0-9A-Za-z]{4,17}", texto):
        raise ValidationError("La cuenta bancaria debe tener entre 4 y 17 caracteres alfanuméricos.")
    return texto
