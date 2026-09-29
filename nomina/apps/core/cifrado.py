"""
Cifrado de campos sensibles con AES-256-GCM.

Formato guardado en la base de datos:  enc1:<id_llave>:<base64(nonce + texto_cifrado)>

- Cada valor usa un nonce aleatorio de 12 bytes (dos SSN iguales producen
  textos cifrados distintos).
- El "contexto" (app.modelo.campo) se usa como datos autenticados (AAD): un
  valor cifrado copiado a otra columna no se puede descifrar.
- Rotación: se añaden llaves nuevas a NOMINA_LLAVES_CIFRADO y se cambia
  NOMINA_LLAVE_ACTIVA; los valores viejos se siguen descifrando con su llave.
- Las llaves viven en variables de entorno, nunca en el código ni en la base
  de datos.
"""

import base64
import hashlib
import hmac
import os
from functools import lru_cache

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed
from django.dispatch import receiver

PREFIJO = "enc1"


class ErrorCifrado(Exception):
    pass


def _decodificar_llave(texto: str, nombre: str) -> bytes:
    try:
        llave = base64.b64decode(texto.strip(), validate=True)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{nombre}: la llave no es base64 válido.") from exc
    if len(llave) != 32:
        raise ImproperlyConfigured(f"{nombre}: la llave debe tener 32 bytes (AES-256).")
    return llave


@lru_cache(maxsize=1)
def _llaves() -> dict:
    llaves = {}
    for parte in settings.NOMINA_LLAVES_CIFRADO.split(","):
        parte = parte.strip()
        if not parte:
            continue
        if ":" not in parte:
            raise ImproperlyConfigured(
                "NOMINA_LLAVES_CIFRADO debe tener el formato id:llave_base64[,id:llave_base64]"
            )
        id_llave, texto = parte.split(":", 1)
        id_llave = id_llave.strip()
        if not id_llave.isalnum():
            raise ImproperlyConfigured("Los identificadores de llave deben ser alfanuméricos.")
        llaves[id_llave] = _decodificar_llave(texto, f"Llave {id_llave}")
    activa = str(settings.NOMINA_LLAVE_ACTIVA).strip()
    if activa not in llaves:
        raise ImproperlyConfigured("NOMINA_LLAVE_ACTIVA no está en NOMINA_LLAVES_CIFRADO.")
    return llaves


@lru_cache(maxsize=1)
def _llave_indice() -> bytes:
    return _decodificar_llave(settings.NOMINA_LLAVE_INDICE, "NOMINA_LLAVE_INDICE")


@receiver(setting_changed)
def _limpiar_cache(setting, **kwargs):
    if setting.startswith("NOMINA_LLAVE"):
        _llaves.cache_clear()
        _llave_indice.cache_clear()


def verificar_configuracion():
    """Falla temprano si las llaves están mal configuradas."""
    _llaves()
    _llave_indice()


def es_cifrado(valor) -> bool:
    return isinstance(valor, str) and valor.startswith(PREFIJO + ":")


def cifrar(texto: str, contexto: str) -> str:
    id_llave = str(settings.NOMINA_LLAVE_ACTIVA).strip()
    llave = _llaves()[id_llave]
    nonce = os.urandom(12)
    datos = AESGCM(llave).encrypt(nonce, texto.encode("utf-8"), contexto.encode("utf-8"))
    cuerpo = base64.urlsafe_b64encode(nonce + datos).decode("ascii")
    return f"{PREFIJO}:{id_llave}:{cuerpo}"


def descifrar(token: str, contexto: str) -> str:
    try:
        prefijo, id_llave, cuerpo = token.split(":", 2)
    except ValueError as exc:
        raise ErrorCifrado("Valor cifrado con formato inválido.") from exc
    if prefijo != PREFIJO:
        raise ErrorCifrado("Versión de cifrado desconocida.")
    llave = _llaves().get(id_llave)
    if llave is None:
        raise ErrorCifrado(f"No se encontró la llave '{id_llave}' para descifrar.")
    crudo = base64.urlsafe_b64decode(cuerpo.encode("ascii"))
    try:
        texto = AESGCM(llave).decrypt(crudo[:12], crudo[12:], contexto.encode("utf-8"))
    except InvalidTag as exc:
        raise ErrorCifrado("El valor cifrado fue alterado o la llave es incorrecta.") from exc
    return texto.decode("utf-8")


def id_llave_de(token: str) -> str:
    return token.split(":", 2)[1]


def indice_ciego(valor: str, contexto: str) -> str:
    """HMAC-SHA256 del valor: permite buscar y evitar duplicados sin descifrar."""
    mensaje = f"{contexto}:{valor}".encode("utf-8")
    return hmac.new(_llave_indice(), mensaje, hashlib.sha256).hexdigest()


def generar_llave() -> str:
    return base64.b64encode(os.urandom(32)).decode("ascii")
