import hashlib
import json
from datetime import timezone as dt_timezone

from django.conf import settings
from django.db import models
from django.utils import timezone


class ErrorInmutable(Exception):
    pass


class Accion(models.TextChoices):
    LOGIN = "login", "Inicio de sesión"
    LOGIN_FALLIDO = "login_fallido", "Intento de entrada fallido"
    LOGOUT = "logout", "Cierre de sesión"
    BLOQUEO = "bloqueo", "Cuenta bloqueada"
    DESBLOQUEO = "desbloqueo", "Cuenta desbloqueada"
    OTP_CONFIGURADO = "otp_configurado", "2FA configurado"
    OTP_ELIMINADO = "otp_eliminado", "2FA eliminado"
    CONTRASENA_CAMBIADA = "contrasena_cambiada", "Contraseña cambiada"
    CONTRASENA_RESTABLECIDA = "contrasena_restablecida", "Contraseña restablecida por administrador"
    USUARIO_CREADO = "usuario_creado", "Usuario creado"
    USUARIO_MODIFICADO = "usuario_modificado", "Usuario modificado"
    COMPANIA_CREADA = "compania_creada", "Compañía creada"
    COMPANIA_MODIFICADA = "compania_modificada", "Compañía modificada"
    TASAS_MODIFICADAS = "tasas_modificadas", "Tasas modificadas"
    CATALOGO_MODIFICADO = "catalogo_modificado", "Catálogo modificado"
    EMPLEADO_CREADO = "empleado_creado", "Empleado creado"
    EMPLEADO_MODIFICADO = "empleado_modificado", "Empleado modificado"
    EMPLEADO_TERMINADO = "empleado_terminado", "Empleado terminado"
    EMPLEADOS_IMPORTADOS = "empleados_importados", "Empleados importados"
    PROVEEDOR_CREADO = "proveedor_creado", "Proveedor de servicios creado"
    PROVEEDOR_MODIFICADO = "proveedor_modificado", "Proveedor de servicios modificado"
    PROVEEDORES_IMPORTADOS = "proveedores_importados", "Proveedores de servicios importados"
    PAGO_SERVICIO_REGISTRADO = "pago_servicio_registrado", "Pago por servicios registrado"
    PAGO_SERVICIO_ANULADO = "pago_servicio_anulado", "Pago por servicios anulado"
    PAGOS_IMPORTADOS = "pagos_importados", "Pagos por servicios importados"
    DEPOSITO_REGISTRADO = "deposito_registrado", "Depósito de retención registrado"
    DEPOSITO_ANULADO = "deposito_anulado", "Depósito de retención anulado"
    LICENCIAS_ACUMULADAS = "licencias_acumuladas", "Vacaciones/enfermedad acumuladas"
    LICENCIA_MOVIMIENTO = "licencia_movimiento", "Movimiento de vacaciones/enfermedad"
    BONO_CALCULADO = "bono_calculado", "Bono de Navidad calculado"
    PERIODO_CREADO = "periodo_creado", "Período de nómina creado"
    NOMINA_ENTRADAS = "nomina_entradas", "Horas/ingresos de nómina modificados"
    NOMINA_CALCULADA = "nomina_calculada", "Pre-nómina calculada"
    DEDUCCION_RECURRENTE = "deduccion_recurrente", "Deducción recurrente modificada"
    CONFIGURACION_MODIFICADA = "configuracion_modificada", "Configuración modificada"
    NOMINA_PROCESADA = "nomina_procesada", "Nómina procesada"
    NOMINA_REVERSADA = "nomina_reversada", "Nómina reversada"
    ARCHIVO_GENERADO = "archivo_generado", "Archivo generado"
    CHEQUE_EMITIDO = "cheque_emitido", "Cheques emitidos"
    CHEQUE_ANULADO = "cheque_anulado", "Cheque anulado"
    FORMATO_CHEQUE = "formato_cheque", "Formato de cheques modificado"
    CONFIG_NACHA = "config_nacha", "Datos bancarios de depósito directo modificados"
    CUENTAS_CONTABLES = "cuentas_contables", "Cuentas contables modificadas"
    ACCESO_DENEGADO = "acceso_denegado", "Acceso denegado"


class RegistroQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ErrorInmutable("La bitácora de auditoría es inmutable.")

    def delete(self):
        raise ErrorInmutable("La bitácora de auditoría es inmutable.")


class RegistroAuditoria(models.Model):
    """
    Registro inmutable. Protección en tres capas:
    1. El modelo rechaza update/delete.
    2. Triggers en la base de datos rechazan UPDATE/DELETE/TRUNCATE.
    3. Cadena de hashes: cada registro incluye el hash del anterior, así que
       cualquier alteración directa se detecta con `verificar_auditoria`.
    """

    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    usuario_nombre = models.CharField(max_length=150, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    accion = models.CharField(max_length=40, choices=Accion.choices, db_index=True)
    compania_id = models.BigIntegerField(null=True, blank=True, db_index=True)
    compania_nombre = models.CharField(max_length=200, blank=True)
    objeto_tipo = models.CharField(max_length=100, blank=True)
    objeto_id = models.CharField(max_length=64, blank=True)
    objeto_repr = models.CharField(max_length=255, blank=True)
    descripcion = models.TextField(blank=True)
    cambios = models.JSONField(default=dict, blank=True)
    hash_anterior = models.CharField(max_length=64)
    hash = models.CharField(max_length=64, unique=True)

    objects = RegistroQuerySet.as_manager()

    class Meta:
        ordering = ["-id"]
        verbose_name = "registro de auditoría"
        verbose_name_plural = "bitácora de auditoría"
        indexes = [models.Index(fields=["objeto_tipo", "objeto_id"])]

    def __str__(self):
        return f"{self.fecha:%Y-%m-%d %H:%M} {self.usuario_nombre} {self.get_accion_display()}"

    def contenido_para_hash(self) -> str:
        datos = {
            "fecha": self.fecha.astimezone(dt_timezone.utc).isoformat(),
            "usuario_id": self.usuario_id,
            "usuario_nombre": self.usuario_nombre,
            "ip": self.ip,
            "accion": self.accion,
            "compania_id": self.compania_id,
            "compania_nombre": self.compania_nombre,
            "objeto_tipo": self.objeto_tipo,
            "objeto_id": self.objeto_id,
            "objeto_repr": self.objeto_repr,
            "descripcion": self.descripcion,
            "cambios": self.cambios,
        }
        return json.dumps(datos, sort_keys=True, ensure_ascii=False, separators=(",", ":"))

    def calcular_hash(self) -> str:
        return hashlib.sha256(
            (self.hash_anterior + self.contenido_para_hash()).encode("utf-8")
        ).hexdigest()

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ErrorInmutable("La bitácora de auditoría es inmutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ErrorInmutable("La bitácora de auditoría es inmutable.")
