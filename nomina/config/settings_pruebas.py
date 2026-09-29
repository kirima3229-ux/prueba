"""Configuración para pruebas automatizadas. Usa llaves ficticias."""

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "pruebas-no-usar-en-produccion")
# Llaves de prueba (32 bytes en base64). NUNCA usar fuera de pruebas.
os.environ.setdefault(
    "NOMINA_LLAVES_CIFRADO",
    "1:AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=,"
    "2:ICEiIyQlJicoKSorLC0uLzAxMjM0NTY3ODk6Ozw9Pj8=",
)
os.environ.setdefault("NOMINA_LLAVE_ACTIVA", "2")
os.environ.setdefault("NOMINA_LLAVE_INDICE", "QEFCQ0RFRkdISUpLTE1OT1BRUlNUVVZXWFlaW1xdXl8=")
os.environ.setdefault("NOMINA_LLAVE_RESPALDO", "YGFiY2RlZmdoaWprbG1ub3BxcnN0dXZ3eHl6e3x9fn8=")
os.environ.setdefault("NOMINA_DB_MOTOR", "sqlite")

from .settings import *  # noqa: E402,F403
