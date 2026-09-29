"""
Parámetros de nómina por año de vigencia. Regla de oro: ninguna tasa, tope ni
tabla está en el código; todo vive aquí, se edita en pantalla (administradores),
queda en la bitácora y se marca POR VERIFICAR hasta que se confirma.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.companias.models import EstadoVerificacion


def _porcentaje(nombre):
    return models.DecimalField(
        nombre, max_digits=7, decimal_places=4, validators=[MinValueValidator(0), MaxValueValidator(100)]
    )


def _dinero(nombre, **kwargs):
    return models.DecimalField(nombre, max_digits=12, decimal_places=2, validators=[MinValueValidator(0)], **kwargs)


class VerificableMixin(models.Model):
    estado = models.CharField(
        max_length=20, choices=EstadoVerificacion.choices, default=EstadoVerificacion.POR_VERIFICAR
    )
    verificado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    verificado_en = models.DateTimeField(null=True, blank=True)
    notas = models.TextField(blank=True)
    modificado = models.DateTimeField(auto_now=True)

    CAMPOS_NO_AUDITABLES = ("modificado",)

    class Meta:
        abstract = True

    @property
    def verificado(self):
        return self.estado == EstadoVerificacion.VERIFICADO


class ParametrosAnuales(VerificableMixin):
    anio = models.PositiveSmallIntegerField(
        "año", unique=True, validators=[MinValueValidator(2000), MaxValueValidator(2100)]
    )
    # Seguro Social y Medicare
    ss_tasa_empleado = _porcentaje("Seguro Social empleado %")
    ss_tasa_patrono = _porcentaje("Seguro Social patrono %")
    ss_tope = _dinero("tope salarial anual del Seguro Social ($)")
    medicare_tasa_empleado = _porcentaje("Medicare empleado %")
    medicare_tasa_patrono = _porcentaje("Medicare patrono %")
    medicare_adicional_tasa = _porcentaje("Medicare adicional (empleado) %")
    medicare_adicional_umbral = _dinero("umbral anual del Medicare adicional ($)")
    # Desempleo federal y estatal, incapacidad
    futa_tasa = _porcentaje("FUTA % (neto, después del crédito)")
    futa_tope = _dinero("tope salarial anual FUTA ($)")
    desempleo_tope = _dinero(
        "tope salarial anual de desempleo estatal ($)", help_text="Aplica a SUTA y a la aportación especial."
    )
    sinot_tope = _dinero("tope salarial anual SINOT ($)")
    # Seguro Choferil (cuota fija semanal)
    choferil_empleado_semanal = _dinero("Seguro Choferil empleado por semana ($)")
    choferil_patrono_semanal = _dinero("Seguro Choferil patrono por semana ($)")
    # Retención de Puerto Rico (además de la tabla por tramos)
    exencion_personal_individuo = _dinero("exención personal — individuo ($ anual)")
    exencion_personal_casado = _dinero("exención personal — casado ($ anual, completa)")
    exencion_dependiente = _dinero("exención por dependiente ($ anual)")
    exencion_dependiente_custodia = _dinero("exención por dependiente con custodia compartida ($ anual)")
    exencion_veterano = _dinero("exención de veterano ($ anual)")

    class Meta:
        ordering = ["-anio"]
        verbose_name = "parámetros anuales"
        verbose_name_plural = "parámetros anuales"

    def __str__(self):
        return f"Parámetros {self.anio}"


class TramoRetencionPR(models.Model):
    """Tabla de retención de Hacienda (ingreso anualizado)."""

    parametros = models.ForeignKey(ParametrosAnuales, on_delete=models.CASCADE, related_name="tramos")
    desde = _dinero("desde ($)")
    hasta = _dinero("hasta ($)", null=True, blank=True)
    cuota_fija = _dinero("cuota fija ($)")
    tasa = _porcentaje("tasa sobre el exceso %")

    class Meta:
        ordering = ["desde"]
        verbose_name = "tramo de retención"

    def __str__(self):
        hasta = f"${self.hasta:,.2f}" if self.hasta is not None else "en adelante"
        return f"${self.desde:,.2f} – {hasta}: ${self.cuota_fija:,.2f} + {self.tasa}%"


class ReglaHorasExtra(models.Model):
    """Multiplicadores de horas extra según el régimen laboral del empleado."""

    parametros = models.ForeignKey(ParametrosAnuales, on_delete=models.CASCADE, related_name="reglas_horas_extra")
    regimen = models.CharField(
        max_length=10, choices=[("anterior", "Antes de Ley 4-2017"), ("ley4", "Ley 4-2017")]
    )
    diario = models.DecimalField("exceso de 8 horas diarias (×)", max_digits=4, decimal_places=2)
    semanal = models.DecimalField("exceso de 40 horas semanales (×)", max_digits=4, decimal_places=2)
    septimo_dia = models.DecimalField("séptimo día / día de descanso (×)", max_digits=4, decimal_places=2)
    periodo_alimentos = models.DecimalField("trabajo en el período de tomar alimentos (×)", max_digits=4, decimal_places=2)

    class Meta:
        ordering = ["regimen"]
        constraints = [models.UniqueConstraint(fields=["parametros", "regimen"], name="regla_he_unica")]

    def __str__(self):
        return f"{self.get_regimen_display()} {self.parametros.anio}"


class SalarioMinimo(VerificableMixin):
    vigente_desde = models.DateField("vigente desde", unique=True)
    tarifa_hora = _dinero("salario mínimo por hora ($)")

    class Meta:
        ordering = ["-vigente_desde"]
        verbose_name = "salario mínimo"
        verbose_name_plural = "salarios mínimos"

    def __str__(self):
        return f"${self.tarifa_hora} desde {self.vigente_desde:%m/%d/%Y}"


class ConceptoIngreso(VerificableMixin):
    """Tipo de ingreso y a qué contribuciones está sujeto."""

    codigo = models.SlugField("código", max_length=30, unique=True)
    nombre = models.CharField(max_length=100)
    tributable_pr = models.BooleanField("retención de PR", default=True)
    tributable_ss = models.BooleanField("Seguro Social", default=True)
    tributable_medicare = models.BooleanField("Medicare", default=True)
    tributable_futa = models.BooleanField("FUTA", default=True)
    tributable_desempleo = models.BooleanField("desempleo estatal (SUTA y aportación especial)", default=True)
    tributable_sinot = models.BooleanField("SINOT", default=True)
    tributable_cfse = models.BooleanField("nómina para CFSE", default=True)
    activo = models.BooleanField(default=True)
    del_sistema = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "concepto de ingreso"
        verbose_name_plural = "conceptos de ingreso"

    def __str__(self):
        return self.nombre


class ConceptoDeduccion(VerificableMixin):
    """Tipo de deducción al empleado y si reduce el salario tributable."""

    codigo = models.SlugField("código", max_length=30, unique=True)
    nombre = models.CharField(max_length=100)
    antes_de_pr = models.BooleanField("antes de la retención de PR", default=False)
    antes_de_federal = models.BooleanField("antes de la retención federal", default=False)
    antes_de_fica = models.BooleanField(
        "antes de Seguro Social, Medicare y desempleo/SINOT", default=False
    )
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "concepto de deducción"
        verbose_name_plural = "conceptos de deducción"

    def __str__(self):
        return self.nombre
