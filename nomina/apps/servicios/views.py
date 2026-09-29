from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.auditoria.models import RegistroAuditoria
from apps.auditoria.servicios import Accion, diferencias, instantanea, registrar
from apps.core.permisos import requiere_compania, requiere_edicion

from .forms import ProveedorServiciosForm
from .models import ProveedorServicios


def _proveedor(request, pk):
    return get_object_or_404(ProveedorServicios, pk=pk, compania=request.compania)


@requiere_compania
def lista(request):
    proveedores = ProveedorServicios.objects.filter(compania=request.compania)
    q = request.GET.get("q", "").strip()
    estado = request.GET.get("estado", "activos")
    if estado == "activos":
        proveedores = proveedores.filter(activo=True)
    elif estado == "inactivos":
        proveedores = proveedores.filter(activo=False)
    if q:
        filtro = (
            Q(nombre__icontains=q)
            | Q(apellido_paterno__icontains=q)
            | Q(nombre_comercial__icontains=q)
            | Q(numero__icontains=q)
            | Q(descripcion_servicio__icontains=q)
        )
        if q.isdigit() and len(q) == 4:
            filtro |= Q(identificacion_ultimos4=q)
        proveedores = proveedores.filter(filtro)
    pagina = Paginator(proveedores, 50).get_page(request.GET.get("pagina"))
    contexto = {"pagina": pagina, "q": q, "estado": estado}
    if request.headers.get("HX-Request"):
        return render(request, "servicios/_tabla.html", contexto)
    return render(request, "servicios/lista.html", contexto)


@requiere_compania
@requiere_edicion
def nuevo(request):
    form = ProveedorServiciosForm(request.POST or None, compania=request.compania)
    if request.method == "POST" and form.is_valid():
        proveedor = form.save(commit=False)
        proveedor.creado_por = request.user
        proveedor.save()
        registrar(request, Accion.PROVEEDOR_CREADO, objeto=proveedor)
        messages.success(request, f"Proveedor {proveedor.nombre_mostrar} creado.")
        return redirect("servicios:detalle", pk=proveedor.pk)
    return render(request, "servicios/form.html", {"form": form, "titulo": "Nuevo proveedor de servicios"})


@requiere_compania
def detalle(request, pk):
    proveedor = _proveedor(request, pk)
    historial = RegistroAuditoria.objects.filter(
        objeto_tipo=proveedor._meta.label, objeto_id=str(proveedor.pk)
    )[:30]
    return render(request, "servicios/detalle.html", {"proveedor": proveedor, "historial": historial})


@requiere_compania
@requiere_edicion
def editar(request, pk):
    proveedor = _proveedor(request, pk)
    antes = instantanea(proveedor)
    form = ProveedorServiciosForm(request.POST or None, instance=proveedor, compania=request.compania)
    if request.method == "POST" and form.is_valid():
        proveedor = form.save()
        cambios = diferencias(antes, instantanea(proveedor))
        if cambios:
            registrar(request, Accion.PROVEEDOR_MODIFICADO, objeto=proveedor, cambios=cambios)
        messages.success(request, "Proveedor actualizado.")
        return redirect("servicios:detalle", pk=proveedor.pk)
    return render(
        request,
        "servicios/form.html",
        {"form": form, "titulo": f"Editar {proveedor.nombre_mostrar}", "proveedor": proveedor},
    )


@requiere_compania
@requiere_edicion
@require_POST
def cambiar_estado(request, pk):
    proveedor = _proveedor(request, pk)
    antes = instantanea(proveedor)
    proveedor.activo = not proveedor.activo
    proveedor.save(update_fields=["activo", "modificado"])
    registrar(
        request,
        Accion.PROVEEDOR_MODIFICADO,
        objeto=proveedor,
        cambios=diferencias(antes, instantanea(proveedor)),
        descripcion="Reactivado" if proveedor.activo else "Desactivado",
    )
    messages.success(request, f"{proveedor.nombre_mostrar} {'reactivado' if proveedor.activo else 'desactivado'}.")
    return redirect("servicios:detalle", pk=proveedor.pk)
