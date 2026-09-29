from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.auditoria.servicios import Accion, registrar
from apps.calculo import cargar
from apps.core import hojas
from apps.core.permisos import requiere_compania, requiere_edicion
from apps.empleados.forms import FechaInput
from apps.empleados.models import Empleado
from apps.parametros.models import ParametrosAnuales

from . import servicios
from .models import BonoNavidad, MovimientoLicencia, TipoLicencia, saldo


def _decimal(texto):
    texto = (texto or "").strip().replace(",", "").replace("$", "")
    if texto == "":
        return None
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        raise ValueError(f"'{texto}' no es un número válido.")
    if valor < 0:
        raise ValueError("No se permiten números negativos.")
    return valor


def _horas_por_dia(anio):
    p = ParametrosAnuales.objects.filter(anio=anio).first()
    return p.horas_por_dia if p else Decimal("8")


@requiere_compania
def balances(request):
    empleados = Empleado.objects.filter(compania=request.compania, activo=True).annotate(
        vacaciones=Sum("movimientos_licencia__horas", filter=Q(movimientos_licencia__tipo="vacaciones")),
        enfermedad=Sum("movimientos_licencia__horas", filter=Q(movimientos_licencia__tipo="enfermedad")),
    )
    horas_dia = _horas_por_dia(timezone.localdate().year)
    filas = [
        {"e": e, "vac": e.vacaciones or Decimal("0"), "enf": e.enfermedad or Decimal("0")} for e in empleados
    ]
    for f in filas:
        f["vac_dias"] = f["vac"] / horas_dia
        f["enf_dias"] = f["enf"] / horas_dia
    if request.GET.get("formato") == "xlsx":
        contenido = hojas.libro_xlsx(
            "Balances",
            ["Número", "Empleado", "Régimen", "Vacaciones (h)", "Vacaciones (días)", "Enfermedad (h)", "Enfermedad (días)"],
            [[f["e"].numero_empleado, f["e"].nombre_completo, f["e"].get_regimen_efectivo_display(),
              f["vac"], round(f["vac_dias"], 2), f["enf"], round(f["enf_dias"], 2)] for f in filas],
        )
        registrar(request, Accion.ARCHIVO_GENERADO, descripcion="Balances de vacaciones y enfermedad (Excel)")
        respuesta = HttpResponse(contenido, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        respuesta["Content-Disposition"] = 'attachment; filename="balances_licencias.xlsx"'
        return respuesta
    return render(request, "licencias/balances.html", {"filas": filas, "horas_dia": horas_dia})


def _mes_solicitado(request):
    """Mes a acumular: el indicado en la petición o, por defecto, el mes anterior."""
    hoy = timezone.localdate()
    anio, mes = (hoy.year, hoy.month - 1) if hoy.month > 1 else (hoy.year - 1, 12)
    try:
        anio = int(request.GET.get("anio") or request.POST.get("anio") or anio)
        mes = int(request.GET.get("mes") or request.POST.get("mes") or mes)
        if not (2000 <= anio <= 2100 and 1 <= mes <= 12):
            raise ValueError
    except ValueError:
        anio, mes = hoy.year, hoy.month
    return anio, mes


@requiere_compania
@requiere_edicion
def acumular(request):
    anio, mes = _mes_solicitado(request)
    empleados, inicio, fin = servicios.empleados_del_mes(request.compania, anio, mes)
    ya = set(
        MovimientoLicencia.objects.filter(clase="acumulacion", periodo=inicio, empleado__compania=request.compania)
        .values_list("empleado_id", flat=True)
    )
    resultado, errores, valores = None, [], {}
    if request.method == "POST":
        horas = {}
        for emp in empleados:
            texto = request.POST.get(f"horas_{emp.pk}", "")
            valores[emp.pk] = texto
            try:
                valor = _decimal(texto)
            except ValueError as e:
                errores.append(f"{emp.nombre_completo}: {e}")
                continue
            if valor is not None:
                horas[emp.pk] = valor
        if not errores:
            guardar = request.POST.get("accion") == "guardar"
            try:
                resultado = servicios.acumular_mes(request.compania, anio, mes, horas, request.user, guardar=guardar)
            except cargar.ConfiguracionFaltante as e:
                errores.append(str(e))
            else:
                if guardar:
                    nuevos = [f for f in resultado.filas if not f.ya_acumulado]
                    registrar(
                        request, Accion.LICENCIAS_ACUMULADAS,
                        descripcion=f"Acumulación {mes:02d}/{anio}: {len(nuevos)} empleados",
                        cambios={"empleados": [f.empleado.numero_empleado for f in nuevos]},
                    )
                    messages.success(request, f"Acumulación de {mes:02d}/{anio} guardada para {len(nuevos)} empleados.")
                    return redirect("licencias:balances")
    de_nomina = request.method == "GET" and request.GET.get("de_nomina") == "1"
    if de_nomina:
        from apps.nomina.servicios import horas_del_mes

        valores = {k: str(v) for k, v in horas_del_mes(request.compania, anio, mes).items()}
        if valores:
            messages.info(request, f"Horas traídas de {len(valores)} empleado(s) con nómina cerrada en {mes:02d}/{anio}. "
                                   "Revíselas antes de calcular.")
        else:
            messages.warning(request, f"No hay nóminas cerradas cuyo período termine en {mes:02d}/{anio}.")
    filas = [{"e": e, "valor": valores.get(e.pk, ""), "ya": e.pk in ya} for e in empleados]
    return render(
        request,
        "licencias/acumular.html",
        {"anio": anio, "mes": mes, "filas": filas, "resultado": resultado, "errores": errores,
         "meses": range(1, 13)},
    )


class MovimientoForm(forms.Form):
    tipo = forms.ChoiceField(choices=TipoLicencia.choices)
    clase = forms.ChoiceField(
        label="Movimiento",
        choices=[(c.value, c.label) for c in MovimientoLicencia.Clase if c != MovimientoLicencia.Clase.ACUMULACION],
    )
    horas = forms.DecimalField(
        max_digits=8, decimal_places=2,
        help_text="Uso y liquidación: horas positivas (se restan). Ajuste: positivo suma, negativo resta.",
    )
    fecha = forms.DateField(widget=FechaInput())
    descripcion = forms.CharField(label="Descripción / motivo", max_length=300, required=False)


@requiere_compania
def empleado(request, pk):
    emp = get_object_or_404(Empleado, pk=pk, compania=request.compania)
    form = MovimientoForm(request.POST or None, initial={"fecha": timezone.localdate()})
    if request.method == "POST":
        if not request.user.puede_editar:
            messages.error(request, "No tiene permiso para registrar movimientos.")
            return redirect("licencias:empleado", pk=emp.pk)
        if form.is_valid():
            d = form.cleaned_data
            try:
                mov = servicios.registrar_movimiento(
                    empleado=emp, tipo=d["tipo"], clase=d["clase"], horas=d["horas"], fecha=d["fecha"],
                    descripcion=d["descripcion"], usuario=request.user,
                )
            except servicios.ErrorLicencia as e:
                form.add_error(None, str(e))
            else:
                registrar(request, Accion.LICENCIA_MOVIMIENTO, objeto=emp,
                          cambios={"tipo": mov.tipo, "clase": mov.clase, "horas": mov.horas, "fecha": mov.fecha},
                          descripcion=mov.descripcion)
                messages.success(request, "Movimiento registrado.")
                return redirect("licencias:empleado", pk=emp.pk)
    horas_dia = _horas_por_dia(timezone.localdate().year)
    vacaciones, enfermedad = saldo(emp, "vacaciones"), saldo(emp, "enfermedad")
    return render(
        request,
        "licencias/empleado.html",
        {
            "empleado": emp,
            "form": form,
            "movimientos": emp.movimientos_licencia.select_related("creado_por")[:200],
            "vacaciones": vacaciones,
            "enfermedad": enfermedad,
            "vacaciones_dias": vacaciones / horas_dia,
            "enfermedad_dias": enfermedad / horas_dia,
        },
    )


def _anio_bono(request):
    texto = request.GET.get("anio") or request.POST.get("anio") or ""
    return int(texto) if texto.isdigit() and 2000 <= int(texto) <= 2100 else timezone.localdate().year


@requiere_compania
def bono(request):
    anio = _anio_bono(request)
    guardados = {b.empleado_id: b for b in BonoNavidad.objects.filter(compania=request.compania, anio=anio)}
    errores, filas, periodo, verificado = [], None, None, True
    valores = {}
    if request.method == "POST":
        if not request.user.puede_editar:
            messages.error(request, "No tiene permiso para calcular el bono.")
            return redirect(f"{request.path}?anio={anio}")
        datos = {}
        for emp in Empleado.objects.filter(compania=request.compania):
            h, s = request.POST.get(f"horas_{emp.pk}"), request.POST.get(f"salario_{emp.pk}")
            if h is None and s is None:
                continue
            valores[emp.pk] = (h or "", s or "")
            try:
                horas, salario = _decimal(h), _decimal(s)
            except ValueError as e:
                errores.append(f"{emp.nombre_completo}: {e}")
                continue
            if horas is not None or salario is not None:
                datos[emp.pk] = (horas or 0, salario or 0)
        if not errores:
            guardar = request.POST.get("accion") == "guardar"
            try:
                filas, periodo, verificado = servicios.calcular_bonos(
                    request.compania, anio, datos, request.user, guardar=guardar
                )
            except cargar.ConfiguracionFaltante as e:
                errores.append(str(e))
            else:
                if guardar:
                    total = sum((f.resultado.monto for f in filas if not f.pagado), Decimal("0"))
                    registrar(request, Accion.BONO_CALCULADO,
                              descripcion=f"Bono de Navidad {anio}: {len(filas)} empleados, total ${total:,.2f}",
                              cambios={"total": total})
                    messages.success(request, f"Bono de Navidad {anio} guardado. Total ${total:,.2f}.")
                    return redirect(f"{request.path}?anio={anio}")

    if request.GET.get("formato") == "xlsx":
        bonos = list(guardados.values())
        contenido = hojas.libro_xlsx(
            f"Bono {anio}",
            ["Número", "Empleado", "Régimen", "Horas", "Salario del período", "Tiene derecho", "Bono", "Detalle"],
            [[b.empleado.numero_empleado, b.empleado.nombre_completo, b.regimen, b.horas, b.salario,
              "Sí" if b.elegible else "No", b.monto, b.explicacion] for b in bonos],
            ["", "TOTAL", "", "", sum((b.salario for b in bonos), Decimal("0")), "",
             sum((b.monto for b in bonos), Decimal("0")), ""],
        )
        registrar(request, Accion.ARCHIVO_GENERADO, descripcion=f"Reporte de bono de Navidad {anio} (Excel)")
        respuesta = HttpResponse(contenido, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        respuesta["Content-Disposition"] = f'attachment; filename="bono_navidad_{anio}.xlsx"'
        return respuesta

    from apps.calculo.licencias import periodo_bono

    desde, hasta = periodo or periodo_bono(anio)
    empleados = (
        Empleado.objects.filter(compania=request.compania, fecha_empleo__lte=hasta)
        .exclude(fecha_terminacion__lt=desde)
        .order_by("apellido_paterno", "nombre")
    )
    if request.method == "GET" and request.GET.get("de_nomina") == "1":
        from apps.nomina.servicios import datos_bono

        datos_nomina = datos_bono(request.compania, desde, hasta)
        valores = {k: (str(h), str(s)) for k, (h, s) in datos_nomina.items()}
        if valores:
            messages.info(request, f"Horas y salarios traídos de la nómina para {len(valores)} empleado(s) "
                                   f"({desde:%m/%d/%Y} – {hasta:%m/%d/%Y}). Revíselos antes de calcular.")
        else:
            messages.warning(request, "No hay nóminas cerradas en el período del bono.")
    grid = []
    for e in empleados:
        g = guardados.get(e.pk)
        h, s = valores.get(e.pk, (g.horas if g else "", g.salario if g else ""))
        grid.append({"e": e, "horas": h, "salario": s, "guardado": g})
    return render(
        request,
        "licencias/bono.html",
        {
            "anio": anio, "desde": desde, "hasta": hasta, "grid": grid, "filas": filas, "errores": errores,
            "verificado": verificado, "guardados": list(guardados.values()),
            "total_guardado": sum((b.monto for b in guardados.values()), Decimal("0")),
        },
    )
