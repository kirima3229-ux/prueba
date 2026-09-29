from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from apps.auditoria.servicios import Accion, registrar
from apps.core import basedatos, respaldo


class Command(BaseCommand):
    help = ("REEMPLAZA toda la base de datos con un respaldo cifrado. Detenga la aplicación antes. "
            "Requiere --confirmar.")

    def add_arguments(self, parser):
        parser.add_argument("archivo")
        parser.add_argument("--confirmar", action="store_true",
                            help="Confirma que se reemplazarán TODOS los datos actuales.")

    def handle(self, *args, archivo, confirmar, **opciones):
        if not confirmar:
            raise CommandError("Esto reemplaza TODOS los datos actuales con el respaldo. Detenga la aplicación, "
                               "haga un respaldo de lo actual y repita con --confirmar.")
        try:
            with open(archivo, "rb") as entrada, basedatos.archivo_temporal() as ruta:
                with open(ruta, "wb") as salida:
                    respaldo.descifrar(entrada, salida, respaldo.llaves_respaldo())
                resumen = basedatos.validar_volcado(ruta)
                basedatos.cargar(ruta)
        except FileNotFoundError:
            raise CommandError(f"No existe el archivo {archivo}.")
        except (respaldo.ErrorRespaldo, basedatos.ErrorBaseDatos, ImproperlyConfigured) as e:
            raise CommandError(f"No se restauró nada: {e}")
        registrar(accion=Accion.RESPALDO_RESTAURADO, descripcion=f"Restaurado desde {archivo} ({resumen})")
        self.stdout.write(self.style.SUCCESS(f"Base de datos restaurada ({resumen}). "
                                             "Ejecute verificar_auditoria para confirmar la bitácora."))
