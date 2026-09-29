from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.core import cifrado
from apps.core.campos import CampoCifrado, enmascarar


class EstadoVerificacion(models.TextChoices):
    POR_VERIFICAR = "por_verificar", "POR VERIFICAR"
    VERIFICADO = "verificado", "Verificado"


class Compania(models.Model):
    class Frecuencia(models.TextChoices):
        SEMANAL = "semanal", "Semanal"
        BISEMANAL = "bisemanal", "Bisemanal (cada 2 semanas)"
        QUINCENAL = "quincenal", "Quincenal (2 veces al mes)"
        MENSUAL = "mensual", "Mensual"

    class Industria(models.TextChoices):
        RESTAURANTE = "restaurante", "Restaurante"
        FARMACIA = "farmacia", "Farmacia"
        CONSTRUCCION = "construccion", "Construcción"
        SALUD = "salud", "Salud"
        RETAIL = "retail", "Comercio al detal"
        SERVICIOS = "servicios", "Servicios"
        OTRA = "otra", "Otra"

    nombre = models.CharField("nombre legal", max_length=200)
    nombre_comercial = models.CharField(max_length=200, blank=True)
    industria = models.CharField(max_length=20, choices=Industria.choices, default=Industria.OTRA)

    # Números patronales: cifrados. Se guardan los últimos 4 para mostrar.
    ein = CampoCifrado("EIN")
    ein_indice = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    ein_ultimos4 = models.CharField(max_length=4, blank=True, editable=False)
    registro_comerciante = CampoCifrado("número de registro de comerciante (Hacienda)")
    cuenta_patronal_dtrh = CampoCifrado(
        "cuenta patronal DTRH", help_text="Número de cuenta patronal de desempleo e incapacidad."
    )
    poliza_cfse = CampoCifrado("número de póliza CFSE")

    direccion_linea1 = models.CharField("dirección", max_length=200, blank=True)
    direccion_linea2 = models.CharField("dirección (línea 2)", max_length=200, blank=True)
    ciudad = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=2, default="PR")
    codigo_postal = models.CharField("código postal", max_length=10, blank=True)
    telefono = models.CharField("teléfono", max_length=20, blank=True)
    persona_contacto = models.CharField(max_length=150, blank=True)
    email_contacto = models.EmailField("email de contacto", blank=True)

    frecuencia_pago = models.CharField(
        "frecuencia de pago", max_length=20, choices=Frecuencia.choices, default=Frecuencia.SEMANAL
    )
    class FrecuenciaDeposito(models.TextChoices):
        MENSUAL = "mensual", "Mensual"
        BISEMANAL = "bisemanal", "Bisemanal"

    frecuencia_deposito = models.CharField(
        "frecuencia de depósito de retenciones (Hacienda)",
        max_length=10,
        choices=FrecuenciaDeposito.choices,
        default=FrecuenciaDeposito.MENSUAL,
        help_text="Cada cuánto se depositan las retenciones (nómina y servicios prestados).",
    )
    frecuencia_deposito_federal = models.CharField(
        "frecuencia de depósito federal (941)",
        max_length=10,
        choices=FrecuenciaDeposito.choices,
        default=FrecuenciaDeposito.MENSUAL,
        help_text="Según el período de referencia del IRS (lookback): mensual o bisemanal (semiweekly).",
    )
    numero_empleados = models.PositiveIntegerField(
        "número de empleados (declarado)",
        default=0,
        help_text="Se usa para las reglas que dependen del tamaño del patrono "
        "(vacaciones, enfermedad, bono de Navidad).",
    )
    activa = models.BooleanField(default=True)
    creada = models.DateTimeField(auto_now_add=True)
    modificada = models.DateTimeField(auto_now=True)

    CAMPOS_NO_AUDITABLES = ("ein_indice", "creada", "modificada")

    class Meta:
        ordering = ["nombre"]
        verbose_name = "compañía"
        verbose_name_plural = "compañías"

    def __str__(self):
        return self.nombre_comercial or self.nombre

    def asignar_ein(self, digitos: str):
        self.ein = digitos
        self.ein_indice = cifrado.indice_ciego(digitos, "ein")
        self.ein_ultimos4 = digitos[-4:]

    @property
    def ein_enmascarado(self):
        return f"XX-XXX{self.ein_ultimos4}" if self.ein_ultimos4 else ""

    @property
    def cuenta_dtrh_enmascarada(self):
        return enmascarar(self.cuenta_patronal_dtrh.revelar()) if self.cuenta_patronal_dtrh else ""

    @property
    def poliza_cfse_enmascarada(self):
        return enmascarar(self.poliza_cfse.revelar()) if self.poliza_cfse else ""

    @property
    def registro_comerciante_enmascarado(self):
        return enmascarar(self.registro_comerciante.revelar()) if self.registro_comerciante else ""


def _validadores_tasa():
    return [MinValueValidator(0), MaxValueValidator(100)]


class TasasCompania(models.Model):
    """Tasas patronales propias de cada compañía, por año de vigencia (en %)."""

    compania = models.ForeignKey(Compania, on_delete=models.PROTECT, related_name="tasas")
    anio = models.PositiveSmallIntegerField("año", validators=[MinValueValidator(2000), MaxValueValidator(2100)])
    suta_tasa = models.DecimalField(
        "desempleo estatal (SUTA) %", max_digits=7, decimal_places=4, validators=_validadores_tasa()
    )
    aportacion_especial_tasa = models.DecimalField(
        "aportación especial %", max_digits=7, decimal_places=4, validators=_validadores_tasa()
    )
    sinot_empleado_tasa = models.DecimalField(
        "incapacidad (SINOT) empleado %", max_digits=7, decimal_places=4, validators=_validadores_tasa()
    )
    sinot_patrono_tasa = models.DecimalField(
        "incapacidad (SINOT) patrono %", max_digits=7, decimal_places=4, validators=_validadores_tasa()
    )
    estado = models.CharField(
        max_length=20, choices=EstadoVerificacion.choices, default=EstadoVerificacion.POR_VERIFICAR
    )
    verificado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    verificado_en = models.DateTimeField(null=True, blank=True)
    notas = models.TextField(blank=True)
    modificada = models.DateTimeField(auto_now=True)

    CAMPOS_NO_AUDITABLES = ("modificada",)

    class Meta:
        ordering = ["-anio"]
        constraints = [models.UniqueConstraint(fields=["compania", "anio"], name="tasas_unicas_por_anio")]
        verbose_name = "tasas de la compañía"
        verbose_name_plural = "tasas de la compañía"

    def __str__(self):
        return f"Tasas {self.anio} — {self.compania}"


class Departamento(models.Model):
    compania = models.ForeignKey(Compania, on_delete=models.PROTECT, related_name="departamentos")
    nombre = models.CharField(max_length=100)
    codigo = models.CharField("código", max_length=20, blank=True)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        constraints = [models.UniqueConstraint(fields=["compania", "nombre"], name="departamento_unico")]

    def __str__(self):
        return self.nombre


class ClasificacionCFSE(models.Model):
    """Clasificación de la póliza CFSE. Las tasas por año se configuran en la Fase 2."""

    compania = models.ForeignKey(Compania, on_delete=models.PROTECT, related_name="clasificaciones_cfse")
    codigo = models.CharField("código", max_length=20)
    descripcion = models.CharField("descripción", max_length=200, blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        ordering = ["codigo"]
        constraints = [models.UniqueConstraint(fields=["compania", "codigo"], name="clasificacion_cfse_unica")]
        verbose_name = "clasificación CFSE"
        verbose_name_plural = "clasificaciones CFSE"

    def __str__(self):
        return f"{self.codigo} — {self.descripcion}" if self.descripcion else self.codigo


class TasaCFSE(models.Model):
    """Tasa de la póliza CFSE por clasificación y año (por cada $100 de nómina)."""

    clasificacion = models.ForeignKey(ClasificacionCFSE, on_delete=models.CASCADE, related_name="tasas")
    anio = models.PositiveSmallIntegerField("año", validators=[MinValueValidator(2000), MaxValueValidator(2100)])
    tasa_por_100 = models.DecimalField(
        "tasa por cada $100 de nómina", max_digits=7, decimal_places=4, validators=[MinValueValidator(0)]
    )
    estado = models.CharField(
        max_length=20, choices=EstadoVerificacion.choices, default=EstadoVerificacion.POR_VERIFICAR
    )
    modificada = models.DateTimeField(auto_now=True)

    CAMPOS_NO_AUDITABLES = ("modificada",)

    class Meta:
        ordering = ["-anio"]
        constraints = [models.UniqueConstraint(fields=["clasificacion", "anio"], name="tasa_cfse_unica")]
        verbose_name = "tasa CFSE"
        verbose_name_plural = "tasas CFSE"

    def __str__(self):
        return f"CFSE {self.clasificacion.codigo} {self.anio}: {self.tasa_por_100} por $100"
