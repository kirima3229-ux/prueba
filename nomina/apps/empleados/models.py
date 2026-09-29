from datetime import date

from django.conf import settings
from django.db import models

from apps.companias.models import ClasificacionCFSE, Compania, Departamento
from apps.core import cifrado
from apps.core.campos import CampoCifrado
from apps.core.validadores import formato_ssn_enmascarado

# Fecha de vigencia de la Ley 4-2017 (Ley de Transformación y Flexibilidad Laboral).
FECHA_LEY_4_2017 = date(2017, 1, 26)


class Empleado(models.Model):
    class Regimen(models.TextChoices):
        ANTERIOR = "anterior", "Antes de Ley 4-2017"
        LEY4 = "ley4", "Ley 4-2017"

    class TipoPago(models.TextChoices):
        HORA = "hora", "Por hora"
        SALARIO = "salario", "Salario fijo (no exento)"
        EXENTO = "exento", "Salario fijo — exento (sin horas extra)"

    class RazonTerminacion(models.TextChoices):
        RENUNCIA = "renuncia", "Renuncia"
        DESPIDO = "despido", "Despido"
        CESANTIA = "cesantia", "Cesantía / reducción de personal"
        FIN_CONTRATO = "fin_contrato", "Fin de contrato"
        JUBILACION = "jubilacion", "Jubilación"
        FALLECIMIENTO = "fallecimiento", "Fallecimiento"
        OTRA = "otra", "Otra"

    # 499 R-4 — las categorías se confirmarán contra el formulario vigente en la Fase 2.
    class EstadoCivilPR(models.TextChoices):
        SOLTERO = "soltero", "Soltero(a)"
        CASADO = "casado", "Casado(a)"
        CASADO_SEPARADO = "casado_separado", "Casado(a) — planilla separada"
        JEFE_FAMILIA = "jefe_familia", "Jefe(a) de familia"

    class ExencionPersonal(models.TextChoices):
        COMPLETA = "completa", "Completa"
        MITAD = "mitad", "Mitad"
        NINGUNA = "ninguna", "Ninguna"

    class EstadoCivilW4(models.TextChoices):
        SOLTERO = "single", "Soltero o casado declarando por separado"
        CASADO = "married", "Casado declarando conjuntamente"
        JEFE_FAMILIA = "head", "Jefe de familia"

    class TipoCuenta(models.TextChoices):
        CHEQUES = "cheques", "Cheques"
        AHORROS = "ahorros", "Ahorros"

    compania = models.ForeignKey(Compania, on_delete=models.PROTECT, related_name="empleados")
    numero_empleado = models.CharField("número de empleado", max_length=20)

    # Datos personales
    nombre = models.CharField(max_length=60)
    segundo_nombre = models.CharField("segundo nombre", max_length=60, blank=True)
    apellido_paterno = models.CharField("apellido paterno", max_length=60)
    apellido_materno = models.CharField("apellido materno", max_length=60, blank=True)
    ssn = CampoCifrado("SSN")
    ssn_indice = models.CharField(max_length=64, editable=False, db_index=True)
    ssn_ultimos4 = models.CharField(max_length=4, editable=False)
    fecha_nacimiento = models.DateField("fecha de nacimiento", null=True, blank=True)
    direccion_linea1 = models.CharField("dirección", max_length=200, blank=True)
    direccion_linea2 = models.CharField("dirección (línea 2)", max_length=200, blank=True)
    ciudad = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=2, default="PR")
    codigo_postal = models.CharField("código postal", max_length=10, blank=True)
    telefono = models.CharField("teléfono", max_length=20, blank=True)
    email = models.EmailField(blank=True)

    # Empleo
    fecha_empleo = models.DateField("fecha de empleo")
    regimen_laboral = models.CharField(
        "régimen laboral",
        max_length=10,
        choices=Regimen.choices,
        blank=True,
        help_text="En blanco = automático según la fecha de empleo (antes o después del 26-ene-2017).",
    )
    departamento = models.ForeignKey(Departamento, null=True, blank=True, on_delete=models.PROTECT)
    clasificacion_cfse = models.ForeignKey(
        ClasificacionCFSE, null=True, blank=True, on_delete=models.PROTECT, verbose_name="clasificación CFSE"
    )
    tipo_pago = models.CharField("tipo de pago", max_length=10, choices=TipoPago.choices, default=TipoPago.HORA)
    tarifa = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="Por hora: tarifa por hora. Salario: cantidad por período de pago.",
    )
    horas_regulares_periodo = models.DecimalField(
        "horas regulares por período",
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Para empleados asalariados: horas que cubre el salario (para calcular la tarifa por hora).",
    )
    aplica_choferil = models.BooleanField("aplica Seguro Choferil", default=False)
    recibe_propinas = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)
    fecha_terminacion = models.DateField("fecha de terminación", null=True, blank=True)
    razon_terminacion = models.CharField(
        "razón de terminación", max_length=20, choices=RazonTerminacion.choices, blank=True
    )

    # Retención de Puerto Rico (Formulario 499 R-4)
    r4_estado_civil = models.CharField(
        "estado civil (499 R-4)", max_length=20, choices=EstadoCivilPR.choices, default=EstadoCivilPR.SOLTERO
    )
    r4_exencion_personal = models.CharField(
        "exención personal (499 R-4)", max_length=10, choices=ExencionPersonal.choices, default=ExencionPersonal.COMPLETA
    )
    r4_dependientes = models.PositiveSmallIntegerField("dependientes", default=0)
    r4_dependientes_custodia_compartida = models.PositiveSmallIntegerField("dependientes (custodia compartida)", default=0)
    r4_veterano = models.BooleanField("exención de veterano", default=False)
    r4_concesion_deducciones = models.DecimalField(
        "concesión por deducciones ($ anual)", max_digits=10, decimal_places=2, default=0
    )
    r4_retencion_adicional = models.DecimalField(
        "retención adicional por período ($)", max_digits=10, decimal_places=2, default=0
    )

    # Retención federal (W-4) — solo si aplica
    w4_aplica = models.BooleanField("aplica retención federal (W-4)", default=False)
    w4_estado_civil = models.CharField(
        "estado civil (W-4)", max_length=10, choices=EstadoCivilW4.choices, default=EstadoCivilW4.SOLTERO
    )
    w4_version = models.CharField(
        "versión del W-4", max_length=4, choices=[("2020", "2020 o posterior"), ("2019", "2019 o anterior")],
        default="2020",
    )
    w4_exenciones = models.PositiveSmallIntegerField("W-4 2019 o anterior: exenciones (allowances)", default=0)
    w4_paso2 = models.BooleanField("W-4 paso 2 marcado (múltiples empleos)", default=False)
    w4_dependientes = models.DecimalField("W-4 paso 3: dependientes ($)", max_digits=10, decimal_places=2, default=0)
    w4_otros_ingresos = models.DecimalField("W-4 paso 4(a): otros ingresos ($)", max_digits=10, decimal_places=2, default=0)
    w4_deducciones = models.DecimalField("W-4 paso 4(b): deducciones ($)", max_digits=10, decimal_places=2, default=0)
    w4_retencion_adicional = models.DecimalField(
        "W-4 paso 4(c): retención adicional ($)", max_digits=10, decimal_places=2, default=0
    )

    # Depósito directo (cuenta cifrada)
    deposito_directo = models.BooleanField("depósito directo", default=False)
    banco_nombre = models.CharField("banco", max_length=100, blank=True)
    banco_ruta = models.CharField("número de ruta", max_length=9, blank=True)
    banco_cuenta = CampoCifrado("número de cuenta")
    banco_cuenta_ultimos4 = models.CharField(max_length=4, blank=True, editable=False)
    banco_tipo_cuenta = models.CharField(
        "tipo de cuenta", max_length=10, choices=TipoCuenta.choices, default=TipoCuenta.CHEQUES
    )

    notas = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    CAMPOS_NO_AUDITABLES = ("ssn_indice", "creado", "modificado", "creado_por")

    class Meta:
        ordering = ["apellido_paterno", "apellido_materno", "nombre"]
        constraints = [
            models.UniqueConstraint(fields=["compania", "numero_empleado"], name="empleado_numero_unico"),
            models.UniqueConstraint(fields=["compania", "ssn_indice"], name="empleado_ssn_unico"),
        ]
        indexes = [models.Index(fields=["compania", "activo"])]

    def __str__(self):
        return f"{self.nombre_completo} ({self.numero_empleado})"

    @staticmethod
    def indice_ssn(digitos: str) -> str:
        return cifrado.indice_ciego(digitos, "ssn")

    def asignar_ssn(self, digitos: str):
        self.ssn = digitos
        self.ssn_indice = self.indice_ssn(digitos)
        self.ssn_ultimos4 = digitos[-4:]

    def asignar_cuenta_bancaria(self, cuenta: str | None):
        self.banco_cuenta = cuenta or None
        self.banco_cuenta_ultimos4 = cuenta[-4:] if cuenta else ""

    @property
    def nombre_completo(self):
        partes = [self.nombre, self.segundo_nombre, self.apellido_paterno, self.apellido_materno]
        return " ".join(p for p in partes if p)

    @property
    def ssn_enmascarado(self):
        return formato_ssn_enmascarado(self.ssn_ultimos4)

    @property
    def cuenta_enmascarada(self):
        return f"••••{self.banco_cuenta_ultimos4}" if self.banco_cuenta_ultimos4 else ""

    @property
    def regimen_automatico(self):
        if self.fecha_empleo and self.fecha_empleo < FECHA_LEY_4_2017:
            return self.Regimen.ANTERIOR
        return self.Regimen.LEY4

    @property
    def regimen_efectivo(self):
        return self.regimen_laboral or self.regimen_automatico

    @property
    def regimen_es_manual(self):
        return bool(self.regimen_laboral) and self.regimen_laboral != self.regimen_automatico

    def get_regimen_efectivo_display(self):
        return self.Regimen(self.regimen_efectivo).label
