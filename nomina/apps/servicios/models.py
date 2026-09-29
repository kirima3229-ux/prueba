"""
Proveedores de servicios prestados (contratistas que no son empleados).

A los pagos por servicios prestados se les aplica retención en el origen y se
informan en la declaración informativa de servicios prestados. El registro de
pagos, el cálculo de la retención (tasa configurable por año) y los
formularios se añaden en las fases 2 a 4. Aquí solo están los datos maestros.
"""

from datetime import date

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.companias.models import Compania, EstadoVerificacion
from apps.core import cifrado
from apps.core.campos import CampoCifrado

from .calculo import Tratamiento


class ProveedorServicios(models.Model):
    class TipoPersona(models.TextChoices):
        INDIVIDUO = "individuo", "Individuo"
        ENTIDAD = "entidad", "Entidad (corporación, sociedad, LLC)"

    class TipoIdentificacion(models.TextChoices):
        SSN = "ssn", "SSN"
        EIN = "ein", "EIN"

    class Relevo(models.TextChoices):
        NINGUNO = "ninguno", "Sin relevo (retención completa)"
        PARCIAL = "parcial", "Relevo parcial"
        TOTAL = "total", "Relevo total"
        DECLARACION_JURADA = "declaracion_jurada", "Exento — Sección 1062.03(b) (declaración jurada)"

    class TipoCuenta(models.TextChoices):
        CHEQUES = "cheques", "Cheques"
        AHORROS = "ahorros", "Ahorros"

    compania = models.ForeignKey(Compania, on_delete=models.PROTECT, related_name="proveedores_servicios")
    numero = models.CharField("número de proveedor", max_length=20)
    tipo_persona = models.CharField("tipo", max_length=10, choices=TipoPersona.choices, default=TipoPersona.INDIVIDUO)

    # Individuo: nombre y apellidos. Entidad: razón social en "nombre".
    nombre = models.CharField("nombre o razón social", max_length=150)
    segundo_nombre = models.CharField("segundo nombre", max_length=60, blank=True)
    apellido_paterno = models.CharField("apellido paterno", max_length=60, blank=True)
    apellido_materno = models.CharField("apellido materno", max_length=60, blank=True)
    nombre_comercial = models.CharField("nombre comercial", max_length=150, blank=True)

    tipo_identificacion = models.CharField(
        "tipo de identificación", max_length=3, choices=TipoIdentificacion.choices, default=TipoIdentificacion.SSN
    )
    identificacion = CampoCifrado("número de identificación")
    identificacion_indice = models.CharField(max_length=64, editable=False, db_index=True)
    identificacion_ultimos4 = models.CharField(max_length=4, editable=False)

    direccion_linea1 = models.CharField("dirección", max_length=200, blank=True)
    direccion_linea2 = models.CharField("dirección (línea 2)", max_length=200, blank=True)
    ciudad = models.CharField(max_length=100, blank=True)
    estado = models.CharField(max_length=2, default="PR")
    codigo_postal = models.CharField("código postal", max_length=10, blank=True)
    telefono = models.CharField("teléfono", max_length=20, blank=True)
    email = models.EmailField(blank=True)

    descripcion_servicio = models.CharField("servicio que presta", max_length=200, blank=True)
    fecha_inicio = models.DateField("fecha de inicio", null=True, blank=True)

    # Relevo de retención emitido por Hacienda.
    relevo = models.CharField("relevo de retención", max_length=20, choices=Relevo.choices, default=Relevo.NINGUNO)
    relevo_porcentaje = models.DecimalField(
        "porcentaje de retención con relevo parcial (%)",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Solo para relevo parcial: el porcentaje que indica el certificado.",
    )
    relevo_vigente_hasta = models.DateField("relevo vigente hasta", null=True, blank=True)
    relevo_numero = models.CharField("número del certificado de relevo", max_length=50, blank=True)

    deposito_directo = models.BooleanField("depósito directo", default=False)
    banco_nombre = models.CharField("banco", max_length=100, blank=True)
    banco_ruta = models.CharField("número de ruta", max_length=9, blank=True)
    banco_cuenta = CampoCifrado("número de cuenta")
    banco_cuenta_ultimos4 = models.CharField(max_length=4, blank=True, editable=False)
    banco_tipo_cuenta = models.CharField(
        "tipo de cuenta", max_length=10, choices=TipoCuenta.choices, default=TipoCuenta.CHEQUES
    )

    activo = models.BooleanField(default=True)
    notas = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    modificado = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    CAMPOS_NO_AUDITABLES = ("identificacion_indice", "creado", "modificado", "creado_por")

    class Meta:
        ordering = ["nombre", "apellido_paterno"]
        verbose_name = "proveedor de servicios"
        verbose_name_plural = "proveedores de servicios"
        constraints = [
            models.UniqueConstraint(fields=["compania", "numero"], name="proveedor_numero_unico"),
            models.UniqueConstraint(fields=["compania", "identificacion_indice"], name="proveedor_identificacion_unica"),
        ]

    def __str__(self):
        return f"{self.nombre_mostrar} ({self.numero})"

    @staticmethod
    def indice_identificacion(tipo: str, digitos: str) -> str:
        # Mismo contexto que empleados/compañías: se puede cruzar sin descifrar.
        return cifrado.indice_ciego(digitos, tipo)

    def asignar_identificacion(self, tipo: str, digitos: str):
        self.tipo_identificacion = tipo
        self.identificacion = digitos
        self.identificacion_indice = self.indice_identificacion(tipo, digitos)
        self.identificacion_ultimos4 = digitos[-4:]

    def asignar_cuenta_bancaria(self, cuenta: str | None):
        self.banco_cuenta = cuenta or None
        self.banco_cuenta_ultimos4 = cuenta[-4:] if cuenta else ""

    @property
    def nombre_mostrar(self):
        if self.tipo_persona == self.TipoPersona.ENTIDAD:
            return self.nombre_comercial or self.nombre
        partes = [self.nombre, self.segundo_nombre, self.apellido_paterno, self.apellido_materno]
        return " ".join(p for p in partes if p)

    @property
    def identificacion_enmascarada(self):
        if not self.identificacion_ultimos4:
            return ""
        if self.tipo_identificacion == self.TipoIdentificacion.EIN:
            return f"XX-XXX{self.identificacion_ultimos4}"
        return f"XXX-XX-{self.identificacion_ultimos4}"

    @property
    def cuenta_enmascarada(self):
        return f"••••{self.banco_cuenta_ultimos4}" if self.banco_cuenta_ultimos4 else ""

    def relevo_vigente(self, fecha: date | None = None) -> bool:
        """Un relevo vencido deja de aplicar: se retiene la tasa completa."""
        if self.relevo == self.Relevo.NINGUNO:
            return False
        if self.relevo_vigente_hasta is None:
            return True
        return (fecha or date.today()) <= self.relevo_vigente_hasta

    @property
    def relevo_vencido(self) -> bool:
        return self.relevo != self.Relevo.NINGUNO and not self.relevo_vigente()

    def tratamiento_en(self, fecha: date):
        """Tratamiento de retención que corresponde a un pago en `fecha`."""
        if not self.relevo_vigente(fecha):
            return Tratamiento.GENERAL, None
        return {
            self.Relevo.PARCIAL: (Tratamiento.RELEVO_PARCIAL, self.relevo_porcentaje),
            self.Relevo.TOTAL: (Tratamiento.RELEVO_TOTAL, None),
            self.Relevo.DECLARACION_JURADA: (Tratamiento.DECLARACION_JURADA, None),
        }[self.relevo]


class ConfigRetencionServicios(models.Model):
    """Tasa y exención de la retención por servicios prestados, por año natural."""

    anio = models.PositiveSmallIntegerField(
        "año", unique=True, validators=[MinValueValidator(2000), MaxValueValidator(2100)]
    )
    tasa_general = models.DecimalField(
        "tasa de retención (%)", max_digits=5, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    exencion_anual = models.DecimalField(
        "exención anual por proveedor ($)", max_digits=10, decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text="Los primeros $ pagados en el año a cada proveedor no llevan retención.",
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
        verbose_name = "configuración de retención por servicios prestados"

    def __str__(self):
        return f"Retención servicios prestados {self.anio}"


class ErrorPagoInmutable(Exception):
    pass


class PagoServicio(models.Model):
    """
    Pago a un proveedor de servicios. Una vez registrado no se edita: si hay
    un error se anula (con motivo) y se registra de nuevo. Los valores del
    cálculo quedan guardados tal como se aplicaron.
    """

    class Metodo(models.TextChoices):
        CHEQUE = "cheque", "Cheque"
        DEPOSITO = "deposito", "Depósito directo"
        TRANSFERENCIA = "transferencia", "Transferencia / ACH"
        EFECTIVO = "efectivo", "Efectivo"
        OTRO = "otro", "Otro"

    class Origen(models.TextChoices):
        MANUAL = "manual", "Registro manual"
        IMPORTADO = "importado", "Importado de Excel/CSV"
        NOMINA = "nomina", "Ciclo de nómina"

    class Estado(models.TextChoices):
        REGISTRADO = "registrado", "Registrado"
        ANULADO = "anulado", "Anulado"

    compania = models.ForeignKey(Compania, on_delete=models.PROTECT, related_name="pagos_servicios")
    proveedor = models.ForeignKey(ProveedorServicios, on_delete=models.PROTECT, related_name="pagos")
    fecha = models.DateField("fecha del pago")
    anio = models.PositiveSmallIntegerField("año", db_index=True, editable=False)
    referencia = models.CharField("factura / referencia", max_length=50, blank=True)
    descripcion = models.CharField("descripción", max_length=200, blank=True)
    metodo = models.CharField("método de pago", max_length=15, choices=Metodo.choices, default=Metodo.CHEQUE)
    numero_cheque = models.CharField("número de cheque", max_length=30, blank=True)
    origen = models.CharField(max_length=10, choices=Origen.choices, default=Origen.MANUAL)

    # Resultado del cálculo (se guarda tal como se aplicó).
    monto = models.DecimalField("monto bruto", max_digits=12, decimal_places=2)
    acumulado_previo = models.DecimalField(max_digits=12, decimal_places=2)
    exencion_aplicada = models.DecimalField(max_digits=12, decimal_places=2)
    base_sujeta = models.DecimalField("cantidad sujeta", max_digits=12, decimal_places=2)
    tasa_aplicada = models.DecimalField("tasa aplicada (%)", max_digits=5, decimal_places=2)
    tratamiento = models.CharField(max_length=20, choices=Tratamiento.CHOICES)
    retencion = models.DecimalField("retención", max_digits=12, decimal_places=2)
    neto = models.DecimalField("neto pagado", max_digits=12, decimal_places=2)
    explicacion = models.TextField()
    motivo_exencion = models.CharField("motivo de la exención", max_length=200, blank=True)
    config_verificada = models.BooleanField(default=False)

    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.REGISTRADO)
    motivo_anulacion = models.CharField("motivo de la anulación", max_length=200, blank=True)
    anulado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    anulado_en = models.DateTimeField(null=True, blank=True)

    deposito = models.ForeignKey(
        "DepositoRetencion", null=True, blank=True, on_delete=models.PROTECT, related_name="pagos"
    )

    creado = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    # Únicos campos que cambian después de registrar: la anulación y el depósito.
    CAMPOS_ANULACION = {"estado", "motivo_anulacion", "anulado_por", "anulado_en", "deposito"}

    class Meta:
        ordering = ["-fecha", "-id"]
        indexes = [models.Index(fields=["compania", "anio", "estado"]), models.Index(fields=["proveedor", "anio"])]
        verbose_name = "pago por servicios prestados"
        verbose_name_plural = "pagos por servicios prestados"

    def __str__(self):
        return f"Pago {self.pk} — {self.proveedor.nombre_mostrar} ${self.monto:,.2f} ({self.fecha:%m/%d/%Y})"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            campos = set(kwargs.get("update_fields") or ())
            if not campos or not campos <= self.CAMPOS_ANULACION:
                raise ErrorPagoInmutable("Un pago registrado no se modifica; anúlelo y registre uno nuevo.")
        self.anio = self.fecha.year
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ErrorPagoInmutable("Los pagos no se borran; se anulan.")


class DepositoRetencion(models.Model):
    """
    Depósito en Hacienda de la retención por servicios prestados de un rango
    de fechas. Agrupa los pagos con retención de ese rango. No se edita: si se
    registró por error, se anula (los pagos quedan pendientes otra vez).
    """

    class Estado(models.TextChoices):
        REGISTRADO = "registrado", "Registrado"
        ANULADO = "anulado", "Anulado"

    compania = models.ForeignKey(Compania, on_delete=models.PROTECT, related_name="depositos_retencion")
    desde = models.DateField("pagos desde")
    hasta = models.DateField("pagos hasta")
    fecha_deposito = models.DateField("fecha del depósito")
    confirmacion = models.CharField("número de confirmación (SURI)", max_length=60, blank=True)
    monto = models.DecimalField("monto depositado", max_digits=12, decimal_places=2)
    notas = models.CharField(max_length=200, blank=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.REGISTRADO)
    motivo_anulacion = models.CharField(max_length=200, blank=True)
    anulado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    anulado_en = models.DateTimeField(null=True, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    CAMPOS_ANULACION = {"estado", "motivo_anulacion", "anulado_por", "anulado_en"}

    class Meta:
        ordering = ["-hasta", "-id"]
        verbose_name = "depósito de retención"
        verbose_name_plural = "depósitos de retención"

    def __str__(self):
        return f"Depósito {self.desde:%m/%d/%Y}–{self.hasta:%m/%d/%Y} ${self.monto:,.2f}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            campos = set(kwargs.get("update_fields") or ())
            if not campos or not campos <= self.CAMPOS_ANULACION:
                raise ErrorPagoInmutable("Un depósito registrado no se modifica; anúlelo y regístrelo de nuevo.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ErrorPagoInmutable("Los depósitos no se borran; se anulan.")

    def retencion_actual(self) -> Decimal:
        """Retención de los pagos incluidos que siguen activos (cambia si se anula un pago)."""
        total = self.pagos.filter(estado=PagoServicio.Estado.REGISTRADO).aggregate(t=models.Sum("retencion"))["t"]
        return total or Decimal("0")

    @property
    def diferencia(self) -> Decimal:
        if self.estado == self.Estado.ANULADO:
            return Decimal("0")
        return self.monto - self.retencion_actual()


def acumulado_del_anio(proveedor, anio: int) -> Decimal:
    total = (
        PagoServicio.objects.filter(proveedor=proveedor, anio=anio, estado=PagoServicio.Estado.REGISTRADO)
        .aggregate(total=models.Sum("monto"))["total"]
    )
    return total or Decimal("0")
