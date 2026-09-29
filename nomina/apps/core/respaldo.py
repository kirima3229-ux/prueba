"""
Respaldos cifrados de la base de datos.

Formato del archivo (.respaldo):

    b"NOMRESP1" · huella de la llave (8 bytes) · prefijo de nonce (7 bytes)
    bloques: largo (4 bytes, big-endian) · AES-256-GCM(bloque)

Cada bloque se cifra con el nonce = prefijo · número de bloque (4 bytes) · 1 si es el último, 0 si no;
el encabezado va como datos autenticados. Así se detecta cualquier cambio, bloques reordenados o un archivo
cortado. La llave de respaldo (NOMINA_LLAVE_RESPALDO) es distinta de las llaves de los campos: dentro del
respaldo los SSN y las cuentas siguen cifrados con sus propias llaves.
"""

import base64
import hashlib
import os
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

MAGIA = b"NOMRESP1"
TAMANO_BLOQUE = 1024 * 1024
LARGO_ENCABEZADO = len(MAGIA) + 8 + 7


class ErrorRespaldo(Exception):
    pass


def huella(llave: bytes) -> bytes:
    return hashlib.sha256(b"nomina-respaldo:" + llave).digest()[:8]


def llaves_respaldo() -> list[bytes]:
    """La primera es la activa; las demás sirven para restaurar respaldos viejos."""
    texto = getattr(settings, "NOMINA_LLAVE_RESPALDO", "") or ""
    llaves = []
    for parte in (p.strip() for p in texto.split(",")):
        if not parte:
            continue
        try:
            llave = base64.b64decode(parte, validate=True)
        except ValueError as exc:
            raise ImproperlyConfigured("NOMINA_LLAVE_RESPALDO: la llave no es base64 válido.") from exc
        if len(llave) != 32:
            raise ImproperlyConfigured("NOMINA_LLAVE_RESPALDO: cada llave debe tener 32 bytes.")
        llaves.append(llave)
    if not llaves:
        raise ImproperlyConfigured("Falta NOMINA_LLAVE_RESPALDO (genere una con: python manage.py generar_llave).")
    return llaves


def _nonce(prefijo: bytes, numero: int, ultimo: bool) -> bytes:
    return prefijo + struct.pack(">IB", numero, 1 if ultimo else 0)


def cifrar(entrada, salida, llave: bytes) -> int:
    """Cifra el flujo `entrada` en `salida`. Devuelve los bytes de datos cifrados."""
    prefijo = os.urandom(7)
    encabezado = MAGIA + huella(llave) + prefijo
    salida.write(encabezado)
    aes = AESGCM(llave)
    total = 0
    numero = 0
    actual = entrada.read(TAMANO_BLOQUE)
    while True:
        siguiente = entrada.read(TAMANO_BLOQUE)
        ultimo = not siguiente
        cifrado = aes.encrypt(_nonce(prefijo, numero, ultimo), actual, encabezado)
        salida.write(struct.pack(">I", len(cifrado)))
        salida.write(cifrado)
        total += len(actual)
        if ultimo:
            return total
        numero += 1
        if numero >= 2**32:
            raise ErrorRespaldo("Respaldo demasiado grande.")
        actual = siguiente


def descifrar(entrada, salida, llaves: list[bytes]) -> int:
    """Descifra y verifica. `salida` puede ser None para sólo verificar. Devuelve los bytes de datos."""
    encabezado = entrada.read(LARGO_ENCABEZADO)
    if len(encabezado) != LARGO_ENCABEZADO or not encabezado.startswith(MAGIA):
        raise ErrorRespaldo("El archivo no es un respaldo del sistema de nómina.")
    marca = encabezado[len(MAGIA):len(MAGIA) + 8]
    prefijo = encabezado[len(MAGIA) + 8:]
    llave = next((l for l in llaves if huella(l) == marca), None)
    if llave is None:
        raise ErrorRespaldo("Ninguna de las llaves de respaldo configuradas abre este archivo.")
    aes = AESGCM(llave)
    total = 0
    numero = 0
    while True:
        largo_crudo = entrada.read(4)
        if len(largo_crudo) != 4:
            raise ErrorRespaldo("El respaldo está incompleto (el archivo se cortó).")
        (largo,) = struct.unpack(">I", largo_crudo)
        if largo > TAMANO_BLOQUE + 16:
            raise ErrorRespaldo("El respaldo está dañado.")
        cifrado = entrada.read(largo)
        if len(cifrado) != largo:
            raise ErrorRespaldo("El respaldo está incompleto (el archivo se cortó).")
        datos = None
        for ultimo in (False, True):
            try:
                datos = aes.decrypt(_nonce(prefijo, numero, ultimo), cifrado, encabezado)
            except InvalidTag:
                continue
            break
        if datos is None:
            raise ErrorRespaldo("El respaldo fue alterado o está dañado.")
        if salida is not None:
            salida.write(datos)
        total += len(datos)
        if ultimo:
            if entrada.read(1):
                raise ErrorRespaldo("El respaldo tiene datos de más después del final.")
            return total
        numero += 1
