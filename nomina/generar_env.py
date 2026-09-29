#!/usr/bin/env python3
"""
Crea el archivo .env con llaves nuevas y aleatorias.

    python generar_env.py            # desarrollo con SQLite
    python generar_env.py --postgres # desarrollo/producción con PostgreSQL

No sobrescribe un .env existente. GUARDE UNA COPIA DE LAS LLAVES FUERA DEL
SERVIDOR: si se pierde NOMINA_LLAVES_CIFRADO, los SSN y cuentas bancarias
cifrados no se pueden recuperar.
"""

import base64
import secrets
import sys
from pathlib import Path

RUTA = Path(__file__).resolve().parent / ".env"


def llave():
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def main():
    if RUTA.exists():
        sys.exit(f"Ya existe {RUTA}. No se sobrescribe (contiene las llaves de cifrado).")
    postgres = "--postgres" in sys.argv
    lineas = [
        "# Generado por generar_env.py — NO subir a git. Guardar copia de las llaves en lugar seguro.",
        "NOMINA_ENTORNO=desarrollo",
        "DJANGO_DEBUG=1",
        f"DJANGO_SECRET_KEY={secrets.token_urlsafe(50)}",
        "DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1",
        f"NOMINA_LLAVES_CIFRADO=1:{llave()}",
        "NOMINA_LLAVE_ACTIVA=1",
        f"NOMINA_LLAVE_INDICE={llave()}",
    ]
    if postgres:
        lineas += [
            "NOMINA_DB_MOTOR=postgres",
            "POSTGRES_DB=nomina",
            "POSTGRES_USER=nomina",
            f"POSTGRES_PASSWORD={secrets.token_urlsafe(24)}",
            "POSTGRES_HOST=localhost",
            "POSTGRES_PORT=5432",
        ]
    else:
        lineas.append("NOMINA_DB_MOTOR=sqlite")
    RUTA.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    RUTA.chmod(0o600)
    print(f"Creado {RUTA}")
    print("IMPORTANTE: guarde una copia de NOMINA_LLAVES_CIFRADO y NOMINA_LLAVE_INDICE fuera del servidor.")


if __name__ == "__main__":
    main()
