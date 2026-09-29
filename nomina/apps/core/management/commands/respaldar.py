import hashlib
import os
import time
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.auditoria.servicios import Accion, registrar
from apps.core import basedatos, respaldo


def sha256(ruta) -> str:
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


class Command(BaseCommand):
    help = "Crea un respaldo cifrado de toda la base de datos y borra los respaldos más viejos que el plazo."

    def add_arguments(self, parser):
        parser.add_argument("--destino", help="Carpeta de los respaldos (por defecto NOMINA_DIR_RESPALDOS).")
        parser.add_argument("--conservar-dias", type=int, default=int(os.environ.get("NOMINA_DIAS_RESPALDO", "35")),
                            help="Borra respaldos más viejos que esta cantidad de días (0 = no borrar).")

    def handle(self, *args, **opciones):
        try:
            llave = respaldo.llaves_respaldo()[0]
        except ImproperlyConfigured as e:
            raise CommandError(str(e))
        carpeta = Path(opciones["destino"]) if opciones["destino"] else basedatos.directorio_respaldos()
        carpeta.mkdir(parents=True, exist_ok=True)
        os.chmod(carpeta, 0o700)
        nombre = f"nomina-{timezone.localtime():%Y%m%d-%H%M%S}.respaldo"
        final = carpeta / nombre
        parcial = carpeta / (nombre + ".parcial")
        try:
            descriptor = os.open(parcial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "wb") as salida:
                with basedatos.volcado() as flujo:
                    datos = respaldo.cifrar(flujo, salida, llave)
            os.replace(parcial, final)
        except (basedatos.ErrorBaseDatos, respaldo.ErrorRespaldo, OSError) as e:
            parcial.unlink(missing_ok=True)
            raise CommandError(f"No se pudo crear el respaldo: {e}")
        huella = sha256(final)
        tamano = final.stat().st_size
        registrar(accion=Accion.RESPALDO_CREADO, descripcion=f"{nombre} ({tamano:,} bytes)",
                  cambios={"sha256": huella, "datos": datos})
        self.stdout.write(self.style.SUCCESS(f"Respaldo creado: {final}"))
        self.stdout.write(f"  Tamaño: {tamano:,} bytes · SHA-256: {huella}")
        dias = opciones["conservar_dias"]
        if dias > 0:
            limite = time.time() - dias * 86400
            for viejo in sorted(carpeta.glob("nomina-*.respaldo")):
                if viejo != final and viejo.stat().st_mtime < limite:
                    viejo.unlink()
                    self.stdout.write(f"  Borrado (más de {dias} días): {viejo.name}")
