from django import forms

from apps.core.validadores import (
    normalizar_ein,
    normalizar_ssn,
    validar_cuenta_bancaria,
    validar_ruta_bancaria,
)
from apps.empleados.forms import FechaInput

from .models import ProveedorServicios

SECCIONES = [
    ("Identificación", [
        "numero", "tipo_persona", "nombre", "segundo_nombre", "apellido_paterno", "apellido_materno",
        "nombre_comercial", "tipo_identificacion", "identificacion_nueva",
    ]),
    ("Dirección y contacto", [
        "direccion_linea1", "direccion_linea2", "ciudad", "estado", "codigo_postal", "telefono", "email",
    ]),
    ("Servicio", ["descripcion_servicio", "fecha_inicio"]),
    ("Relevo de retención (Hacienda)", [
        "relevo", "relevo_porcentaje", "relevo_vigente_hasta", "relevo_numero",
    ]),
    ("Depósito directo", [
        "deposito_directo", "banco_nombre", "banco_ruta", "cuenta_nueva", "borrar_cuenta", "banco_tipo_cuenta",
    ]),
    ("Otros", ["notas"]),
]


class ProveedorServiciosForm(forms.ModelForm):
    identificacion_nueva = forms.CharField(label="Número de identificación (SSN o EIN)", required=False, max_length=11)
    cuenta_nueva = forms.CharField(label="Número de cuenta", required=False, max_length=20)
    borrar_cuenta = forms.BooleanField(label="Eliminar la cuenta bancaria guardada", required=False)

    class Meta:
        model = ProveedorServicios
        exclude = ["compania", "identificacion", "banco_cuenta", "activo", "creado_por"]
        widgets = {
            "fecha_inicio": FechaInput(),
            "relevo_vigente_hasta": FechaInput(),
            "notas": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, compania, **kwargs):
        self.compania = compania
        super().__init__(*args, **kwargs)
        for nombre in ("identificacion_nueva", "cuenta_nueva"):
            self.fields[nombre].widget.attrs["autocomplete"] = "off"
        if self.instance.pk:
            self.fields["identificacion_nueva"].help_text = (
                f"Actual: {self.instance.identificacion_enmascarada}. Deje en blanco para no cambiarlo."
            )
            if self.instance.banco_cuenta_ultimos4:
                self.fields["cuenta_nueva"].help_text = (
                    f"Actual: {self.instance.cuenta_enmascarada}. Deje en blanco para no cambiarla."
                )
            else:
                del self.fields["borrar_cuenta"]
        else:
            self.fields["identificacion_nueva"].required = True
            del self.fields["borrar_cuenta"]
        self.fields["nombre"].help_text = "Individuo: primer nombre. Entidad: razón social."

    def secciones(self):
        for titulo, nombres in SECCIONES:
            yield titulo, [self[n] for n in nombres if n in self.fields]

    def clean_numero(self):
        numero = self.cleaned_data["numero"].strip()
        existe = ProveedorServicios.objects.filter(compania=self.compania, numero=numero).exclude(pk=self.instance.pk)
        if existe.exists():
            raise forms.ValidationError("Ya existe un proveedor con ese número en esta compañía.")
        return numero

    def clean_banco_ruta(self):
        valor = self.cleaned_data["banco_ruta"].strip()
        return validar_ruta_bancaria(valor) if valor else ""

    def clean_cuenta_nueva(self):
        valor = self.cleaned_data["cuenta_nueva"].strip()
        return validar_cuenta_bancaria(valor) if valor else ""

    def clean(self):
        datos = super().clean()
        tipo_persona = datos.get("tipo_persona")
        tipo_id = datos.get("tipo_identificacion")

        if tipo_persona == ProveedorServicios.TipoPersona.INDIVIDUO and not datos.get("apellido_paterno"):
            self.add_error("apellido_paterno", "Requerido para individuos.")

        # La identificación se valida según su tipo (SSN o EIN).
        texto = (datos.get("identificacion_nueva") or "").strip()
        if texto and tipo_id:
            try:
                digitos = normalizar_ssn(texto) if tipo_id == "ssn" else normalizar_ein(texto)
            except forms.ValidationError as error:
                self.add_error("identificacion_nueva", error)
            else:
                indice = ProveedorServicios.indice_identificacion(tipo_id, digitos)
                duplicado = ProveedorServicios.objects.filter(
                    compania=self.compania, identificacion_indice=indice
                ).exclude(pk=self.instance.pk)
                if duplicado.exists():
                    self.add_error("identificacion_nueva", "Ya existe un proveedor con esta identificación.")
                datos["identificacion_nueva"] = digitos
        elif not texto and self.instance.pk and tipo_id != self.instance.tipo_identificacion:
            self.add_error("identificacion_nueva", "Si cambia el tipo de identificación, escriba el número nuevo.")

        relevo = datos.get("relevo")
        porcentaje = datos.get("relevo_porcentaje")
        if relevo == ProveedorServicios.Relevo.PARCIAL:
            if porcentaje is None:
                self.add_error("relevo_porcentaje", "Indique el porcentaje del certificado de relevo parcial.")
            elif not (0 <= porcentaje < 100):
                self.add_error("relevo_porcentaje", "Debe estar entre 0 y 100.")
        elif relevo == ProveedorServicios.Relevo.NINGUNO:
            datos["relevo_porcentaje"] = None
            datos["relevo_vigente_hasta"] = None
            datos["relevo_numero"] = ""
        if relevo in (ProveedorServicios.Relevo.PARCIAL, ProveedorServicios.Relevo.TOTAL):
            if not datos.get("relevo_vigente_hasta"):
                self.add_error("relevo_vigente_hasta", "Indique hasta cuándo es válido el certificado.")

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
        proveedor = super().save(commit=False)
        proveedor.compania = self.compania
        for campo in ("relevo_porcentaje", "relevo_vigente_hasta", "relevo_numero"):
            setattr(proveedor, campo, self.cleaned_data.get(campo))
        if self.cleaned_data.get("identificacion_nueva"):
            proveedor.asignar_identificacion(
                self.cleaned_data["tipo_identificacion"], self.cleaned_data["identificacion_nueva"]
            )
        if self.cleaned_data.get("cuenta_nueva"):
            proveedor.asignar_cuenta_bancaria(self.cleaned_data["cuenta_nueva"])
        elif self.cleaned_data.get("borrar_cuenta"):
            proveedor.asignar_cuenta_bancaria(None)
        if commit:
            proveedor.save()
        return proveedor
