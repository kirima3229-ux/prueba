"""
Proveedores de servicios prestados (contratistas que no son empleados).

A los pagos por servicios prestados se les aplica retención en el origen y se
informan en la declaración informativa de servicios prestados. El registro de
pagos, el cálculo de la retención (tasa configurable por año) y los
formularios se añaden en las fases 2 a 4. Aquí solo están los datos maestros.
"""

from datetime import date

from django.conf import settings
from django.db import models

from apps.companias.models import Compania
from apps.core import cifrado
from apps.core.campos import CampoCifrado


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
    relevo = models.CharField("relevo de retención", max_length=10, choices=Relevo.choices, default=Relevo.NINGUNO)
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
