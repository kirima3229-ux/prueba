from django import forms
from django.forms import inlineformset_factory

from apps.empleados.forms import FechaInput

from .models import (
    ConceptoDeduccion,
    ConceptoIngreso,
    ParametrosAnuales,
    ReglaBonoNavidad,
    ReglaHorasExtra,
    ReglaLicencia,
    ReglaMesada,
    SalarioMinimo,
    TramoRetencionPR,
)

CONFIRMAR = "Confirmo que estos valores son correctos (marcar como VERIFICADO)"


class VerificarMixin(forms.Form):
    marcar_verificado = forms.BooleanField(label=CONFIRMAR, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if getattr(self, "instance", None) is not None and self.instance.pk:
            self.fields["marcar_verificado"].initial = self.instance.estado == "verificado"


GRUPOS_PARAMETROS = [
    ("Seguro Social y Medicare", [
        "ss_tasa_empleado", "ss_tasa_patrono", "ss_tope", "medicare_tasa_empleado", "medicare_tasa_patrono",
        "medicare_adicional_tasa", "medicare_adicional_umbral",
    ]),
    ("Desempleo e incapacidad", ["futa_tasa", "futa_tope", "desempleo_tope", "sinot_tope"]),
    ("Seguro Choferil", ["choferil_empleado_semanal", "choferil_patrono_semanal"]),
    ("Retención de Puerto Rico — exenciones", [
        "exencion_personal_individuo", "exencion_personal_casado", "exencion_dependiente",
        "exencion_dependiente_custodia", "exencion_veterano",
    ]),
    ("Vacaciones y enfermedad — general", [
        "horas_por_dia", "limite_patrono_pequeno_licencias", "tope_vacaciones_meses", "tope_enfermedad_dias",
    ]),
]


class ParametrosForm(VerificarMixin, forms.ModelForm):
    class Meta:
        model = ParametrosAnuales
        exclude = ["estado", "verificado_por", "verificado_en", "anio"]
        widgets = {"notas": forms.Textarea(attrs={"rows": 3})}

    def grupos(self):
        for titulo, campos in GRUPOS_PARAMETROS:
            yield titulo, [self[c] for c in campos]


TramosFormSet = inlineformset_factory(
    ParametrosAnuales, TramoRetencionPR, fields=["desde", "hasta", "cuota_fija", "tasa"], extra=1, can_delete=True
)
ReglasFormSet = inlineformset_factory(
    ParametrosAnuales, ReglaHorasExtra,
    fields=["regimen", "diario", "semanal", "septimo_dia", "periodo_alimentos"], extra=0, can_delete=False,
)
LicenciasFormSet = inlineformset_factory(
    ParametrosAnuales, ReglaLicencia,
    fields=["tipo", "regimen", "tamano", "anios_desde", "anios_hasta", "horas_minimas_mes", "dias_por_mes"],
    extra=1, can_delete=True,
)
MesadaFormSet = inlineformset_factory(
    ParametrosAnuales, ReglaMesada,
    fields=["regimen", "anios_desde", "anios_hasta", "meses_sueldo", "semanas_por_anio", "tope_meses"],
    extra=1, can_delete=True,
)
BonoFormSet = inlineformset_factory(
    ParametrosAnuales, ReglaBonoNavidad,
    fields=["regimen", "mes_inicio_periodo", "horas_minimas", "umbral_empleados", "porcentaje_grande", "tope_grande",
            "porcentaje_pequeno", "tope_pequeno", "tope_salario"],
    extra=0, can_delete=False,
)


class CopiarAnioForm(forms.Form):
    origen = forms.ModelChoiceField(label="Copiar desde", queryset=ParametrosAnuales.objects.all())
    anio = forms.IntegerField(label="Año nuevo", min_value=2000, max_value=2100)

    def clean_anio(self):
        anio = self.cleaned_data["anio"]
        if ParametrosAnuales.objects.filter(anio=anio).exists():
            raise forms.ValidationError("Ese año ya existe.")
        return anio


class SalarioMinimoForm(VerificarMixin, forms.ModelForm):
    class Meta:
        model = SalarioMinimo
        fields = ["vigente_desde", "tarifa_hora", "tarifa_propinas", "notas"]
        widgets = {"vigente_desde": FechaInput(), "notas": forms.Textarea(attrs={"rows": 2})}


class ConceptoIngresoForm(VerificarMixin, forms.ModelForm):
    class Meta:
        model = ConceptoIngreso
        fields = [
            "codigo", "nombre", "tributable_pr", "tributable_ss", "tributable_medicare", "tributable_futa",
            "tributable_desempleo", "tributable_sinot", "tributable_cfse", "activo", "notas",
        ]
        widgets = {"notas": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and self.instance.del_sistema:
            self.fields["codigo"].disabled = True


class ConceptoDeduccionForm(VerificarMixin, forms.ModelForm):
    class Meta:
        model = ConceptoDeduccion
        fields = ["codigo", "nombre", "antes_de_pr", "antes_de_federal", "antes_de_fica", "activo", "notas"]
        widgets = {"notas": forms.Textarea(attrs={"rows": 2})}
