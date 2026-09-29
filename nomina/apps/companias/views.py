from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.auditoria.models import RegistroAuditoria
from apps.auditoria.servicios import Accion, diferencias, instantanea, registrar
from apps.core.permisos import requiere_admin, requiere_edicion

from .forms import ClasificacionCFSEForm, CompaniaForm, DepartamentoForm, TasaCFSEForm, TasasCompaniaForm
from .middleware import CLAVE_SESION
from .models import ClasificacionCFSE, Departamento, EstadoVerificacion, TasaCFSE, TasasCompania


def _compania_accesible(request, pk):
    return get_object_or_404(request.user.companias_accesibles(), pk=pk)


def lista(request):
    companias = request.user.companias_accesibles().annotate(
        activos=Count("empleados", filter=Q(empleados__activo=True))
    )
    return render(request, "companias/lista.html", {"companias": companias})


@requiere_admin
def nueva(request):
    form = CompaniaForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        compania = form.save()
        registrar(request, Accion.COMPANIA_CREADA, objeto=compania, compania=compania)
        request.session[CLAVE_SESION] = compania.pk
        messages.success(request, f"Compañía {compania} creada.")
        return redirect("companias:detalle", pk=compania.pk)
    return render(request, "companias/form.html", {"form": form, "titulo": "Nueva compañía"})


def detalle(request, pk):
    compania = _compania_accesible(request, pk)
    historial = None
    if request.user.es_admin:
        historial = RegistroAuditoria.objects.filter(compania_id=compania.pk)[:20]
    return render(
        request,
        "companias/detalle.html",
        {
            "compania": compania,
            "tasas": compania.tasas.all(),
            "departamentos": compania.departamentos.all(),
            "clasificaciones": compania.clasificaciones_cfse.prefetch_related("tasas"),
            "activos": compania.empleados.filter(activo=True).count(),
            "historial": historial,
        },
    )


@requiere_admin
def editar(request, pk):
    compania = _compania_accesible(request, pk)
    antes = instantanea(compania)
    form = CompaniaForm(request.POST or None, instance=compania)
    if request.method == "POST" and form.is_valid():
        compania = form.save()
        cambios = diferencias(antes, instantanea(compania))
        if cambios:
            registrar(request, Accion.COMPANIA_MODIFICADA, objeto=compania, compania=compania, cambios=cambios)
        messages.success(request, "Compañía actualizada.")
        return redirect("companias:detalle", pk=compania.pk)
    return render(request, "companias/form.html", {"form": form, "titulo": f"Editar {compania}", "compania": compania})


@require_POST
def seleccionar(request):
    compania_id = request.POST.get("compania", "")
    if not compania_id.isdigit():
        return redirect("companias:lista")
    compania = _compania_accesible(request, int(compania_id))
    request.session[CLAVE_SESION] = compania.pk
    destino = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()}):
        destino = "inicio"
    # Si estaba viendo un registro de otra compañía, volver al inicio.
    if destino.rstrip("/").split("/")[-1].isdigit():
        destino = "inicio"
    return redirect(destino)


# --- Tasas por año -------------------------------------------------------------


@requiere_admin
def tasas_form(request, pk, tasas_pk=None):
    compania = _compania_accesible(request, pk)
    tasas = get_object_or_404(TasasCompania, pk=tasas_pk, compania=compania) if tasas_pk else None
    antes = instantanea(tasas) if tasas else {}
    form = TasasCompaniaForm(request.POST or None, instance=tasas, compania=compania)
    if request.method == "POST" and form.is_valid():
        tasas = form.save(commit=False)
        tasas.compania = compania
        verificar = form.cleaned_data["marcar_verificado"]
        # Cualquier cambio de tasa sin la confirmación vuelve a POR VERIFICAR.
        if verificar:
            if tasas.estado != EstadoVerificacion.VERIFICADO or form.changed_data:
                tasas.estado = EstadoVerificacion.VERIFICADO
                tasas.verificado_por = request.user
                tasas.verificado_en = timezone.now()
        else:
            tasas.estado = EstadoVerificacion.POR_VERIFICAR
            tasas.verificado_por = None
            tasas.verificado_en = None
        tasas.save()
        cambios = diferencias(antes, instantanea(tasas))
        if cambios:
            registrar(
                request,
                Accion.TASAS_MODIFICADAS,
                objeto=tasas,
                compania=compania,
                cambios=cambios,
                descripcion=f"Tasas {tasas.anio}",
            )
        messages.success(request, f"Tasas {tasas.anio} guardadas ({tasas.get_estado_display()}).")
        return redirect("companias:detalle", pk=compania.pk)
    historial = None
    if tasas:
        historial = RegistroAuditoria.objects.filter(objeto_tipo=tasas._meta.label, objeto_id=str(tasas.pk))
    return render(
        request,
        "companias/tasas_form.html",
        {"form": form, "compania": compania, "tasas": tasas, "historial": historial},
    )


# --- Catálogos: departamentos y clasificaciones CFSE ----------------------------

CATALOGOS = {
    "departamentos": (Departamento, DepartamentoForm, "departamento"),
    "cfse": (ClasificacionCFSE, ClasificacionCFSEForm, "clasificación CFSE"),
}


@requiere_edicion
def catalogo_form(request, pk, catalogo, item_pk=None):
    compania = _compania_accesible(request, pk)
    if catalogo not in CATALOGOS:
        return redirect("companias:detalle", pk=compania.pk)
    modelo, clase_form, nombre = CATALOGOS[catalogo]
    item = get_object_or_404(modelo, pk=item_pk, compania=compania) if item_pk else None
    antes = instantanea(item) if item else {}
    form = clase_form(request.POST or None, instance=item, compania=compania)
    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.compania = compania
        item.save()
        registrar(
            request,
            Accion.CATALOGO_MODIFICADO,
            objeto=item,
            compania=compania,
            cambios=diferencias(antes, instantanea(item)),
            descripcion=f"{nombre.capitalize()} {'modificado' if antes else 'creado'}",
        )
        messages.success(request, f"{nombre.capitalize()} guardado.")
        return redirect("companias:detalle", pk=compania.pk)
    return render(
        request,
        "companias/catalogo_form.html",
        {"form": form, "compania": compania, "titulo": f"{'Editar' if item else 'Nuevo'} {nombre}"},
    )


@requiere_admin
def tasa_cfse_form(request, pk, cls_pk, tasa_pk=None):
    compania = _compania_accesible(request, pk)
    clasificacion = get_object_or_404(ClasificacionCFSE, pk=cls_pk, compania=compania)
    tasa = get_object_or_404(TasaCFSE, pk=tasa_pk, clasificacion=clasificacion) if tasa_pk else None
    antes = instantanea(tasa) if tasa else {}
    form = TasaCFSEForm(request.POST or None, instance=tasa, clasificacion=clasificacion)
    if request.method == "POST" and form.is_valid():
        tasa = form.save(commit=False)
        tasa.clasificacion = clasificacion
        tasa.estado = (
            EstadoVerificacion.VERIFICADO if form.cleaned_data["marcar_verificado"] else EstadoVerificacion.POR_VERIFICAR
        )
        tasa.save()
        cambios = diferencias(antes, instantanea(tasa))
        if cambios:
            registrar(request, Accion.TASAS_MODIFICADAS, objeto=tasa, compania=compania, cambios=cambios,
                      descripcion=f"CFSE {clasificacion.codigo} {tasa.anio}")
        messages.success(request, f"Tasa CFSE {clasificacion.codigo} {tasa.anio} guardada.")
        return redirect("companias:detalle", pk=compania.pk)
    return render(
        request,
        "companias/catalogo_form.html",
        {"form": form, "compania": compania, "titulo": f"Tasa CFSE — {clasificacion}"},
    )
