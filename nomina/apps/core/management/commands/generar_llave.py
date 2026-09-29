from django.core.management.base import BaseCommand

from apps.core.cifrado import generar_llave


class Command(BaseCommand):
    help = "Imprime una llave AES-256 nueva (32 bytes en base64) para el .env."

    def handle(self, *args, **opciones):
        self.stdout.write(generar_llave())
