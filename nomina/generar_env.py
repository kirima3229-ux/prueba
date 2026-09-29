#!/usr/bin/env python3
"""
Crea el archivo .env con llaves nuevas y aleatorias.

    python generar_env.py            # desarrollo con SQLite
    python generar_env.py --postgres # desarrollo/producción con PostgreSQL
    python generar_env.py --docker --dominio nomina.midominio.com   # producción con docker compose

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
    docker = "--docker" in sys.argv
    postgres = "--postgres" in sys.argv or docker
    dominio = ""
    if docker:
        if "--dominio" not in sys.argv or sys.argv.index("--dominio") + 1 >= len(sys.argv):
            sys.exit("Indique el dominio: python generar_env.py --docker --dominio nomina.midominio.com")
        dominio = sys.argv[sys.argv.index("--dominio") + 1].strip().lower()
    lineas = [
        "# Generado por generar_env.py — NO subir a git. Guardar copia de las llaves en lugar seguro.",
        f"NOMINA_ENTORNO={'produccion' if docker else 'desarrollo'}",
        f"DJANGO_DEBUG={'0' if docker else '1'}",
        f"DJANGO_SECRET_KEY={secrets.token_urlsafe(50)}",
        f"DJANGO_ALLOWED_HOSTS={dominio + ',localhost' if docker else 'localhost,127.0.0.1'}",
        f"NOMINA_LLAVES_CIFRADO=1:{llave()}",
        "NOMINA_LLAVE_ACTIVA=1",
        f"NOMINA_LLAVE_INDICE={llave()}",
        f"NOMINA_LLAVE_RESPALDO={llave()}",
    ]
    if postgres:
        lineas += [
            "NOMINA_DB_MOTOR=postgres",
            "POSTGRES_DB=nomina",
            "POSTGRES_USER=nomina",
            f"POSTGRES_PASSWORD={secrets.token_urlsafe(24)}",
            f"POSTGRES_HOST={'db' if docker else 'localhost'}",
            "POSTGRES_PORT=5432",
        ]
    if docker:
        lineas += [
            f"NOMINA_DOMINIO={dominio}",
            f"DJANGO_CSRF_TRUSTED_ORIGINS=https://{dominio}",
            "NOMINA_PROXIES_CONFIABLES=1",
            "NOMINA_HORA_RESPALDO=2",
            "NOMINA_DIAS_RESPALDO=35",
        ]
    else:
        lineas.append("NOMINA_DB_MOTOR=sqlite")
    RUTA.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    RUTA.chmod(0o600)
    print(f"Creado {RUTA}")
    print("IMPORTANTE: guarde una copia de NOMINA_LLAVES_CIFRADO, NOMINA_LLAVE_INDICE y NOMINA_LLAVE_RESPALDO "
          "fuera del servidor y lejos de los respaldos.")


if __name__ == "__main__":
    main()
