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
    # Vacaciones y enfermedad
    horas_por_dia = models.DecimalField(
        "horas por día de licencia", max_digits=4, decimal_places=2, default=8,
        help_text="Para convertir días de licencia a horas.",
    )
    limite_patrono_pequeno_licencias = models.PositiveSmallIntegerField(
        "patrono pequeño para licencias: hasta cuántos empleados", default=12
    )
    tope_vacaciones_meses = models.PositiveSmallIntegerField(
        "tope de vacaciones acumuladas (meses de acumulación)", default=24,
        help_text="Ej.: 24 = hasta dos años de vacaciones acumuladas.",
    )
    tope_enfermedad_dias = models.DecimalField(
        "tope de licencia por enfermedad acumulada (días)", max_digits=5, decimal_places=2, default=15
    )

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
    tarifa_propinas = _dinero(
        "mínimo en efectivo por hora para empleados con propinas ($)",
        null=True,
        blank=True,
        help_text="Lo mínimo que el patrono paga en efectivo a meseros y otros empleados con propinas. "
        "Sus vacaciones y licencias por enfermedad se pagan al salario mínimo completo.",
    )

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


REGIMENES = [("anterior", "Antes de Ley 4-2017"), ("ley4", "Ley 4-2017")]


class ReglaLicencia(models.Model):
    """Acumulación mensual de vacaciones o enfermedad (Ley 180 / Ley 4-2017)."""

    class Tipo(models.TextChoices):
        VACACIONES = "vacaciones", "Vacaciones"
        ENFERMEDAD = "enfermedad", "Enfermedad"

    class Tamano(models.TextChoices):
        GRANDE = "grande", "Patrono de más empleados que el límite"
        PEQUENO = "pequeno", "Patrono pequeño (hasta el límite)"

    parametros = models.ForeignKey(ParametrosAnuales, on_delete=models.CASCADE, related_name="reglas_licencia")
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    regimen = models.CharField(max_length=10, choices=REGIMENES)
    tamano = models.CharField("tamaño del patrono", max_length=10, choices=Tamano.choices)
    anios_desde = models.DecimalField("años de servicio desde", max_digits=5, decimal_places=2, default=0)
    anios_hasta = models.DecimalField(
        "años de servicio hasta", max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Vacío = en adelante.",
    )
    horas_minimas_mes = models.DecimalField("horas trabajadas mínimas en el mes", max_digits=6, decimal_places=2)
    dias_por_mes = models.DecimalField("días acumulados por mes", max_digits=5, decimal_places=3)

    class Meta:
        ordering = ["tipo", "regimen", "tamano", "anios_desde"]
        verbose_name = "regla de licencia"

    def __str__(self):
        hasta = f"{self.anios_hasta}" if self.anios_hasta is not None else "∞"
        return (
            f"{self.get_tipo_display()} · {self.get_regimen_display()} · {self.get_tamano_display()} · "
            f"{self.anios_desde}–{hasta} años: {self.dias_por_mes} día(s)/mes con {self.horas_minimas_mes} h"
        )


class ReglaBonoNavidad(models.Model):
    """Bono de Navidad (Ley 148-1969, enmendada por Ley 4-2017), por régimen."""

    parametros = models.ForeignKey(ParametrosAnuales, on_delete=models.CASCADE, related_name="reglas_bono")
    regimen = models.CharField(max_length=10, choices=REGIMENES)
    mes_inicio_periodo = models.PositiveSmallIntegerField(
        "mes en que empieza el período", default=10, validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="10 = del 1 de octubre del año anterior al 30 de septiembre.",
    )
    horas_minimas = models.DecimalField("horas mínimas trabajadas en el período", max_digits=7, decimal_places=2)
    umbral_empleados = models.PositiveSmallIntegerField(
        "patrono grande: más de cuántos empleados"
    )
    porcentaje_grande = _porcentaje("% patrono grande")
    tope_grande = _dinero("bono máximo patrono grande ($)")
    porcentaje_pequeno = _porcentaje("% patrono pequeño")
    tope_pequeno = _dinero("bono máximo patrono pequeño ($)")
    tope_salario = _dinero("salario máximo considerado ($)", null=True, blank=True, help_text="Vacío = sin tope de salario.")

    class Meta:
        ordering = ["regimen"]
        constraints = [models.UniqueConstraint(fields=["parametros", "regimen"], name="regla_bono_unica")]
        verbose_name = "regla del bono de Navidad"

    def __str__(self):
        return f"Bono {self.get_regimen_display()} {self.parametros.anio}"
