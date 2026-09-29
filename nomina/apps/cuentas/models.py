from django.contrib.auth.models import AbstractUser, UserManager
from django.db import models


class GestorUsuarios(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("rol", Usuario.Rol.ADMIN)
        return super().create_superuser(username, email, password, **extra_fields)


class Usuario(AbstractUser):
    class Rol(models.TextChoices):
        ADMIN = "admin", "Administrador"
        PREPARADOR = "preparador", "Preparador"
        LECTURA = "lectura", "Solo lectura"

    rol = models.CharField(max_length=20, choices=Rol.choices, default=Rol.LECTURA)
    companias = models.ManyToManyField(
        "companias.Compania",
        blank=True,
        related_name="usuarios",
        verbose_name="compañías asignadas",
        help_text="Los administradores ven todas las compañías.",
    )
    debe_cambiar_contrasena = models.BooleanField(
        default=False, help_text="Obliga a cambiar la contraseña en la próxima entrada."
    )

    objects = GestorUsuarios()

    CAMPOS_NO_AUDITABLES = ("password", "last_login", "date_joined")

    class Meta:
        ordering = ["username"]
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"

    @property
    def es_admin(self) -> bool:
        return self.rol == self.Rol.ADMIN

    @property
    def puede_editar(self) -> bool:
        return self.rol in (self.Rol.ADMIN, self.Rol.PREPARADOR)

    def companias_accesibles(self):
        from apps.companias.models import Compania

        if self.es_admin:
            return Compania.objects.all()
        return self.companias.all()

    def tiene_2fa(self) -> bool:
        from django_otp.plugins.otp_totp.models import TOTPDevice

        return TOTPDevice.objects.filter(user=self, confirmed=True).exists()
