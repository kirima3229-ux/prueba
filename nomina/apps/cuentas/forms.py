from django import forms
from django.contrib.auth import password_validation

from apps.companias.models import Compania

from .models import Usuario


class EntradaForm(forms.Form):
    username = forms.CharField(label="Usuario", max_length=150, widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}))
    password = forms.CharField(label="Contraseña", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class CodigoOTPForm(forms.Form):
    codigo = forms.RegexField(
        label="Código de 6 dígitos",
        regex=r"^\d{6}$",
        error_messages={"invalid": "El código debe tener 6 dígitos."},
        widget=forms.TextInput(
            attrs={"autofocus": True, "autocomplete": "one-time-code", "inputmode": "numeric", "maxlength": 6}
        ),
    )


class _ContrasenaNuevaMixin(forms.Form):
    nueva1 = forms.CharField(
        label="Contraseña nueva",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Mínimo 12 caracteres. No use contraseñas comunes ni parecidas a su usuario.",
    )
    nueva2 = forms.CharField(
        label="Confirme la contraseña nueva",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )

    def _usuario_para_validar(self):
        return getattr(self, "usuario", None)

    def clean(self):
        datos = super().clean()
        n1, n2 = datos.get("nueva1"), datos.get("nueva2")
        if n1 and n2 and n1 != n2:
            self.add_error("nueva2", "Las contraseñas no coinciden.")
        elif n1:
            try:
                password_validation.validate_password(n1, self._usuario_para_validar())
            except forms.ValidationError as error:
                self.add_error("nueva1", error)
        return datos


class CambiarContrasenaForm(_ContrasenaNuevaMixin):
    actual = forms.CharField(
        label="Contraseña actual",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )
    field_order = ["actual", "nueva1", "nueva2"]

    def __init__(self, usuario, *args, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)

    def clean_actual(self):
        actual = self.cleaned_data["actual"]
        if not self.usuario.check_password(actual):
            raise forms.ValidationError("La contraseña actual no es correcta.")
        return actual

    def clean(self):
        datos = super().clean()
        if datos.get("actual") and datos.get("actual") == datos.get("nueva1"):
            self.add_error("nueva1", "La contraseña nueva debe ser distinta de la actual.")
        return datos


class RestablecerContrasenaForm(_ContrasenaNuevaMixin):
    def __init__(self, usuario, *args, **kwargs):
        self.usuario = usuario
        super().__init__(*args, **kwargs)


class ConfirmarPasswordForm(forms.Form):
    password = forms.CharField(label="Su contraseña", strip=False, widget=forms.PasswordInput)
    codigo = forms.RegexField(label="Código 2FA actual", regex=r"^\d{6}$")


class _UsuarioBaseForm(forms.ModelForm):
    companias = forms.ModelMultipleChoiceField(
        label="Compañías asignadas",
        queryset=Compania.objects.filter(activa=True),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Los administradores tienen acceso a todas las compañías.",
    )

    class Meta:
        model = Usuario
        fields = ["username", "first_name", "last_name", "email", "rol", "companias"]
        labels = {"username": "Usuario", "first_name": "Nombre", "last_name": "Apellidos", "email": "Email"}


class UsuarioCrearForm(_ContrasenaNuevaMixin, _UsuarioBaseForm):
    class Meta(_UsuarioBaseForm.Meta):
        pass

    def _usuario_para_validar(self):
        return Usuario(
            username=self.cleaned_data.get("username", ""),
            first_name=self.cleaned_data.get("first_name", ""),
            last_name=self.cleaned_data.get("last_name", ""),
            email=self.cleaned_data.get("email", ""),
        )

    def save(self, commit=True):
        usuario = super().save(commit=False)
        usuario.set_password(self.cleaned_data["nueva1"])
        usuario.debe_cambiar_contrasena = True
        if commit:
            usuario.save()
            self.save_m2m()
        return usuario


class UsuarioEditarForm(_UsuarioBaseForm):
    class Meta(_UsuarioBaseForm.Meta):
        fields = _UsuarioBaseForm.Meta.fields + ["is_active"]
        labels = {**_UsuarioBaseForm.Meta.labels, "is_active": "Activo"}

    def __init__(self, *args, editor=None, **kwargs):
        self.editor = editor
        super().__init__(*args, **kwargs)

    def clean(self):
        datos = super().clean()
        if self.editor is not None and self.instance.pk == self.editor.pk:
            if datos.get("rol") != Usuario.Rol.ADMIN:
                self.add_error("rol", "No puede quitarse a sí mismo el rol de administrador.")
            if not datos.get("is_active"):
                self.add_error("is_active", "No puede desactivar su propia cuenta.")
        return datos
