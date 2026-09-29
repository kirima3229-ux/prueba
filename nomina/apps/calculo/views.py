"""
Simulador de nómina: calcula un período para un empleado sin guardar nada.
Sirve para validar el motor contra casos reales antes de procesar nóminas.
"""

from decimal import Decimal

from django import forms
from django.shortcuts import render
from django.utils import timezone

from apps.core.permisos import requiere_compania
from apps.empleados.forms import FechaInput
from apps.empleados.models import Empleado
from apps.parametros.models import ConceptoDeduccion, ConceptoIngreso

from . import cargar, motor

FILAS_EXTRA = 4
CERO = Decimal("0")


def _decimal(etiqueta, requerido=False):
    return forms.DecimalField(label=etiqueta, required=requerido, min_value=0, max_digits=12, decimal_places=2,
                              initial=None)


class SimuladorForm(forms.Form):
    empleado = forms.ModelChoiceField(label="Empleado", queryset=Empleado.objects.none())
    fecha_pago = forms.DateField(label="Fecha de pago", widget=FechaInput())
    horas_regulares = _decimal("Horas regulares")
    horas_extra_diarias = _decimal("Horas extra (exceso de 8 diarias)")
    horas_extra_semanales = _decimal("Horas extra (exceso de 40 semanales)")
    horas_septimo_dia = _decimal("Horas en séptimo día")
    horas_periodo_alimentos = _decimal("Horas en período de alimentos")
    horas_vacaciones = _decimal("Horas de vacaciones pagadas")
    horas_enfermedad = _decimal("Horas de enfermedad pagadas")
    semanas_choferil = forms.IntegerField(label="Semanas (Seguro Choferil)", required=False, min_value=0, max_value=6,
                                          help_text="Vacío = según la frecuencia de pago.")
    acumulado_ss = _decimal("Salarios SS acumulados en el año")
    acumulado_medicare = _decimal("Salarios Medicare acumulados")
    acumulado_futa = _decimal("Salarios FUTA acumulados")
    acumulado_desempleo = _decimal("Salarios desempleo estatal acumulados")
    acumulado_sinot = _decimal("Salarios SINOT acumulados")

    def __init__(self, *args, compania, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["empleado"].queryset = Empleado.objects.filter(compania=compania, activo=True)
        ingresos = [("", "—")] + [
            (c.codigo, c.nombre)
            for c in ConceptoIngreso.objects.filter(activo=True).exclude(
                codigo__in=["regular", "horas_extra", "vacaciones", "enfermedad"]
            )
        ]
        deducciones = [("", "—")] + [(c.codigo, c.nombre) for c in ConceptoDeduccion.objects.filter(activo=True)]
        for i in range(FILAS_EXTRA):
            self.fields[f"ingreso_{i}"] = forms.ChoiceField(label=f"Otro ingreso {i + 1}", choices=ingresos, required=False)
            self.fields[f"ingreso_{i}_monto"] = _decimal("Monto")
            self.fields[f"deduccion_{i}"] = forms.ChoiceField(label=f"Deducción {i + 1}", choices=deducciones, required=False)
            self.fields[f"deduccion_{i}_monto"] = _decimal("Monto")

    def filas_extra(self):
        return [
            (self[f"ingreso_{i}"], self[f"ingreso_{i}_monto"], self[f"deduccion_{i}"], self[f"deduccion_{i}_monto"])
            for i in range(FILAS_EXTRA)
        ]


def _valor(datos, campo):
    return datos.get(campo) or CERO


@requiere_compania
def simulador(request):
    inicial = {"fecha_pago": timezone.localdate()}
    if request.GET.get("empleado", "").isdigit():
        inicial["empleado"] = int(request.GET["empleado"])
    form = SimuladorForm(request.POST or None, initial=inicial, compania=request.compania)
    resultado, error, contexto_calculo = None, None, {}
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        emp = d["empleado"]
        try:
            parametros = cargar.parametros(d["fecha_pago"])
            tasas = cargar.tasas_compania(request.compania, emp, d["fecha_pago"].year)
            ingresos_cat = {c.codigo: c for c in ConceptoIngreso.objects.filter(activo=True)}
            deducciones_cat = {c.codigo: c for c in ConceptoDeduccion.objects.filter(activo=True)}
            otros = [
                motor.Monto(cargar.concepto_ingreso(ingresos_cat[d[f"ingreso_{i}"]]), d[f"ingreso_{i}_monto"])
                for i in range(FILAS_EXTRA)
                if d.get(f"ingreso_{i}") and d.get(f"ingreso_{i}_monto")
            ]
            deducciones = [
                motor.Monto(cargar.tipo_deduccion(deducciones_cat[d[f"deduccion_{i}"]]), d[f"deduccion_{i}_monto"])
                for i in range(FILAS_EXTRA)
                if d.get(f"deduccion_{i}") and d.get(f"deduccion_{i}_monto")
            ]
            resultado = motor.calcular(
                empleado=cargar.empleado(emp),
                parametros=parametros,
                tasas=tasas,
                frecuencia=request.compania.frecuencia_pago,
                horas=motor.Horas(
                    regulares=_valor(d, "horas_regulares"),
                    extra_diarias=_valor(d, "horas_extra_diarias"),
                    extra_semanales=_valor(d, "horas_extra_semanales"),
                    septimo_dia=_valor(d, "horas_septimo_dia"),
                    periodo_alimentos=_valor(d, "horas_periodo_alimentos"),
                    vacaciones=_valor(d, "horas_vacaciones"),
                    enfermedad=_valor(d, "horas_enfermedad"),
                ),
                otros_ingresos=otros,
                deducciones=deducciones,
                acumulados=motor.Acumulados(
                    ss=_valor(d, "acumulado_ss"),
                    medicare=_valor(d, "acumulado_medicare"),
                    futa=_valor(d, "acumulado_futa"),
                    desempleo=_valor(d, "acumulado_desempleo"),
                    sinot=_valor(d, "acumulado_sinot"),
                ),
                semanas_choferil=d.get("semanas_choferil"),
                conceptos=cargar.conceptos_ingreso(),
            )
            contexto_calculo = {"empleado": emp, "parametros": parametros}
        except motor.ErrorCalculo as e:
            error = str(e)
    return render(
        request,
        "calculo/simulador.html",
        {"form": form, "resultado": resultado, "error": error, **contexto_calculo},
    )


# --- Calculadora de mesada (Ley 80) --------------------------------------------------


class MesadaForm(forms.Form):
    empleado = forms.ModelChoiceField(label="Empleado", queryset=Empleado.objects.none())
    fecha_despido = forms.DateField(label="Fecha de despido", widget=FechaInput())
    salario_mensual = forms.DecimalField(
        label="Salario mensual base ($)", min_value=Decimal("0.01"), max_digits=12, decimal_places=2, required=False,
        help_text="Antes de Ley 4-2017: el salario más alto de los últimos 3 años. Ley 4-2017: el de los 30 días "
        "consecutivos con más horas regulares del último año.",
    )
    horas_30_dias = forms.DecimalField(
        label="o, si cobra por hora: horas regulares en esos 30 días", min_value=Decimal("0.01"), max_digits=6,
        decimal_places=2, required=False,
        help_text="El sistema calcula el salario base con su tarifa por hora.",
    )
    periodo_probatorio = forms.BooleanField(label="El despido ocurre durante el período probatorio", required=False)

    def __init__(self, *args, compania, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["empleado"].queryset = Empleado.objects.filter(compania=compania)

    def clean(self):
        datos = super().clean()
        emp, salario, horas = datos.get("empleado"), datos.get("salario_mensual"), datos.get("horas_30_dias")
        if emp is None:
            return datos
        if salario is None and horas is None:
            self.add_error("salario_mensual", "Indique el salario mensual base o, si cobra por hora, las horas.")
        elif salario is None and emp.tipo_pago != "hora":
            self.add_error("horas_30_dias", "El empleado no cobra por hora: indique el salario mensual base.")
        return datos


@requiere_compania
def mesada(request):
    from apps.licencias.models import saldo

    from .mesada import calcular_mesada, liquidar, salario_base_por_horas, tarifa_para_liquidacion

    inicial = {"fecha_despido": timezone.localdate()}
    if request.GET.get("empleado", "").isdigit():
        inicial["empleado"] = int(request.GET["empleado"])
    form = MesadaForm(request.POST or None, initial=inicial, compania=request.compania)
    liquidacion, error, emp, base_texto = None, None, None, ""
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        emp = d["empleado"]
        salario = d["salario_mensual"]
        if salario is None:
            salario = salario_base_por_horas(emp.tarifa, d["horas_30_dias"])
            base_texto = f"Salario base: {d['horas_30_dias']} h × ${emp.tarifa:,.2f} = ${salario:,.2f}."
        try:
            p = cargar.parametros_anio(d["fecha_despido"].year)
            resultado = calcular_mesada(
                regimen=emp.regimen_efectivo, fecha_empleo=emp.fecha_empleo, fecha_despido=d["fecha_despido"],
                salario_mensual=salario, reglas=cargar.reglas_mesada(p),
                periodo_probatorio=d["periodo_probatorio"],
            )
            minimo = cargar.salario_minimo_en(d["fecha_despido"])
            tarifa, texto_tarifa = tarifa_para_liquidacion(
                tipo_pago=emp.tipo_pago, tarifa=emp.tarifa, horas_regulares_periodo=emp.horas_regulares_periodo,
                salario_mensual=salario, salario_minimo=minimo.tarifa_hora if minimo else None,
            )
            liquidacion = liquidar(
                mesada=resultado, horas_vacaciones=saldo(emp, "vacaciones"), horas_enfermedad=saldo(emp, "enfermedad"),
                tarifa_hora=tarifa, texto_tarifa=texto_tarifa,
            )
            if not p.verificado:
                error = f"Las reglas de {p.anio} están POR VERIFICAR."
        except cargar.ConfiguracionFaltante as e:
            error = str(e)
    return render(
        request,
        "calculo/mesada.html",
        {"form": form, "liquidacion": liquidacion, "error": error, "empleado": emp, "base_texto": base_texto},
    )
