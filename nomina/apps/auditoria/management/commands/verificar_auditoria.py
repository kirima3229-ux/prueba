from django.core.management.base import BaseCommand, CommandError

from apps.auditoria.servicios import verificar_cadena


class Command(BaseCommand):
    help = "Verifica la cadena de hashes de la bitácora de auditoría (detecta alteraciones)."

    def handle(self, *args, **options):
        ok, total, problemas = verificar_cadena()
        if ok:
            self.stdout.write(self.style.SUCCESS(f"Bitácora íntegra: {total} registros verificados."))
            return
        for problema in problemas:
            self.stderr.write(problema)
        raise CommandError(f"La bitácora tiene {len(problemas)} problema(s) de integridad.")
