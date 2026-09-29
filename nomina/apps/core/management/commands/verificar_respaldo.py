from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from apps.core import basedatos, respaldo


class Command(BaseCommand):
    help = "Comprueba que un respaldo se puede descifrar completo y que el volcado es válido (no cambia nada)."

    def add_arguments(self, parser):
        parser.add_argument("archivo")

    def handle(self, *args, archivo, **opciones):
        try:
            with open(archivo, "rb") as entrada, basedatos.archivo_temporal() as ruta:
                with open(ruta, "wb") as salida:
                    datos = respaldo.descifrar(entrada, salida, respaldo.llaves_respaldo())
                resumen = basedatos.validar_volcado(ruta)
        except FileNotFoundError:
            raise CommandError(f"No existe el archivo {archivo}.")
        except (respaldo.ErrorRespaldo, basedatos.ErrorBaseDatos, ImproperlyConfigured) as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(f"Respaldo válido: {datos:,} bytes de datos, {resumen}."))
