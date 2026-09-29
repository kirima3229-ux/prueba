from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.auditoria.models import RegistroAuditoria
from apps.auditoria.servicios import Accion, diferencias, instantanea, registrar
from apps.companias.models import EstadoVerificacion
from apps.core.permisos import requiere_admin

from .forms import (
    ConceptoDeduccionForm,
    ConceptoIngresoForm,
    CopiarAnioForm,
    ParametrosForm,
    ReglasFormSet,
    SalarioMinimoForm,
    TramosFormSet,
)
from .models import ConceptoDeduccion, ConceptoIngreso, ParametrosAnuales, SalarioMinimo


def _aplicar_verificacion(objeto, verificar, cambio, usuario):
    """Confirmar marca VERIFICADO; cualquier cambio sin confirmar vuelve a POR VERIFICAR."""
    if verificar:
        if objeto.estado != EstadoVerificacion.VERIFICADO or cambio:
            objeto.estado = EstadoVerificacion.VERIFICADO
            objeto.verificado_por = usuario
            objeto.verificado_en = timezone.now()
    else:
        objeto.estado = EstadoVerificacion.POR_VERIFICAR
        objeto.verificado_por = None
        objeto.verificado_en = None


def _historial(objeto):
    return RegistroAuditoria.objects.filter(objeto_tipo=objeto._meta.label, objeto_id=str(objeto.pk))[:30]


def _foto_parametros(p):
    foto = instantanea(p)
    foto["tramos"] = [str(t) for t in p.tramos.all()]
    foto["horas_extra"] = [
        f"{r.get_regimen_display()}: diario {r.diario}, semanal {r.semanal}, 7º día {r.septimo_dia}, "
        f"alimentos {r.periodo_alimentos}"
        for r in p.reglas_horas_extra.all()
    ]
    return foto


@requiere_admin
def inicio(request):
    return render(
        request,
        "parametros/inicio.html",
        {
            "anios": ParametrosAnuales.objects.all(),
            "minimos": SalarioMinimo.objects.all(),
            "ingresos": ConceptoIngreso.objects.all(),
            "deducciones": ConceptoDeduccion.objects.all(),
            "copiar": CopiarAnioForm(),
        },
    )


@requiere_admin
def anio(request, anio):
    parametros = get_object_or_404(ParametrosAnuales, anio=anio)
    antes = _foto_parametros(parametros)
    form = ParametrosForm(request.POST or None, instance=parametros)
    tramos = TramosFormSet(request.POST or None, instance=parametros, prefix="tramos")
    reglas = ReglasFormSet(request.POST or None, instance=parametros, prefix="reglas")
    if request.method == "POST" and form.is_valid() and tramos.is_valid() and reglas.is_valid():
        with transaction.atomic():
            cambio = form.has_changed() or tramos.has_changed() or reglas.has_changed()
            parametros = form.save(commit=False)
            _aplicar_verificacion(parametros, form.cleaned_data["marcar_verificado"], cambio, request.user)
            parametros.save()
            tramos.save()
            reglas.save()
        cambios = diferencias(antes, _foto_parametros(parametros))
        if cambios:
            registrar(request, Accion.CONFIGURACION_MODIFICADA, objeto=parametros, cambios=cambios, compania=None)
        messages.success(request, f"Parámetros {anio} guardados ({parametros.get_estado_display()}).")
        return redirect("parametros:inicio")
    return render(
        request,
        "parametros/anio.html",
        {"form": form, "tramos": tramos, "reglas": reglas, "parametros": parametros, "historial": _historial(parametros)},
    )


@requiere_admin
def copiar(request):
    form = CopiarAnioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        origen = form.cleaned_data["origen"]
        with transaction.atomic():
            nuevo = ParametrosAnuales.objects.get(pk=origen.pk)
            nuevo.pk = None
            nuevo.anio = form.cleaned_data["anio"]
            nuevo.estado = EstadoVerificacion.POR_VERIFICAR
            nuevo.verificado_por = None
            nuevo.verificado_en = None
            nuevo.notas = f"Copiado de {origen.anio}. Actualice los topes y la tabla del año nuevo."
            nuevo.save()
            for tramo in origen.tramos.all():
                tramo.pk = None
                tramo.parametros = nuevo
                tramo.save()
            for regla in origen.reglas_horas_extra.all():
                regla.pk = None
                regla.parametros = nuevo
                regla.save()
        registrar(request, Accion.CONFIGURACION_MODIFICADA, objeto=nuevo, compania=None,
                  descripcion=f"Parámetros {nuevo.anio} creados copiando {origen.anio}")
        messages.success(request, f"Año {nuevo.anio} creado como copia de {origen.anio}. Quedó POR VERIFICAR.")
        return redirect("parametros:anio", anio=nuevo.anio)
    messages.error(request, "No se pudo copiar: " + " ".join(e for errs in form.errors.values() for e in errs))
    return redirect("parametros:inicio")


def _form_simple(request, modelo, clase_form, pk, titulo):
    objeto = get_object_or_404(modelo, pk=pk) if pk else None
    antes = instantanea(objeto) if objeto else {}
    form = clase_form(request.POST or None, instance=objeto)
    if request.method == "POST" and form.is_valid():
        objeto = form.save(commit=False)
        _aplicar_verificacion(objeto, form.cleaned_data["marcar_verificado"], form.has_changed(), request.user)
        objeto.save()
        cambios = diferencias(antes, instantanea(objeto))
        if cambios:
            registrar(request, Accion.CONFIGURACION_MODIFICADA, objeto=objeto, cambios=cambios, compania=None)
        messages.success(request, f"{titulo} guardado ({objeto.get_estado_display()}).")
        return redirect("parametros:inicio")
    return render(
        request,
        "parametros/simple_form.html",
        {"form": form, "titulo": f"{'Editar' if objeto else 'Nuevo'} {titulo.lower()}", "historial": _historial(objeto) if objeto else None},
    )


@requiere_admin
def salario_minimo(request, pk=None):
    return _form_simple(request, SalarioMinimo, SalarioMinimoForm, pk, "Salario mínimo")


@requiere_admin
def concepto_ingreso(request, pk=None):
    return _form_simple(request, ConceptoIngreso, ConceptoIngresoForm, pk, "Concepto de ingreso")


@requiere_admin
def concepto_deduccion(request, pk=None):
    return _form_simple(request, ConceptoDeduccion, ConceptoDeduccionForm, pk, "Concepto de deducción")
