from django.conf import settings
from django.db import models

from apps.companias.models import Compania


class Radicacion(models.Model):
    """Constancia de que una planilla se radicó o pagó (número de confirmación de la agencia)."""

    compania = models.ForeignKey(Compania, on_delete=models.PROTECT, related_name="radicaciones")
    tipo = models.CharField(max_length=20)
    anio = models.PositiveSmallIntegerField("año")
    trimestre = models.PositiveSmallIntegerField(null=True, blank=True)
    fecha = models.DateField("fecha de radicación o pago")
    confirmacion = models.CharField("número de confirmación", max_length=60)
    monto = models.DecimalField("monto pagado", max_digits=12, decimal_places=2, null=True, blank=True)
    notas = models.CharField(max_length=300, blank=True)
    registrado_en = models.DateTimeField(auto_now_add=True)
    registrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-fecha", "-registrado_en"]
        verbose_name_plural = "radicaciones"

    def __str__(self):
        return f"{self.tipo} {self.anio}{f' T{self.trimestre}' if self.trimestre else ''} — {self.confirmacion}"
