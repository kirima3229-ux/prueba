from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.auditoria.models import RegistroAuditoria
from apps.auditoria.servicios import Accion, diferencias, instantanea, registrar
from apps.core.permisos import requiere_compania, requiere_edicion

from . import importacion
from .forms import EmpleadoForm, ImportarForm, TerminarEmpleadoForm
from .models import Empleado


def _empleado(request, pk):
    # Solo empleados de la compañía activa (ya validada contra las asignadas).
    return get_object_or_404(Empleado, pk=pk, compania=request.compania)


@requiere_compania
def lista(request):
    empleados = Empleado.objects.filter(compania=request.compania).select_related("departamento")
    q = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "activos")
    if estado == "activos":
        empleados = empleados.filter(activo=True)
    elif estado == "inactivos":
        empleados = empleados.filter(activo=False)
    if q:
        filtro = (
            Q(nombre__icontains=q)
            | Q(apellido_paterno__icontains=q)
            | Q(apellido_materno__icontains=q)
            | Q(numero_empleado__icontains=q)
        )
        if q.isdigit() and len(q) == 4:
            filtro |= Q(ssn_ultimos4=q)
        empleados = empleados.filter(filtro)
    pagina = Paginator(empleados, 50).get_page(request.GET.get("pagina"))
    contexto = {"pagina": pagina, "q": q, "estado": estado}
    if request.headers.get("HX-Request"):
        return render(request, "empleados/_tabla.html", contexto)
    return render(request, "empleados/lista.html", contexto)


@requiere_compania
@requiere_edicion
def nuevo(request):
    form = EmpleadoForm(request.POST or None, compania=request.compania)
    if request.method == "POST" and form.is_valid():
        empleado = form.save(commit=False)
        empleado.creado_por = request.user
        empleado.save()
        registrar(request, Accion.EMPLEADO_CREADO, objeto=empleado)
        messages.success(request, f"Empleado {empleado.nombre_completo} creado.")
        return redirect("empleados:detalle", pk=empleado.pk)
    return render(request, "empleados/form.html", {"form": form, "titulo": "Nuevo empleado"})


@requiere_compania
def detalle(request, pk):
    empleado = _empleado(request, pk)
    historial = RegistroAuditoria.objects.filter(objeto_tipo=empleado._meta.label, objeto_id=str(empleado.pk))[:30]
    return render(request, "empleados/detalle.html", {"empleado": empleado, "historial": historial})


@requiere_compania
@requiere_edicion
def editar(request, pk):
    empleado = _empleado(request, pk)
    antes = instantanea(empleado)
    form = EmpleadoForm(request.POST or None, instance=empleado, compania=request.compania)
    if request.method == "POST" and form.is_valid():
        empleado = form.save()
        cambios = diferencias(antes, instantanea(empleado))
        if cambios:
            registrar(request, Accion.EMPLEADO_MODIFICADO, objeto=empleado, cambios=cambios)
        messages.success(request, "Empleado actualizado.")
        return redirect("empleados:detalle", pk=empleado.pk)
    return render(request, "empleados/form.html", {"form": form, "titulo": f"Editar {empleado.nombre_completo}", "empleado": empleado})


@requiere_compania
@requiere_edicion
def terminar(request, pk):
    empleado = _empleado(request, pk)
    if not empleado.activo:
        messages.info(request, "El empleado ya está inactivo.")
        return redirect("empleados:detalle", pk=empleado.pk)
    antes = instantanea(empleado)
    form = TerminarEmpleadoForm(request.POST or None, instance=empleado)
    if request.method == "POST" and form.is_valid():
        empleado = form.save(commit=False)
        empleado.activo = False
        empleado.save()
        registrar(request, Accion.EMPLEADO_TERMINADO, objeto=empleado, cambios=diferencias(antes, instantanea(empleado)))
        messages.success(request, f"{empleado.nombre_completo} marcado como inactivo.")
        return redirect("empleados:detalle", pk=empleado.pk)
    return render(request, "empleados/terminar.html", {"form": form, "empleado": empleado})


@requiere_compania
@requiere_edicion
@require_POST
def reactivar(request, pk):
    empleado = _empleado(request, pk)
    antes = instantanea(empleado)
    empleado.activo = True
    empleado.fecha_terminacion = None
    empleado.razon_terminacion = ""
    empleado.save()
    registrar(request, Accion.EMPLEADO_MODIFICADO, objeto=empleado, cambios=diferencias(antes, instantanea(empleado)), descripcion="Reactivado")
    messages.success(request, f"{empleado.nombre_completo} reactivado.")
    return redirect("empleados:detalle", pk=empleado.pk)


@requiere_compania
@requiere_edicion
def importar(request):
    form = ImportarForm(request.POST or None, request.FILES or None)
    resultado = None
    if request.method == "POST" and form.is_valid():
        solo_validar = form.cleaned_data["solo_validar"]
        resultado = importacion.procesar(
            form.cleaned_data["archivo"], request.compania, request.user, solo_validar=solo_validar
        )
        if resultado.creados:
            registrar(
                request,
                Accion.EMPLEADOS_IMPORTADOS,
                descripcion=f"{len(resultado.creados)} empleados importados desde {form.cleaned_data['archivo'].name[:100]}",
                cambios={"numeros": [e.numero_empleado for e in resultado.creados]},
            )
            messages.success(request, f"Se importaron {len(resultado.creados)} empleados.")
            return redirect("empleados:lista")
    return render(request, "empleados/importar.html", {"form": form, "resultado": resultado})


@requiere_compania
@requiere_edicion
def plantilla(request):
    respuesta = HttpResponse(
        importacion.plantilla_xlsx(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    respuesta["Content-Disposition"] = 'attachment; filename="plantilla_empleados.xlsx"'
    return respuesta
