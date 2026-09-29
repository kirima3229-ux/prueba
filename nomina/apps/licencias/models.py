from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q, Sum

from apps.companias.models import Compania
from apps.empleados.models import Empleado


class ErrorInmutable(Exception):
    pass


class TipoLicencia(models.TextChoices):
    VACACIONES = "vacaciones", "Vacaciones"
    ENFERMEDAD = "enfermedad", "Enfermedad"


class MovimientoLicencia(models.Model):
    """
    Movimiento del balance de vacaciones o enfermedad, en horas. El balance es
    la suma de los movimientos. No se editan ni se borran: una corrección se
    hace con un ajuste (queda la traza).
    """

    class Clase(models.TextChoices):
        SALDO_INICIAL = "saldo_inicial", "Saldo inicial"
        ACUMULACION = "acumulacion", "Acumulación mensual"
        USO = "uso", "Uso (licencia disfrutada)"
        AJUSTE = "ajuste", "Ajuste"
        LIQUIDACION = "liquidacion", "Liquidación"

    empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT, related_name="movimientos_licencia")
    tipo = models.CharField(max_length=10, choices=TipoLicencia.choices)
    clase = models.CharField(max_length=15, choices=Clase.choices)
    fecha = models.DateField()
    periodo = models.DateField(
        null=True, blank=True, help_text="Primer día del mes acumulado (solo acumulaciones)."
    )
    horas = models.DecimalField(max_digits=8, decimal_places=2, help_text="Positivo suma, negativo resta.")
    horas_trabajadas = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    descripcion = models.CharField(max_length=300, blank=True)
    periodo_nomina = models.ForeignKey(
        "nomina.PeriodoNomina", null=True, blank=True, on_delete=models.PROTECT, related_name="movimientos_licencia"
    )
    creado = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-fecha", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["empleado", "tipo", "periodo"], condition=Q(clase="acumulacion"),
                name="una_acumulacion_por_mes",
            )
        ]
        verbose_name = "movimiento de licencia"
        verbose_name_plural = "movimientos de licencia"

    def __str__(self):
        return f"{self.get_tipo_display()} {self.get_clase_display()} {self.horas} h ({self.fecha:%m/%d/%Y})"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ErrorInmutable("Los movimientos de licencia no se modifican; registre un ajuste.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ErrorInmutable("Los movimientos de licencia no se borran; registre un ajuste.")


def saldo(empleado, tipo) -> Decimal:
    total = MovimientoLicencia.objects.filter(empleado=empleado, tipo=tipo).aggregate(t=Sum("horas"))["t"]
    return total or Decimal("0")


class BonoNavidad(models.Model):
    """Cálculo del bono de Navidad de un empleado para un año (se paga en diciembre)."""

    class Estado(models.TextChoices):
        CALCULADO = "calculado", "Calculado"
        PAGADO = "pagado", "Pagado"

    compania = models.ForeignKey(Compania, on_delete=models.PROTECT, related_name="bonos_navidad")
    empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT, related_name="bonos_navidad")
    anio = models.PositiveSmallIntegerField("año")
    periodo_desde = models.DateField()
    periodo_hasta = models.DateField()
    regimen = models.CharField(max_length=10)
    numero_empleados = models.PositiveIntegerField("empleados del patrono")
    horas = models.DecimalField("horas trabajadas en el período", max_digits=8, decimal_places=2)
    salario = models.DecimalField("salario del período", max_digits=12, decimal_places=2)
    elegible = models.BooleanField()
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    explicacion = models.TextField()
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.CALCULADO)
    parametros_verificados = models.BooleanField(default=False)
    calculado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    calculado_en = models.DateTimeField(auto_now=True)

    CAMPOS_NO_AUDITABLES = ("calculado_en",)

    class Meta:
        ordering = ["empleado__apellido_paterno", "empleado__nombre"]
        constraints = [models.UniqueConstraint(fields=["empleado", "anio"], name="un_bono_por_anio")]
        verbose_name = "bono de Navidad"
        verbose_name_plural = "bonos de Navidad"

    def __str__(self):
        return f"Bono {self.anio} {self.empleado.nombre_completo}: ${self.monto:,.2f}"
