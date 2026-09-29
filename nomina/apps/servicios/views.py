from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.auditoria.models import RegistroAuditoria
from apps.auditoria.servicios import Accion, diferencias, instantanea, registrar
from apps.core import hojas
from apps.core.permisos import requiere_admin, requiere_compania, requiere_edicion
from apps.empleados.forms import ImportarForm

from . import depositos as servicio_depositos
from . import importacion
from . import pagos as servicio_pagos
from .calculo import retencion_esperada
from .forms import AnularPagoForm, ConfigRetencionForm, DepositoForm, PagoForm, ProveedorServiciosForm
from .models import ConfigRetencionServicios, DepositoRetencion, EstadoVerificacion, PagoServicio, ProveedorServicios


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
    anio = timezone.localdate().year
    pagos_anio = proveedor.pagos.filter(anio=anio)
    activos = pagos_anio.filter(estado=PagoServicio.Estado.REGISTRADO).aggregate(
        acumulado=Sum("monto"), retenido=Sum("retencion")
    )
    return render(
        request,
        "servicios/detalle.html",
        {
            "proveedor": proveedor,
            "historial": historial,
            "anio": anio,
            "pagos": pagos_anio.order_by("-fecha", "-id")[:15],
            "acumulado": activos["acumulado"] or 0,
            "retenido": activos["retenido"] or 0,
        },
    )


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


# --- Pagos -------------------------------------------------------------------------




def _anio(request):
    texto = request.GET.get("anio", "")
    return int(texto) if texto.isdigit() and 2000 <= int(texto) <= 2100 else timezone.localdate().year


@requiere_compania
def pagos_lista(request):
    anio = _anio(request)
    pagos = PagoServicio.objects.filter(compania=request.compania, anio=anio).select_related("proveedor")
    proveedor_id = request.GET.get("proveedor", "")
    if proveedor_id.isdigit():
        pagos = pagos.filter(proveedor_id=int(proveedor_id))
    estado = request.GET.get("estado", "registrado")
    if estado in PagoServicio.Estado.values:
        pagos = pagos.filter(estado=estado)
    totales = pagos.filter(estado=PagoServicio.Estado.REGISTRADO).aggregate(
        monto=Sum("monto"), retencion=Sum("retencion"), neto=Sum("neto"), cantidad=Count("id")
    )
    pagina = Paginator(pagos, 100).get_page(request.GET.get("pagina"))
    return render(
        request,
        "servicios/pagos_lista.html",
        {
            "pagina": pagina,
            "anio": anio,
            "estado": estado,
            "proveedor_id": proveedor_id,
            "proveedores": ProveedorServicios.objects.filter(compania=request.compania),
            "totales": totales,
        },
    )


def _calculo_para_form(form, compania):
    """Devuelve (calculo, error) para la vista previa del formulario de pago."""
    d = form.cleaned_data
    try:
        return servicio_pagos.calcular(d["proveedor"], d["fecha"], d["monto"], exento=d.get("exento", False)), None
    except (servicio_pagos.ErrorPago, ValueError) as error:
        return None, str(error)


@requiere_compania
@requiere_edicion
def pago_nuevo(request):
    inicial = {"fecha": timezone.localdate(), "metodo": PagoServicio.Metodo.CHEQUE}
    if request.GET.get("proveedor", "").isdigit():
        inicial["proveedor"] = int(request.GET["proveedor"])
    form = PagoForm(request.POST or None, initial=inicial, compania=request.compania)
    calculo, error = None, None
    if request.method == "POST" and form.is_valid():
        calculo, error = _calculo_para_form(form, request.compania)
        if calculo is not None and request.POST.get("confirmar") == "1":
            d = form.cleaned_data
            try:
                pago, avisos = servicio_pagos.registrar(
                    proveedor=d["proveedor"], fecha=d["fecha"], monto=d["monto"], usuario=request.user,
                    exento=d["exento"], motivo_exencion=d["motivo_exencion"], referencia=d["referencia"],
                    descripcion=d["descripcion"], metodo=d["metodo"], numero_cheque=d["numero_cheque"],
                )
            except servicio_pagos.ErrorPago as e:
                error = str(e)
            else:
                registrar(
                    request, Accion.PAGO_SERVICIO_REGISTRADO, objeto=pago,
                    cambios={"monto": pago.monto, "retencion": pago.retencion, "tasa": pago.tasa_aplicada,
                             "tratamiento": pago.get_tratamiento_display()},
                )
                for aviso in avisos:
                    messages.warning(request, aviso)
                messages.success(request, f"Pago registrado. Retención: ${pago.retencion:,.2f}.")
                return redirect("servicios:pago_detalle", pk=pago.pk)
    plantilla = "servicios/_calculo.html" if request.headers.get("HX-Request") else "servicios/pago_form.html"
    return render(request, plantilla, {"form": form, "calculo": calculo, "error": error})


@requiere_compania
def pago_detalle(request, pk):
    pago = get_object_or_404(PagoServicio.objects.select_related("proveedor"), pk=pk, compania=request.compania)
    posteriores = PagoServicio.objects.filter(
        proveedor=pago.proveedor, anio=pago.anio, estado=PagoServicio.Estado.REGISTRADO, pk__gt=pago.pk
    ).count()
    historial = RegistroAuditoria.objects.filter(objeto_tipo=pago._meta.label, objeto_id=str(pago.pk))
    return render(
        request,
        "servicios/pago_detalle.html",
        {"pago": pago, "form": AnularPagoForm(), "posteriores": posteriores, "historial": historial},
    )


@requiere_compania
@requiere_edicion
@require_POST
def pago_anular(request, pk):
    pago = get_object_or_404(PagoServicio, pk=pk, compania=request.compania)
    form = AnularPagoForm(request.POST)
    if pago.estado == PagoServicio.Estado.ANULADO:
        messages.info(request, "El pago ya estaba anulado.")
    elif not form.is_valid():
        messages.error(request, "Indique el motivo de la anulación.")
    else:
        pago.estado = PagoServicio.Estado.ANULADO
        pago.motivo_anulacion = form.cleaned_data["motivo"]
        pago.anulado_por = request.user
        pago.anulado_en = timezone.now()
        pago.save(update_fields=["estado", "motivo_anulacion", "anulado_por", "anulado_en"])
        registrar(request, Accion.PAGO_SERVICIO_ANULADO, objeto=pago, descripcion=pago.motivo_anulacion)
        messages.success(request, "Pago anulado. Si corresponde, registre el pago correcto.")
        if pago.deposito_id and pago.deposito.estado == DepositoRetencion.Estado.REGISTRADO and pago.retencion:
            messages.warning(
                request,
                f"Este pago estaba incluido en un depósito ya registrado: se depositaron ${pago.retencion:,.2f} "
                "de más. Revise el depósito para un crédito o ajuste con Hacienda.",
            )
    return redirect("servicios:pago_detalle", pk=pago.pk)


def _filas_resumen(compania, anio):
    config = ConfigRetencionServicios.objects.filter(anio=anio).first()
    exencion = config.exencion_anual if config else Decimal("0")
    activos = PagoServicio.objects.filter(compania=compania, anio=anio, estado=PagoServicio.Estado.REGISTRADO)
    filas = []
    for proveedor in ProveedorServicios.objects.filter(pk__in=activos.values("proveedor")).order_by("numero"):
        suyos = activos.filter(proveedor=proveedor).order_by("id")
        t = suyos.aggregate(monto=Sum("monto"), exencion=Sum("exencion_aplicada"), base=Sum("base_sujeta"),
                            retencion=Sum("retencion"), neto=Sum("neto"), cantidad=Count("id"))
        esperada = retencion_esperada(suyos.values_list("monto", "tasa_aplicada"), exencion)
        filas.append({"proveedor": proveedor, **t, "esperada": esperada, "diferencia": esperada - t["retencion"]})
    return filas, config


@requiere_compania
def resumen_anual(request):
    anio = _anio(request)
    filas, config = _filas_resumen(request.compania, anio)
    totales = {k: sum((f[k] for f in filas), Decimal("0")) for k in ("monto", "exencion", "base", "retencion", "neto")}
    if request.GET.get("formato") == "xlsx":
        contenido = hojas.libro_xlsx(
            f"Servicios {anio}",
            ["Número", "Proveedor", "Tipo ID", "ID (últimos 4)", "Pagos", "Total pagado", "Exención",
             "Cantidad sujeta", "Retenido", "Neto pagado", "Revisar"],
            [[f["proveedor"].numero, f["proveedor"].nombre_mostrar, f["proveedor"].get_tipo_identificacion_display(),
              f["proveedor"].identificacion_ultimos4, f["cantidad"], f["monto"], f["exencion"], f["base"],
              f["retencion"], f["neto"], "Sí" if f["diferencia"] else ""] for f in filas],
            ["", "TOTAL", "", "", "", totales["monto"], totales["exencion"], totales["base"],
             totales["retencion"], totales["neto"], ""],
        )
        registrar(request, Accion.ARCHIVO_GENERADO, descripcion=f"Resumen de servicios prestados {anio} (Excel)")
        respuesta = HttpResponse(
            contenido, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        respuesta["Content-Disposition"] = f'attachment; filename="servicios_prestados_{anio}.xlsx"'
        return respuesta
    return render(
        request,
        "servicios/resumen.html",
        {"filas": filas, "anio": anio, "config": config, "totales": totales,
         "con_diferencias": any(f["diferencia"] for f in filas)},
    )


# --- Configuración (administradores) ----------------------------------------------


@requiere_admin
def config_lista(request):
    return render(request, "servicios/config_lista.html", {"configs": ConfigRetencionServicios.objects.all()})


@requiere_admin
def config_form(request, pk=None):
    config = get_object_or_404(ConfigRetencionServicios, pk=pk) if pk else None
    antes = instantanea(config) if config else {}
    form = ConfigRetencionForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        config = form.save(commit=False)
        if form.cleaned_data["marcar_verificado"]:
            if config.estado != EstadoVerificacion.VERIFICADO or form.changed_data:
                config.estado = EstadoVerificacion.VERIFICADO
                config.verificado_por = request.user
                config.verificado_en = timezone.now()
        else:
            config.estado = EstadoVerificacion.POR_VERIFICAR
            config.verificado_por = None
            config.verificado_en = None
        config.save()
        cambios = diferencias(antes, instantanea(config))
        if cambios:
            registrar(request, Accion.CONFIGURACION_MODIFICADA, objeto=config, cambios=cambios, compania=None)
        messages.success(request, f"Configuración {config.anio} guardada ({config.get_estado_display()}).")
        return redirect("servicios:config_lista")
    historial = (
        RegistroAuditoria.objects.filter(objeto_tipo=config._meta.label, objeto_id=str(config.pk)) if config else None
    )
    return render(request, "servicios/config_form.html", {"form": form, "config": config, "historial": historial})


# --- Importación -------------------------------------------------------------------


def _importar(request, procesar, accion, plantilla_url, titulo, destino):
    form = ImportarForm(request.POST or None, request.FILES or None)
    resultado = None
    if request.method == "POST" and form.is_valid():
        resultado = procesar(
            form.cleaned_data["archivo"], request.compania, request.user,
            solo_validar=form.cleaned_data["solo_validar"],
        )
        if resultado.creados:
            registrar(
                request, accion,
                descripcion=f"{len(resultado.creados)} registros importados desde {form.cleaned_data['archivo'].name[:100]}",
                cambios={"ids": [r.pk for r in resultado.creados]},
            )
            messages.success(request, f"Se importaron {len(resultado.creados)} registros.")
            return redirect(destino)
    return render(
        request,
        "servicios/importar.html",
        {"form": form, "resultado": resultado, "plantilla_url": plantilla_url, "titulo": titulo},
    )


@requiere_compania
@requiere_edicion
def importar_proveedores(request):
    return _importar(
        request, importacion.procesar_proveedores, Accion.PROVEEDORES_IMPORTADOS,
        "servicios:plantilla_proveedores", "Importar proveedores", "servicios:lista",
    )


@requiere_compania
@requiere_edicion
def importar_pagos(request):
    return _importar(
        request, importacion.procesar_pagos, Accion.PAGOS_IMPORTADOS,
        "servicios:plantilla_pagos", "Importar pagos", "servicios:pagos",
    )


def _descargar(contenido, nombre):
    respuesta = HttpResponse(contenido, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


@requiere_compania
@requiere_edicion
def plantilla_proveedores(request):
    return _descargar(importacion.plantilla_proveedores(), "plantilla_proveedores.xlsx")


@requiere_compania
@requiere_edicion
def plantilla_pagos(request):
    return _descargar(importacion.plantilla_pagos(), "plantilla_pagos_servicios.xlsx")


# --- Depósitos de la retención -----------------------------------------------------


@requiere_compania
def depositos_lista(request):
    anio = _anio(request)
    lista_depositos = DepositoRetencion.objects.filter(compania=request.compania, hasta__year=anio)
    return render(
        request,
        "servicios/depositos_lista.html",
        {
            "depositos": lista_depositos,
            "anio": anio,
            "pendiente": servicio_depositos.total_pendiente(request.compania),
            "pagos_pendientes": servicio_depositos.pendientes(request.compania).count(),
        },
    )


@requiere_compania
@requiere_edicion
def deposito_nuevo(request):
    if request.method == "POST":
        form = DepositoForm(request.POST)
    elif request.GET.get("desde"):
        # "Ver pagos del período": el usuario cambió el rango sugerido.
        form = DepositoForm({**request.GET.dict(), "fecha_deposito": timezone.localdate()})
    else:
        desde, hasta = servicio_depositos.periodo_sugerido(request.compania)
        form = DepositoForm(initial={"desde": desde, "hasta": hasta, "fecha_deposito": timezone.localdate()})
    periodo = None
    if form.is_bound and form.is_valid():
        periodo = (form.cleaned_data["desde"], form.cleaned_data["hasta"])
    elif not form.is_bound:
        periodo = (form.initial["desde"], form.initial["hasta"])

    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        try:
            deposito = servicio_depositos.registrar(
                compania=request.compania, desde=d["desde"], hasta=d["hasta"], fecha_deposito=d["fecha_deposito"],
                confirmacion=d["confirmacion"], notas=d["notas"], usuario=request.user,
            )
        except servicio_depositos.ErrorDeposito as error:
            messages.error(request, str(error))
        else:
            registrar(
                request, Accion.DEPOSITO_REGISTRADO, objeto=deposito,
                cambios={"monto": deposito.monto, "pagos": deposito.pagos.count(), "confirmacion": deposito.confirmacion},
            )
            messages.success(request, f"Depósito de ${deposito.monto:,.2f} registrado.")
            return redirect("servicios:deposito_detalle", pk=deposito.pk)

    incluidos = servicio_depositos.pendientes(request.compania, *periodo) if periodo else []
    total = sum((p.retencion for p in incluidos), Decimal("0"))
    anteriores = (
        servicio_depositos.pendientes(request.compania, hasta=periodo[0] - timedelta(days=1)).count() if periodo else 0
    )
    return render(
        request,
        "servicios/deposito_form.html",
        {"form": form, "incluidos": incluidos, "total": total, "anteriores": anteriores, "periodo": periodo},
    )


@requiere_compania
def deposito_detalle(request, pk):
    deposito = get_object_or_404(DepositoRetencion, pk=pk, compania=request.compania)
    historial = RegistroAuditoria.objects.filter(objeto_tipo=deposito._meta.label, objeto_id=str(deposito.pk))
    return render(
        request,
        "servicios/deposito_detalle.html",
        {"deposito": deposito, "pagos": deposito.pagos.select_related("proveedor"), "form": AnularPagoForm(),
         "historial": historial},
    )


@requiere_compania
@requiere_edicion
@require_POST
def deposito_anular(request, pk):
    deposito = get_object_or_404(DepositoRetencion, pk=pk, compania=request.compania)
    form = AnularPagoForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Indique el motivo de la anulación.")
        return redirect("servicios:deposito_detalle", pk=deposito.pk)
    try:
        servicio_depositos.anular(deposito, form.cleaned_data["motivo"], request.user)
    except servicio_depositos.ErrorDeposito as error:
        messages.info(request, str(error))
    else:
        registrar(request, Accion.DEPOSITO_ANULADO, objeto=deposito, descripcion=deposito.motivo_anulacion)
        messages.success(request, "Depósito anulado. Sus pagos vuelven a quedar pendientes de depositar.")
    return redirect("servicios:deposito_detalle", pk=deposito.pk)


# --- Informe trimestral ------------------------------------------------------------


@requiere_compania
def trimestral(request):
    anio = _anio(request)
    texto = request.GET.get("trimestre", "")
    trimestre = int(texto) if texto in ("1", "2", "3", "4") else servicio_depositos.trimestre_de(timezone.localdate())
    inicio, fin = servicio_depositos.rango_trimestre(anio, trimestre)
    activos = PagoServicio.objects.filter(
        compania=request.compania, estado=PagoServicio.Estado.REGISTRADO, fecha__range=(inicio, fin)
    )
    filas = []
    for proveedor in ProveedorServicios.objects.filter(pk__in=activos.values("proveedor")).order_by("numero"):
        t = activos.filter(proveedor=proveedor).aggregate(
            cantidad=Count("id"), monto=Sum("monto"), exencion=Sum("exencion_aplicada"),
            base=Sum("base_sujeta"), retencion=Sum("retencion"),
        )
        filas.append({"proveedor": proveedor, **t})
    totales = {k: sum((f[k] for f in filas), Decimal("0")) for k in ("monto", "exencion", "base", "retencion")}
    depositado = activos.filter(
        deposito__estado=DepositoRetencion.Estado.REGISTRADO
    ).aggregate(t=Sum("retencion"))["t"] or Decimal("0")
    if request.GET.get("formato") == "xlsx":
        contenido = hojas.libro_xlsx(
            f"T{trimestre}-{anio}",
            ["Número", "Proveedor", "Tipo", "Tipo ID", "ID (últimos 4)", "Pagos", "Ingreso pagado",
             "Exención", "Cantidad sujeta", "Retenido"],
            [[f["proveedor"].numero, f["proveedor"].nombre_mostrar, f["proveedor"].get_tipo_persona_display(),
              f["proveedor"].get_tipo_identificacion_display(), f["proveedor"].identificacion_ultimos4,
              f["cantidad"], f["monto"], f["exencion"], f["base"], f["retencion"]] for f in filas],
            ["", "TOTAL", "", "", "", "", totales["monto"], totales["exencion"], totales["base"], totales["retencion"]],
        )
        registrar(request, Accion.ARCHIVO_GENERADO, descripcion=f"Informe trimestral servicios prestados T{trimestre} {anio} (Excel)")
        return _descargar(contenido, f"servicios_prestados_T{trimestre}_{anio}.xlsx")
    return render(
        request,
        "servicios/trimestral.html",
        {"filas": filas, "totales": totales, "anio": anio, "trimestre": trimestre, "inicio": inicio, "fin": fin,
         "depositado": depositado, "pendiente": totales["retencion"] - depositado},
    )
