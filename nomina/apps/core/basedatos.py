"""Volcado y carga de la base de datos para los respaldos (PostgreSQL con pg_dump/pg_restore; SQLite en desarrollo)."""

import os
import shutil
import sqlite3
import subprocess  # nosec B404 — sólo pg_dump/pg_restore con argumentos en lista, sin shell
import tempfile
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.db import connection


class ErrorBaseDatos(Exception):
    pass


def motor() -> str:
    return connection.vendor  # "postgresql" | "sqlite"


def _programa(nombre: str) -> str:
    carpeta = os.environ.get("NOMINA_PG_BIN", "")
    ruta = str(Path(carpeta) / nombre) if carpeta else shutil.which(nombre)
    if not ruta or not Path(ruta).exists():
        raise ErrorBaseDatos(f"No se encontró {nombre}. Instale el cliente de PostgreSQL o defina NOMINA_PG_BIN.")
    return ruta


def _conexion_pg():
    datos = connection.settings_dict
    argumentos = ["--host", str(datos.get("HOST") or "localhost"), "--port", str(datos.get("PORT") or "5432"),
                  "--username", str(datos.get("USER") or ""), "--dbname", str(datos["NAME"])]
    entorno = {**os.environ, "PGPASSWORD": str(datos.get("PASSWORD") or "")}
    return argumentos, entorno


@contextmanager
def archivo_temporal(sufijo=""):
    """Archivo temporal sólo legible por el usuario; se borra al terminar."""
    descriptor, ruta = tempfile.mkstemp(prefix="nomina-", suffix=sufijo)
    os.close(descriptor)
    os.chmod(ruta, 0o600)
    try:
        yield ruta
    finally:
        try:
            os.remove(ruta)
        except FileNotFoundError:
            pass


@contextmanager
def volcado():
    """Abre un flujo de lectura con el volcado completo de la base de datos."""
    if motor() == "postgresql":
        argumentos, entorno = _conexion_pg()
        proceso = subprocess.Popen(  # nosec B603 — programa y argumentos de la configuración, sin shell
            [_programa("pg_dump"), "--format=custom", "--no-owner", "--no-privileges", *argumentos],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=entorno,
        )
        try:
            yield proceso.stdout
        finally:
            proceso.stdout.close()
            error = proceso.stderr.read().decode("utf-8", "replace")
            if proceso.wait() != 0:
                raise ErrorBaseDatos(f"pg_dump falló: {error.strip()[:500]}")
        return
    with archivo_temporal(".sqlite3") as ruta:
        connection.ensure_connection()
        destino = sqlite3.connect(ruta)
        try:
            connection.connection.backup(destino)
        finally:
            destino.close()
        with open(ruta, "rb") as flujo:
            yield flujo


def cargar(ruta_volcado: str):
    """Reemplaza el contenido de la base de datos con el volcado (ya descifrado)."""
    if motor() == "postgresql":
        connection.close()
        argumentos, entorno = _conexion_pg()
        resultado = subprocess.run(  # nosec B603
            [_programa("pg_restore"), "--clean", "--if-exists", "--no-owner", "--no-privileges",
             "--single-transaction", "--exit-on-error", *argumentos, ruta_volcado],
            capture_output=True, env=entorno,
        )
        if resultado.returncode != 0:
            raise ErrorBaseDatos("pg_restore falló: " + resultado.stderr.decode("utf-8", "replace").strip()[:800])
        return
    connection.ensure_connection()
    origen = sqlite3.connect(ruta_volcado)
    try:
        origen.backup(connection.connection)
    finally:
        origen.close()


def validar_volcado(ruta_volcado: str) -> str:
    """Comprueba que el volcado se puede leer (pg_restore --list o integridad de SQLite). Devuelve un resumen."""
    if motor() == "postgresql":
        resultado = subprocess.run(  # nosec B603
            [_programa("pg_restore"), "--list", ruta_volcado], capture_output=True)
        if resultado.returncode != 0:
            raise ErrorBaseDatos("El volcado no es válido: " + resultado.stderr.decode("utf-8", "replace")[:300])
        tablas = sum(1 for l in resultado.stdout.decode("utf-8", "replace").splitlines() if " TABLE DATA " in l)
        return f"{tablas} tablas con datos"
    conexion = sqlite3.connect(ruta_volcado)
    try:
        estado = conexion.execute("PRAGMA integrity_check").fetchone()[0]
        tablas = conexion.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
    finally:
        conexion.close()
    if estado != "ok":
        raise ErrorBaseDatos(f"El volcado de SQLite está dañado: {estado}")
    return f"{tablas} tablas"


def directorio_respaldos() -> Path:
    return Path(getattr(settings, "NOMINA_DIR_RESPALDOS", "") or (Path(settings.BASE_DIR) / "respaldos"))
