from django import forms

from apps.companias.models import ClasificacionCFSE, Departamento
from apps.core.validadores import normalizar_ssn, validar_cuenta_bancaria, validar_ruta_bancaria

from .models import Empleado


class FechaInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


SECCIONES = [
    ("Datos personales", [
        "numero_empleado", "nombre", "segundo_nombre", "apellido_paterno", "apellido_materno",
        "ssn_nuevo", "fecha_nacimiento", "direccion_linea1", "direccion_linea2", "ciudad", "estado",
        "codigo_postal", "telefono", "email",
    ]),
    ("Empleo", [
        "fecha_empleo", "regimen_laboral", "departamento", "clasificacion_cfse", "tipo_pago", "tarifa",
        "horas_regulares_periodo", "aplica_choferil", "recibe_propinas",
    ]),
    ("Retención de Puerto Rico (499 R-4)", [
        "r4_estado_civil", "r4_exencion_personal", "r4_dependientes", "r4_dependientes_custodia_compartida",
        "r4_veterano", "r4_concesion_deducciones", "r4_retencion_adicional",
    ]),
    ("Retención federal (W-4) — solo si aplica", [
        "w4_aplica", "w4_estado_civil", "w4_paso2", "w4_dependientes", "w4_otros_ingresos",
        "w4_deducciones", "w4_retencion_adicional",
    ]),
    ("Depósito directo", [
        "deposito_directo", "banco_nombre", "banco_ruta", "cuenta_nueva", "banco_tipo_cuenta",
    ]),
    ("Otros", ["notas"]),
]


class EmpleadoForm(forms.ModelForm):
    ssn_nuevo = forms.CharField(label="SSN", required=False, max_length=11)
    cuenta_nueva = forms.CharField(label="Número de cuenta", required=False, max_length=20)
    borrar_cuenta = forms.BooleanField(label="Eliminar la cuenta bancaria guardada", required=False)

    class Meta:
        model = Empleado
        exclude = [
            "compania", "ssn", "banco_cuenta", "activo", "fecha_terminacion", "razon_terminacion", "creado_por",
        ]
        widgets = {
            "fecha_nacimiento": FechaInput(),
            "fecha_empleo": FechaInput(),
            "notas": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, compania, **kwargs):
        self.compania = compania
        super().__init__(*args, **kwargs)
        self.fields["departamento"].queryset = Departamento.objects.filter(compania=compania, activo=True)
        self.fields["clasificacion_cfse"].queryset = ClasificacionCFSE.objects.filter(compania=compania, activa=True)
        self.fields["regimen_laboral"].choices = [("", "Automático según fecha de empleo")] + list(
            Empleado.Regimen.choices
        )
        for nombre in ("ssn_nuevo", "cuenta_nueva"):
            self.fields[nombre].widget.attrs["autocomplete"] = "off"
        if self.instance.pk:
            self.fields["ssn_nuevo"].help_text = (
                f"Actual: {self.instance.ssn_enmascarado}. Deje en blanco para no cambiarlo."
            )
            if self.instance.banco_cuenta_ultimos4:
                self.fields["cuenta_nueva"].help_text = (
                    f"Actual: {self.instance.cuenta_enmascarada}. Deje en blanco para no cambiarla."
                )
            else:
                del self.fields["borrar_cuenta"]
        else:
            self.fields["ssn_nuevo"].required = True
            del self.fields["borrar_cuenta"]

    def secciones(self):
        for titulo, nombres in SECCIONES:
            yield titulo, [self[n] for n in nombres if n in self.fields]

    def clean_numero_empleado(self):
        numero = self.cleaned_data["numero_empleado"].strip()
        existe = Empleado.objects.filter(compania=self.compania, numero_empleado=numero).exclude(pk=self.instance.pk)
        if existe.exists():
            raise forms.ValidationError("Ya existe un empleado con ese número en esta compañía.")
        return numero

    def clean_ssn_nuevo(self):
        valor = self.cleaned_data["ssn_nuevo"].strip()
        if not valor:
            return ""
        digitos = normalizar_ssn(valor)
        existe = Empleado.objects.filter(
            compania=self.compania, ssn_indice=Empleado.indice_ssn(digitos)
        ).exclude(pk=self.instance.pk)
        if existe.exists():
            raise forms.ValidationError("Ya existe un empleado con este SSN en esta compañía.")
        return digitos

    def clean_banco_ruta(self):
        valor = self.cleaned_data["banco_ruta"].strip()
        return validar_ruta_bancaria(valor) if valor else ""

    def clean_cuenta_nueva(self):
        valor = self.cleaned_data["cuenta_nueva"].strip()
        return validar_cuenta_bancaria(valor) if valor else ""

    def clean_tarifa(self):
        tarifa = self.cleaned_data["tarifa"]
        if tarifa is not None and tarifa <= 0:
            raise forms.ValidationError("La tarifa debe ser mayor que cero.")
        return tarifa

    def clean(self):
        datos = super().clean()
        nacimiento, empleo = datos.get("fecha_nacimiento"), datos.get("fecha_empleo")
        if nacimiento and empleo and nacimiento >= empleo:
            self.add_error("fecha_nacimiento", "La fecha de nacimiento debe ser anterior a la de empleo.")
        if datos.get("deposito_directo"):
            tiene_cuenta = datos.get("cuenta_nueva") or (
                self.instance.banco_cuenta_ultimos4 and not datos.get("borrar_cuenta")
            )
            if not datos.get("banco_ruta"):
                self.add_error("banco_ruta", "Requerido para depósito directo.")
            if not tiene_cuenta:
                self.add_error("cuenta_nueva", "Requerido para depósito directo.")
        return datos

    def save(self, commit=True):
        empleado = super().save(commit=False)
        empleado.compania = self.compania
        if self.cleaned_data.get("ssn_nuevo"):
            empleado.asignar_ssn(self.cleaned_data["ssn_nuevo"])
        if self.cleaned_data.get("cuenta_nueva"):
            empleado.asignar_cuenta_bancaria(self.cleaned_data["cuenta_nueva"])
        elif self.cleaned_data.get("borrar_cuenta"):
            empleado.asignar_cuenta_bancaria(None)
        if commit:
            empleado.save()
        return empleado


class TerminarEmpleadoForm(forms.ModelForm):
    class Meta:
        model = Empleado
        fields = ["fecha_terminacion", "razon_terminacion"]
        widgets = {"fecha_terminacion": FechaInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fecha_terminacion"].required = True
        self.fields["razon_terminacion"].required = True

    def clean_fecha_terminacion(self):
        fecha = self.cleaned_data["fecha_terminacion"]
        if fecha and self.instance.fecha_empleo and fecha < self.instance.fecha_empleo:
            raise forms.ValidationError("La fecha de terminación no puede ser anterior a la de empleo.")
        return fecha


class ImportarForm(forms.Form):
    archivo = forms.FileField(label="Archivo Excel (.xlsx) o CSV")
    solo_validar = forms.BooleanField(label="Solo validar (no importar)", required=False, initial=True)

    def clean_archivo(self):
        archivo = self.cleaned_data["archivo"]
        nombre = archivo.name.lower()
        if not (nombre.endswith(".xlsx") or nombre.endswith(".csv")):
            raise forms.ValidationError("Solo se aceptan archivos .xlsx o .csv.")
        if archivo.size > 5 * 1024 * 1024:
            raise forms.ValidationError("El archivo no puede pasar de 5 MB.")
        return archivo
