from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    verbose_name = "Núcleo"

    def ready(self):
        from . import cifrado

        # Si las llaves están mal, el sistema no arranca (mejor que fallar al guardar).
        cifrado.verificar_configuracion()
