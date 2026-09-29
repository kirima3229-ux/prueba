from django.apps import AppConfig


class AuditoriaConfig(AppConfig):
    name = "apps.auditoria"
    verbose_name = "Auditoría"

    def ready(self):
        from . import senales  # noqa: F401
