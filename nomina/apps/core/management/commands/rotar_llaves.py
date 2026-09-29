from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand, CommandError

from apps.auditoria.servicios import Accion, registrar
from apps.core import cifrado, rotacion


class Command(BaseCommand):
    help = ("Vuelve a cifrar todos los datos sensibles con la llave activa (NOMINA_LLAVE_ACTIVA) y, si se indica, "
            "recalcula los índices de búsqueda con una llave de índice nueva. Detenga la aplicación y haga un "
            "respaldo antes.")

    def add_arguments(self, parser):
        parser.add_argument("--inventario", action="store_true",
                            help="Sólo muestra cuántos valores hay cifrados con cada llave.")
        parser.add_argument("--llave-indice-nueva",
                            help="Llave nueva (base64) para los índices ciegos. Después ponga esta misma llave en "
                                 "NOMINA_LLAVE_INDICE.")
        parser.add_argument("--confirmar", action="store_true", help="Confirma que hay un respaldo reciente.")

    def _tabla(self, resumen):
        for (campo, llave), n in sorted(resumen.por_llave.items()):
            self.stdout.write(f"  {campo:<45} llave {llave}: {n}")

    def handle(self, *args, inventario, llave_indice_nueva, confirmar, **opciones):
        try:
            cifrado.verificar_configuracion()
        except ImproperlyConfigured as e:
            raise CommandError(str(e))
        if inventario:
            self.stdout.write("Valores cifrados por llave:")
            self._tabla(rotacion.inventario())
            self.stdout.write(f"Llave activa: {settings.NOMINA_LLAVE_ACTIVA}. "
                              f"Llaves configuradas: {', '.join(cifrado.llaves_configuradas())}.")
            return
        if not confirmar:
            raise CommandError("Detenga la aplicación, haga un respaldo (manage.py respaldar) y repita con --confirmar.")
        nueva = None
        if llave_indice_nueva:
            try:
                nueva = cifrado.llave_de_texto(llave_indice_nueva, "--llave-indice-nueva")
            except ImproperlyConfigured as e:
                raise CommandError(str(e))
        try:
            resumen = rotacion.rotar(nueva)
        except cifrado.ErrorCifrado as e:
            raise CommandError(f"No se cambió nada: {e}")
        registrar(accion=Accion.LLAVES_ROTADAS,
                  descripcion=f"{resumen.recifrados} valores recifrados; {resumen.indices} índices recalculados",
                  cambios={"recifrados": resumen.recifrados, "indices": resumen.indices})
        self.stdout.write(self.style.SUCCESS(f"Listo: {resumen.recifrados} valores recifrados con la llave activa."))
        self._tabla(resumen)
        if nueva:
            self.stdout.write(self.style.WARNING(
                f"Se recalcularon {resumen.indices} índices. AHORA ponga la llave nueva en NOMINA_LLAVE_INDICE "
                "y reinicie la aplicación; hasta entonces las búsquedas por SSN no funcionan."))
