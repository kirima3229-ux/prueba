from django import forms

from apps.core.validadores import normalizar_ein

from .models import ClasificacionCFSE, Compania, Departamento, TasaCFSE, TasasCompania

CAMPOS_CIFRADOS = {
    "registro_comerciante": "número de registro de comerciante",
    "cuenta_patronal_dtrh": "cuenta patronal DTRH",
    "poliza_cfse": "póliza CFSE",
}


class CompaniaForm(forms.ModelForm):
    """
    Los números patronales no se muestran completos: el campo aparece vacío
    y solo se cambia si se escribe un valor nuevo.
    """

    ein_nuevo = forms.CharField(label="EIN", required=False, max_length=12)
    registro_comerciante_nuevo = forms.CharField(label="Registro de comerciante (Hacienda)", required=False, max_length=30)
    cuenta_patronal_dtrh_nuevo = forms.CharField(
        label="Cuenta patronal DTRH (desempleo e incapacidad)", required=False, max_length=30
    )
    poliza_cfse_nuevo = forms.CharField(label="Póliza CFSE", required=False, max_length=30)

    class Meta:
        model = Compania
        fields = [
            "nombre",
            "nombre_comercial",
            "industria",
            "direccion_linea1",
            "direccion_linea2",
            "ciudad",
            "estado",
            "codigo_postal",
            "telefono",
            "persona_contacto",
            "email_contacto",
            "frecuencia_pago",
            "frecuencia_deposito",
            "numero_empleados",
            "activa",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instancia = self.instance
        if instancia.pk:
            ayuda = "Actual: {}. Deje en blanco para no cambiarlo."
            self.fields["ein_nuevo"].help_text = ayuda.format(instancia.ein_enmascarado or "—")
            self.fields["registro_comerciante_nuevo"].help_text = ayuda.format(
                instancia.registro_comerciante_enmascarado or "—"
            )
            self.fields["cuenta_patronal_dtrh_nuevo"].help_text = ayuda.format(
                instancia.cuenta_dtrh_enmascarada or "—"
            )
            self.fields["poliza_cfse_nuevo"].help_text = ayuda.format(instancia.poliza_cfse_enmascarada or "—")
        else:
            self.fields["ein_nuevo"].required = True
        for nombre in ("ein_nuevo", "registro_comerciante_nuevo", "cuenta_patronal_dtrh_nuevo", "poliza_cfse_nuevo"):
            self.fields[nombre].widget.attrs["autocomplete"] = "off"

    def clean_ein_nuevo(self):
        valor = self.cleaned_data["ein_nuevo"].strip()
        if not valor:
            return ""
        digitos = normalizar_ein(valor)
        from apps.core import cifrado

        indice = cifrado.indice_ciego(digitos, "ein")
        duplicado = Compania.objects.filter(ein_indice=indice).exclude(pk=self.instance.pk)
        if duplicado.exists():
            raise forms.ValidationError("Ya existe otra compañía con este EIN.")
        return digitos

    def _limpiar_numero(self, nombre):
        return self.cleaned_data[nombre].strip().replace(" ", "")

    def clean_registro_comerciante_nuevo(self):
        return self._limpiar_numero("registro_comerciante_nuevo")

    def clean_cuenta_patronal_dtrh_nuevo(self):
        return self._limpiar_numero("cuenta_patronal_dtrh_nuevo")

    def clean_poliza_cfse_nuevo(self):
        return self._limpiar_numero("poliza_cfse_nuevo")

    def save(self, commit=True):
        compania = super().save(commit=False)
        if self.cleaned_data.get("ein_nuevo"):
            compania.asignar_ein(self.cleaned_data["ein_nuevo"])
        for campo in CAMPOS_CIFRADOS:
            valor = self.cleaned_data.get(f"{campo}_nuevo")
            if valor:
                setattr(compania, campo, valor)
        if commit:
            compania.save()
        return compania


class TasasCompaniaForm(forms.ModelForm):
    marcar_verificado = forms.BooleanField(
        label="Confirmo que estas tasas son correctas (marcar como VERIFICADO)", required=False
    )

    class Meta:
        model = TasasCompania
        fields = [
            "anio",
            "suta_tasa",
            "aportacion_especial_tasa",
            "sinot_empleado_tasa",
            "sinot_patrono_tasa",
            "notas",
        ]
        widgets = {"notas": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, compania=None, **kwargs):
        self.compania = compania
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["anio"].disabled = True
            self.fields["marcar_verificado"].initial = self.instance.estado == "verificado"

    def clean_anio(self):
        anio = self.cleaned_data["anio"]
        existe = TasasCompania.objects.filter(compania=self.compania, anio=anio).exclude(pk=self.instance.pk)
        if existe.exists():
            raise forms.ValidationError("Ya hay tasas para ese año. Edítelas en lugar de crear otras.")
        return anio


class DepartamentoForm(forms.ModelForm):
    class Meta:
        model = Departamento
        fields = ["nombre", "codigo", "activo"]

    def __init__(self, *args, compania=None, **kwargs):
        self.compania = compania
        super().__init__(*args, **kwargs)

    def clean_nombre(self):
        nombre = self.cleaned_data["nombre"].strip()
        if Departamento.objects.filter(compania=self.compania, nombre__iexact=nombre).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe un departamento con ese nombre.")
        return nombre


class ClasificacionCFSEForm(forms.ModelForm):
    class Meta:
        model = ClasificacionCFSE
        fields = ["codigo", "descripcion", "activa"]

    def __init__(self, *args, compania=None, **kwargs):
        self.compania = compania
        super().__init__(*args, **kwargs)

    def clean_codigo(self):
        codigo = self.cleaned_data["codigo"].strip()
        if ClasificacionCFSE.objects.filter(compania=self.compania, codigo__iexact=codigo).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe esa clasificación.")
        return codigo


class TasaCFSEForm(forms.ModelForm):
    marcar_verificado = forms.BooleanField(label="Confirmo que la tasa es correcta (VERIFICADO)", required=False)

    class Meta:
        model = TasaCFSE
        fields = ["anio", "tasa_por_100"]

    def __init__(self, *args, clasificacion=None, **kwargs):
        self.clasificacion = clasificacion
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["anio"].disabled = True
            self.fields["marcar_verificado"].initial = self.instance.estado == "verificado"

    def clean_anio(self):
        anio = self.cleaned_data["anio"]
        if TasaCFSE.objects.filter(clasificacion=self.clasificacion, anio=anio).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya hay una tasa para ese año.")
        return anio
