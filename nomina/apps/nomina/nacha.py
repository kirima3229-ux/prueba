"""
Archivo NACHA (ACH) de depósito directo de nómina: formato PPD, registros de 94 caracteres,
bloques de 10 registros.

Estructura: 1 (encabezado del archivo) · 5 (encabezado del lote) · 6 (una entrada por empleado)
· [6 débito de compensación si el banco pide archivo balanceado] · 8 (control del lote)
· 9 (control del archivo) · relleno de «9» hasta completar el bloque.
"""

import math
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

CREDITO = {"cheques": "22", "ahorros": "32"}
DEBITO = {"cheques": "27", "ahorros": "37"}


class ErrorNACHA(Exception):
    pass


def texto_ach(valor, largo) -> str:
    """Mayúsculas ASCII sin acentos, cortado o rellenado con espacios a la derecha."""
    plano = unicodedata.normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode("ascii")
    plano = "".join(c if 32 <= ord(c) < 127 else " " for c in plano).upper()
    return plano[:largo].ljust(largo)


def numero(valor, largo) -> str:
    texto = str(valor)
    if not texto.isdigit() or len(texto) > largo:
        raise ErrorNACHA(f"El valor «{valor}» no cabe en {largo} dígitos.")
    return texto.zfill(largo)


def centavos(monto: Decimal) -> int:
    return int((Decimal(monto) * 100).quantize(Decimal("1")))


def _diez(valor) -> str:
    """Campo de 10 posiciones: 9 dígitos van precedidos de un espacio (como un número de ruta)."""
    texto = str(valor or "").strip()
    if texto.isdigit() and len(texto) == 9:
        return " " + texto
    return texto_ach(texto, 10)


@dataclass
class Origen:
    """Datos de la compañía y su banco (ODFI)."""
    ruta_banco: str             # 9 dígitos del banco que envía (ODFI)
    nombre_banco: str
    origen_inmediato: str       # 10 caracteres (lo asigna el banco; a menudo «1» + EIN)
    identificacion_compania: str  # 10 caracteres (a menudo «1» + EIN)
    nombre_compania: str
    descripcion: str = "NOMINA"
    referencia: str = ""
    # Archivo balanceado: débito a la cuenta de la compañía por el total.
    balanceado: bool = False
    ruta_compania: str = ""
    cuenta_compania: str = ""
    tipo_cuenta_compania: str = "cheques"


@dataclass
class Pago:
    ruta: str
    cuenta: str
    tipo_cuenta: str   # cheques | ahorros
    monto: Decimal
    identificacion: str  # número de empleado
    nombre: str


def _validar(origen: Origen, pagos: list[Pago]):
    from apps.core.validadores import validar_ruta_bancaria

    from django.core.exceptions import ValidationError

    rutas = [("banco de la compañía", origen.ruta_banco)] + [(p.nombre, p.ruta) for p in pagos]
    if origen.balanceado:
        rutas.append(("cuenta de la compañía", origen.ruta_compania))
    for quien, ruta in rutas:
        try:
            validar_ruta_bancaria(ruta)
        except ValidationError:
            raise ErrorNACHA(f"Número de ruta inválido ({quien}): «{ruta}».")
    for p in pagos:
        if not p.cuenta:
            raise ErrorNACHA(f"{p.nombre}: no tiene número de cuenta.")
        if p.tipo_cuenta not in CREDITO:
            raise ErrorNACHA(f"{p.nombre}: tipo de cuenta desconocido.")
        if p.monto <= 0:
            raise ErrorNACHA(f"{p.nombre}: el monto debe ser mayor que cero.")
    if origen.balanceado and not origen.cuenta_compania:
        raise ErrorNACHA("El archivo balanceado necesita la cuenta de la compañía.")
    if not pagos:
        raise ErrorNACHA("No hay depósitos para el archivo.")


def generar(origen: Origen, pagos: list[Pago], fecha_efectiva: date, creado: datetime, lote: int = 1) -> str:
    _validar(origen, pagos)
    odfi = origen.ruta_banco[:8]
    registros = []
    registros.append(
        "1" + "01" + " " + origen.ruta_banco + _diez(origen.origen_inmediato)
        + creado.strftime("%y%m%d") + creado.strftime("%H%M") + "A" + "094" + "10" + "1"
        + texto_ach(origen.nombre_banco, 23) + texto_ach(origen.nombre_compania, 23) + texto_ach(origen.referencia, 8)
    )
    clase = "200" if origen.balanceado else "220"
    registros.append(
        "5" + clase + texto_ach(origen.nombre_compania, 16) + " " * 20 + _diez(origen.identificacion_compania)
        + "PPD" + texto_ach(origen.descripcion, 10) + fecha_efectiva.strftime("%y%m%d")
        + fecha_efectiva.strftime("%y%m%d") + "   " + "1" + odfi + numero(lote, 7)
    )
    secuencia = 0
    hash_entradas = 0
    total_credito = 0
    total_debito = 0

    def entrada(codigo, ruta, cuenta, monto_centavos, identificacion, nombre):
        nonlocal secuencia, hash_entradas
        secuencia += 1
        hash_entradas += int(ruta[:8])
        return ("6" + codigo + ruta[:8] + ruta[8] + texto_ach(cuenta, 17) + numero(monto_centavos, 10)
                + texto_ach(identificacion, 15) + texto_ach(nombre, 22) + "  " + "0" + odfi + numero(secuencia, 7))

    for p in pagos:
        c = centavos(p.monto)
        total_credito += c
        registros.append(entrada(CREDITO[p.tipo_cuenta], p.ruta, p.cuenta, c, p.identificacion, p.nombre))
    if origen.balanceado:
        total_debito = total_credito
        registros.append(entrada(DEBITO[origen.tipo_cuenta_compania], origen.ruta_compania, origen.cuenta_compania,
                                 total_debito, "NOMINA", origen.nombre_compania))
    hash_texto = str(hash_entradas)[-10:].zfill(10)
    registros.append(
        "8" + clase + numero(secuencia, 6) + hash_texto + numero(total_debito, 12) + numero(total_credito, 12)
        + _diez(origen.identificacion_compania) + " " * 19 + " " * 6 + odfi + numero(lote, 7)
    )
    total_registros = len(registros) + 1
    bloques = math.ceil(total_registros / 10)
    registros.append(
        "9" + numero(1, 6) + numero(bloques, 6) + numero(secuencia, 8) + hash_texto + numero(total_debito, 12)
        + numero(total_credito, 12) + " " * 39
    )
    registros += ["9" * 94] * (bloques * 10 - len(registros))
    for r in registros:
        if len(r) != 94:
            raise ErrorNACHA(f"Registro de largo {len(r)} (debe ser 94).")  # no debería ocurrir
    return "\r\n".join(registros) + "\r\n"
