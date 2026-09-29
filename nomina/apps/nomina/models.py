"""
Flujo de nómina: período → entradas (horas, ingresos, deducciones) → cálculo
(pre-nómina) → aprobar y cerrar → (si hace falta) reversar.

Un período cerrado no se modifica. Para corregirlo se reversa: se crea un
período de reverso con los mismos montos en negativo (los acumulados del año
quedan netos en cero) y se procesa una nómina nueva correcta.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from apps.companias.models import Compania
from apps.empleados.models import Empleado
from apps.parametros.models import ConceptoDeduccion, ConceptoIngreso


class ErrorNominaCerrada(Exception):
    pass


def _horas(nombre):
    return models.DecimalField(nombre, max_digits=7, decimal_places=2, default=0, validators=[MinValueValidator(0)])


class DeduccionRecurrente(models.Model):
    """Deducción que se aplica en cada nómina del empleado (plan médico, retiro, préstamo, ASUME...)."""

    empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT, related_name="deducciones_recurrentes")
    concepto = models.ForeignKey(ConceptoDeduccion, on_delete=models.PROTECT)
    monto = models.DecimalField("monto por período", max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    desde = models.DateField(null=True, blank=True)
    hasta = models.DateField(null=True, blank=True, help_text="Vacío = sin fecha final.")
    activo = models.BooleanField(default=True)
    notas = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["concepto__nombre"]
        verbose_name = "deducción recurrente"
        verbose_name_plural = "deducciones recurrentes"

    def __str__(self):
        return f"{self.concepto} ${self.monto:,.2f}"

    def vigente_en(self, fecha) -> bool:
        return self.activo and (self.desde is None or self.desde <= fecha) and (self.hasta is None or fecha <= self.hasta)


class PeriodoNomina(models.Model):
    class Estado(models.TextChoices):
        BORRADOR = "borrador", "Borrador"
        CALCULADA = "calculada", "Pre-nómina calculada"
        CERRADA = "cerrada", "Aprobada y cerrada"
        REVERSADA = "reversada", "Reversada"

    class Tipo(models.TextChoices):
        REGULAR = "regular", "Regular"
        ESPECIAL = "especial", "Especial (bono, ajuste, nómina final)"
        REVERSO = "reverso", "Reverso"

    compania = models.ForeignKey(Compania, on_delete=models.PROTECT, related_name="periodos_nomina")
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.REGULAR)
    fecha_inicio = models.DateField("desde")
    fecha_fin = models.DateField("hasta")
    fecha_pago = models.DateField("fecha de pago")
    descripcion = models.CharField(max_length=200, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.BORRADOR)
    requiere_recalculo = models.BooleanField(default=True)
    errores = models.JSONField(default=list, blank=True)
    parametros_usados = models.JSONField(default=dict, blank=True)
    reverso_de = models.OneToOneField(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="reverso"
    )
    motivo_reverso = models.CharField(max_length=300, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    calculado_en = models.DateTimeField(null=True, blank=True)
    calculado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    cerrado_en = models.DateTimeField(null=True, blank=True)
    cerrado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-fecha_pago", "-id"]
        verbose_name = "período de nómina"
        verbose_name_plural = "períodos de nómina"

    def __str__(self):
        extra = f" ({self.get_tipo_display()})" if self.tipo != self.Tipo.REGULAR else ""
        return f"Nómina {self.fecha_inicio:%m/%d/%Y}–{self.fecha_fin:%m/%d/%Y}, pago {self.fecha_pago:%m/%d/%Y}{extra}"

    @property
    def editable(self):
        return self.estado in (self.Estado.BORRADOR, self.Estado.CALCULADA)

    @property
    def cerrado(self):
        return self.estado in (self.Estado.CERRADA, self.Estado.REVERSADA)

    def exigir_editable(self):
        if not self.editable:
            raise ErrorNominaCerrada("La nómina está cerrada: no se puede modificar. Para corregirla, reverse y procese de nuevo.")


class EntradaNomina(models.Model):
    """Lo que se entra para un empleado en un período."""

    periodo = models.ForeignKey(PeriodoNomina, on_delete=models.CASCADE, related_name="entradas")
    empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT, related_name="entradas_nomina")
    incluir = models.BooleanField(default=True)
    horas_regulares = _horas("horas regulares")
    horas_extra_diarias = _horas("horas extra (exceso de 8 diarias)")
    horas_extra_semanales = _horas("horas extra (exceso de 40 semanales)")
    horas_septimo_dia = _horas("horas en séptimo día")
    horas_periodo_alimentos = _horas("horas en período de alimentos")
    horas_vacaciones = _horas("horas de vacaciones")
    horas_enfermedad = _horas("horas de enfermedad")
    semanas_choferil = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["empleado__apellido_paterno", "empleado__nombre"]
        constraints = [models.UniqueConstraint(fields=["periodo", "empleado"], name="una_entrada_por_empleado")]

    def __str__(self):
        return f"{self.empleado.nombre_completo} — {self.periodo}"

    @property
    def horas_trabajadas(self):
        return (self.horas_regulares + self.horas_extra_diarias + self.horas_extra_semanales
                + self.horas_septimo_dia + self.horas_periodo_alimentos)


class EntradaIngreso(models.Model):
    entrada = models.ForeignKey(EntradaNomina, on_delete=models.CASCADE, related_name="ingresos")
    concepto = models.ForeignKey(ConceptoIngreso, on_delete=models.PROTECT)
    monto = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    descripcion = models.CharField(max_length=200, blank=True)


class EntradaDeduccion(models.Model):
    entrada = models.ForeignKey(EntradaNomina, on_delete=models.CASCADE, related_name="deducciones")
    concepto = models.ForeignKey(ConceptoDeduccion, on_delete=models.PROTECT)
    monto = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    descripcion = models.CharField(max_length=200, blank=True)
    recurrente = models.ForeignKey(DeduccionRecurrente, null=True, blank=True, on_delete=models.SET_NULL)


class ResultadoNomina(models.Model):
    """Resultado del cálculo de un empleado en un período (con copia de sus datos al momento)."""

    periodo = models.ForeignKey(PeriodoNomina, on_delete=models.CASCADE, related_name="resultados")
    empleado = models.ForeignKey(Empleado, on_delete=models.PROTECT, related_name="resultados_nomina")
    empleado_nombre = models.CharField(max_length=250)
    numero_empleado = models.CharField(max_length=20)
    ssn_ultimos4 = models.CharField(max_length=4)
    departamento = models.CharField(max_length=100, blank=True)
    regimen = models.CharField(max_length=10)
    tarifa = models.DecimalField(max_digits=12, decimal_places=4)
    tipo_pago = models.CharField(max_length=10)
    horas_trabajadas = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    bruto = models.DecimalField(max_digits=12, decimal_places=2)
    total_retenciones = models.DecimalField(max_digits=12, decimal_places=2)
    total_deducciones = models.DecimalField(max_digits=12, decimal_places=2)
    neto = models.DecimalField(max_digits=12, decimal_places=2)
    total_patronal = models.DecimalField(max_digits=12, decimal_places=2)
    trib_pr = models.DecimalField(max_digits=12, decimal_places=2)
    trib_ss = models.DecimalField(max_digits=12, decimal_places=2)
    trib_medicare = models.DecimalField(max_digits=12, decimal_places=2)
    trib_futa = models.DecimalField(max_digits=12, decimal_places=2)
    trib_desempleo = models.DecimalField(max_digits=12, decimal_places=2)
    trib_sinot = models.DecimalField(max_digits=12, decimal_places=2)
    trib_cfse = models.DecimalField(max_digits=12, decimal_places=2)
    alertas = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["empleado_nombre"]
        constraints = [models.UniqueConstraint(fields=["periodo", "empleado"], name="un_resultado_por_empleado")]

    def __str__(self):
        return f"{self.empleado_nombre} — neto ${self.neto:,.2f}"

    def save(self, *args, **kwargs):
        if self.pk and self.periodo.cerrado:
            raise ErrorNominaCerrada("El resultado de una nómina cerrada no se modifica.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.periodo.cerrado:
            raise ErrorNominaCerrada("El resultado de una nómina cerrada no se borra; se reversa.")
        return super().delete(*args, **kwargs)

    def lineas_de(self, grupo):
        return [l for l in self.lineas.all() if l.grupo == grupo]


class LineaResultado(models.Model):
    class Grupo(models.TextChoices):
        INGRESO = "ingreso", "Ingreso"
        RETENCION = "retencion", "Retención"
        DEDUCCION = "deduccion", "Deducción"
        PATRONAL = "patronal", "Aportación patronal"

    resultado = models.ForeignKey(ResultadoNomina, on_delete=models.CASCADE, related_name="lineas")
    grupo = models.CharField(max_length=10, choices=Grupo.choices)
    codigo = models.CharField(max_length=40)
    nombre = models.CharField(max_length=150)
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    base = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    tasa = models.DecimalField(max_digits=9, decimal_places=4, null=True, blank=True)
    explicacion = models.TextField(blank=True)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["orden"]


CERO = Decimal("0")
