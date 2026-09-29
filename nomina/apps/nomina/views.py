from datetime import date
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.auditoria.models import RegistroAuditoria
from apps.auditoria.servicios import Accion, diferencias, instantanea, registrar
from apps.calculo import cargar
from apps.core import hojas
from apps.core.permisos import requiere_admin, requiere_compania, requiere_edicion
from apps.core.validadores import validar_cuenta_bancaria, validar_ruta_bancaria
from apps.empleados.forms import FechaInput
from apps.empleados.models import Empleado
from apps.parametros.models import ConceptoDeduccion, ConceptoIngreso

from . import cheques, contabilidad, deposito_directo, pdf_cheques, servicios, talonario
from .models import (
    Cheque,
    ConfiguracionNACHA,
    CuentaContable,
    LineaResultado,
    DeduccionRecurrente,
    EntradaDeduccion,
    EntradaIngreso,
    EntradaNomina,
    ErrorNominaCerrada,
    FormatoCheque,
    PeriodoNomina,
)

# Columnas de ingresos que se pueden entrar directamente en la tabla del período.
INGRESOS_RAPIDOS = ("propinas", "comisiones", "bono")
CAMPOS_HORAS = [
    ("horas_regulares", "Reg."),
    ("horas_extra_diarias", "HE diarias"),
    ("horas_extra_semanales", "HE sem."),
    ("horas_septimo_dia", "7º día"),
    ("horas_periodo_alimentos", "Alim."),
    ("horas_vacaciones", "Vac."),
    ("horas_enfermedad", "Enf."),
]


def _periodo(request, pk):
    return get_object_or_404(PeriodoNomina, pk=pk, compania=request.compania)


def _decimal(texto):
    texto = (texto or "").strip().replace(",", "").replace("$", "")
    if texto == "":
        return Decimal("0")
    valor = Decimal(texto)
    if valor < 0:
        raise InvalidOperation
    return valor


@requiere_compania
def lista(request):
    periodos = (
        PeriodoNomina.objects.filter(compania=request.compania)
        .annotate(empleados=Count("resultados"), bruto=Sum("resultados__bruto"), neto=Sum("resultados__neto"))
    )
    return render(request, "nomina/lista.html", {"periodos": periodos[:100]})


class PeriodoForm(forms.Form):
    fecha_inicio = forms.DateField(label="Desde", widget=FechaInput())
    fecha_fin = forms.DateField(label="Hasta", widget=FechaInput())
    fecha_pago = forms.DateField(label="Fecha de pago", widget=FechaInput())
    tipo = forms.ChoiceField(choices=[(PeriodoNomina.Tipo.REGULAR, "Regular"), (PeriodoNomina.Tipo.ESPECIAL, "Especial")])
    descripcion = forms.CharField(label="Descripción", max_length=200, required=False)

    def clean(self):
        d = super().clean()
        if d.get("fecha_inicio") and d.get("fecha_fin") and d["fecha_fin"] < d["fecha_inicio"]:
            self.add_error("fecha_fin", "Debe ser igual o posterior a la fecha inicial.")
        return d


@requiere_compania
@requiere_edicion
def nuevo(request):
    inicio, fin, pago = servicios.sugerir_periodo(request.compania)
    form = PeriodoForm(request.POST or None, initial={"fecha_inicio": inicio, "fecha_fin": fin, "fecha_pago": pago,
                                                       "tipo": PeriodoNomina.Tipo.REGULAR})
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        periodo = servicios.crear_periodo(
            compania=request.compania, inicio=d["fecha_inicio"], fin=d["fecha_fin"], fecha_pago=d["fecha_pago"],
            tipo=d["tipo"], descripcion=d["descripcion"], usuario=request.user,
        )
        registrar(request, Accion.PERIODO_CREADO, objeto=periodo)
        messages.success(request, f"Período creado con {periodo.entradas.count()} empleados.")
        return redirect("nomina:detalle", pk=periodo.pk)
    return render(request, "nomina/nuevo.html", {"form": form})


def _valor_rapido(entrada, codigo):
    filas = [i for i in entrada.ingresos.all() if i.concepto.codigo == codigo]
    if len(filas) > 1:
        return None  # varias líneas: se editan en el detalle del empleado
    return filas[0].monto if filas else ""


@requiere_compania
def detalle(request, pk):
    periodo = _periodo(request, pk)
    entradas = list(
        periodo.entradas.select_related("empleado").prefetch_related("ingresos__concepto", "deducciones__concepto")
    )
    errores = []
    if request.method == "POST" and request.POST.get("accion") == "guardar":
        if not request.user.puede_editar:
            messages.error(request, "No tiene permiso para modificar la nómina.")
            return redirect("nomina:detalle", pk=periodo.pk)
        if not periodo.editable:
            messages.error(request, "La nómina está cerrada.")
            return redirect("nomina:detalle", pk=periodo.pk)
        conceptos = {c.codigo: c for c in ConceptoIngreso.objects.filter(codigo__in=INGRESOS_RAPIDOS)}
        with transaction.atomic():
            for entrada in entradas:
                try:
                    for campo, _ in CAMPOS_HORAS:
                        setattr(entrada, campo, _decimal(request.POST.get(f"{campo}_{entrada.pk}")))
                    rapidos = {c: _decimal(request.POST.get(f"{c}_{entrada.pk}")) for c in INGRESOS_RAPIDOS
                               if f"{c}_{entrada.pk}" in request.POST}
                except InvalidOperation:
                    errores.append(f"{entrada.empleado.nombre_completo}: hay un valor que no es un número válido.")
                    continue
                entrada.incluir = request.POST.get(f"incluir_{entrada.pk}") == "on"
                entrada.save()
                for codigo, monto in rapidos.items():
                    if codigo not in conceptos:
                        continue
                    entrada.ingresos.filter(concepto=conceptos[codigo]).delete()
                    if monto:
                        EntradaIngreso.objects.create(entrada=entrada, concepto=conceptos[codigo], monto=monto)
            if errores:
                transaction.set_rollback(True)
            else:
                servicios.marcar_modificado(periodo)
        if not errores:
            registrar(request, Accion.NOMINA_ENTRADAS, objeto=periodo, descripcion="Horas e ingresos guardados")
            messages.success(request, "Horas e ingresos guardados. Calcule la pre-nómina para ver los resultados.")
            return redirect("nomina:detalle", pk=periodo.pk)

    filas = [
        {
            "entrada": e,
            "horas": [(campo, getattr(e, campo)) for campo, _ in CAMPOS_HORAS],
            "rapidos": [(c, _valor_rapido(e, c)) for c in INGRESOS_RAPIDOS],
            "otros": sum(1 for i in e.ingresos.all() if i.concepto.codigo not in INGRESOS_RAPIDOS),
            "deducciones": sum((d.monto for d in e.deducciones.all()), Decimal("0")),
        }
        for e in entradas
    ]
    resultados = list(periodo.resultados.all())
    totales = periodo.resultados.aggregate(
        bruto=Sum("bruto"), retenciones=Sum("total_retenciones"), deducciones=Sum("total_deducciones"),
        neto=Sum("neto"), patronal=Sum("total_patronal"),
    )
    return render(
        request,
        "nomina/detalle.html",
        {
            "periodo": periodo, "filas": filas, "columnas_horas": [e for _, e in CAMPOS_HORAS],
            "columnas_rapidas": INGRESOS_RAPIDOS, "resultados": resultados, "totales": totales, "errores": errores,
            "con_alertas": sum(1 for r in resultados if r.alertas),
            "historial": RegistroAuditoria.objects.filter(objeto_tipo=periodo._meta.label, objeto_id=str(periodo.pk))[:20],
        },
    )


@requiere_compania
@requiere_edicion
@require_POST
def calcular(request, pk):
    periodo = _periodo(request, pk)
    try:
        errores = servicios.calcular_periodo(periodo, request.user)
    except (servicios.ErrorNomina, cargar.ConfiguracionFaltante, ErrorNominaCerrada) as e:
        messages.error(request, str(e))
    else:
        registrar(request, Accion.NOMINA_CALCULADA, objeto=periodo,
                  cambios={"empleados": periodo.resultados.count(), "errores": len(errores)})
        if errores:
            messages.warning(request, f"Pre-nómina calculada con {len(errores)} error(es). Corríjalos antes de aprobar.")
        else:
            messages.success(request, "Pre-nómina calculada. Revise los resultados y apruebe.")
    return redirect("nomina:detalle", pk=periodo.pk)


@requiere_compania
@requiere_edicion
@require_POST
def cerrar(request, pk):
    periodo = _periodo(request, pk)
    try:
        servicios.cerrar_periodo(periodo, request.user)
    except servicios.ErrorNomina as e:
        messages.error(request, str(e))
    else:
        totales = periodo.resultados.aggregate(bruto=Sum("bruto"), neto=Sum("neto"))
        registrar(request, Accion.NOMINA_PROCESADA, objeto=periodo,
                  cambios={"empleados": periodo.resultados.count(), "bruto": totales["bruto"], "neto": totales["neto"]})
        messages.success(request, "Nómina aprobada y cerrada.")
    return redirect("nomina:detalle", pk=periodo.pk)


@requiere_compania
@requiere_admin
@require_POST
def reversar(request, pk):
    periodo = _periodo(request, pk)
    try:
        reverso = servicios.reversar_periodo(periodo, request.POST.get("motivo", ""), request.user)
    except servicios.ErrorNomina as e:
        messages.error(request, str(e))
        return redirect("nomina:detalle", pk=periodo.pk)
    registrar(request, Accion.NOMINA_REVERSADA, objeto=periodo, descripcion=periodo.motivo_reverso,
              cambios={"reverso": reverso.pk})
    messages.success(request, "Nómina reversada. Cree un período nuevo para procesar el pago correcto.")
    return redirect("nomina:detalle", pk=reverso.pk)


# --- Detalle de un empleado en el período -------------------------------------------


class EntradaForm(forms.ModelForm):
    class Meta:
        model = EntradaNomina
        fields = ["incluir"] + [c for c, _ in CAMPOS_HORAS] + ["semanas_choferil"]


class LineaForm(forms.Form):
    concepto = forms.ModelChoiceField(queryset=ConceptoIngreso.objects.none())
    monto = forms.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    descripcion = forms.CharField(max_length=200, required=False)

    def __init__(self, *args, modelo, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["concepto"].queryset = modelo.objects.filter(activo=True)


@requiere_compania
def entrada(request, pk, entrada_pk):
    periodo = _periodo(request, pk)
    entrada = get_object_or_404(EntradaNomina, pk=entrada_pk, periodo=periodo)
    puede = request.user.puede_editar and periodo.editable
    form = EntradaForm(request.POST if request.POST.get("accion") == "horas" else None, instance=entrada)
    form_ingreso = LineaForm(request.POST if request.POST.get("accion") == "ingreso" else None, modelo=ConceptoIngreso,
                             prefix="ing")
    form_deduccion = LineaForm(request.POST if request.POST.get("accion") == "deduccion" else None,
                               modelo=ConceptoDeduccion, prefix="ded")
    if request.method == "POST":
        if not puede:
            messages.error(request, "La nómina no se puede modificar.")
            return redirect("nomina:entrada", pk=periodo.pk, entrada_pk=entrada.pk)
        accion = request.POST.get("accion")
        cambio = False
        if accion == "horas" and form.is_valid():
            form.save()
            cambio = True
        elif accion == "ingreso" and form_ingreso.is_valid():
            EntradaIngreso.objects.create(entrada=entrada, **form_ingreso.cleaned_data)
            cambio = True
        elif accion == "deduccion" and form_deduccion.is_valid():
            EntradaDeduccion.objects.create(entrada=entrada, **form_deduccion.cleaned_data)
            cambio = True
        elif accion == "borrar_ingreso":
            cambio = bool(entrada.ingresos.filter(pk=request.POST.get("id")).delete()[0])
        elif accion == "borrar_deduccion":
            cambio = bool(entrada.deducciones.filter(pk=request.POST.get("id")).delete()[0])
        if cambio:
            servicios.marcar_modificado(periodo)
            registrar(request, Accion.NOMINA_ENTRADAS, objeto=periodo,
                      descripcion=f"{entrada.empleado.nombre_completo}: {accion}")
            messages.success(request, "Guardado. Recuerde calcular de nuevo la pre-nómina.")
            return redirect("nomina:entrada", pk=periodo.pk, entrada_pk=entrada.pk)
    resultado = periodo.resultados.filter(empleado=entrada.empleado).prefetch_related("lineas").first()
    return render(
        request,
        "nomina/entrada.html",
        {"periodo": periodo, "entrada": entrada, "form": form, "form_ingreso": form_ingreso,
         "form_deduccion": form_deduccion, "resultado": resultado, "puede": puede},
    )


# --- Talonarios y registro --------------------------------------------------------------


def _pdf(contenido, nombre):
    respuesta = HttpResponse(contenido, content_type="application/pdf")
    respuesta["Content-Disposition"] = f'inline; filename="{nombre}"'
    return respuesta


@requiere_compania
def talonarios(request, pk):
    periodo = _periodo(request, pk)
    resultados = periodo.resultados.select_related("empleado", "periodo__compania").prefetch_related("lineas")
    empleado = request.GET.get("empleado", "")
    if empleado.isdigit():
        resultados = resultados.filter(empleado_id=int(empleado))
    if not resultados.exists():
        messages.error(request, "No hay resultados. Calcule la pre-nómina primero.")
        return redirect("nomina:detalle", pk=periodo.pk)
    registrar(request, Accion.ARCHIVO_GENERADO, objeto=periodo,
              descripcion=f"Talonarios PDF ({resultados.count()})" + ("" if periodo.cerrado else " — PRE-NÓMINA"))
    return _pdf(talonario.generar_pdf(list(resultados)), f"talonarios_{periodo.fecha_pago:%Y%m%d}.pdf")


@requiere_compania
def registro(request, pk):
    """Registro de nómina del período en Excel."""
    periodo = _periodo(request, pk)
    resultados = periodo.resultados.prefetch_related("lineas")
    codigos = {"ingreso": [], "retencion": [], "deduccion": [], "patronal": []}
    nombres = {}
    for r in resultados:
        for l in r.lineas.all():
            if l.codigo not in codigos[l.grupo]:
                codigos[l.grupo].append(l.codigo)
            nombres[(l.grupo, l.codigo)] = l.nombre
    columnas = [(g, c) for g in ("ingreso", "retencion", "deduccion", "patronal") for c in codigos[g]]
    encabezados = (["Núm.", "Empleado", "SSN (últimos 4)", "Departamento", "Horas"]
                   + [nombres[c] for c in columnas[:len(codigos["ingreso"])]] + ["Bruto"]
                   + [nombres[c] for c in columnas[len(codigos["ingreso"]):]] + ["Neto", "Costo patronal"])
    filas = []
    totales = [Decimal("0")] * (len(columnas) + 4)
    for r in resultados:
        montos = {}
        for l in r.lineas.all():
            montos[(l.grupo, l.codigo)] = montos.get((l.grupo, l.codigo), Decimal("0")) + l.monto
        valores = [montos.get(c, Decimal("0")) for c in columnas]
        n_ing = len(codigos["ingreso"])
        fila_valores = valores[:n_ing] + [r.bruto] + valores[n_ing:] + [r.neto, r.total_patronal]
        filas.append([r.numero_empleado, r.empleado_nombre, r.ssn_ultimos4, r.departamento, r.horas_trabajadas]
                     + fila_valores)
        totales = [a + b for a, b in zip(totales, [r.horas_trabajadas] + fila_valores)]
    contenido = hojas.libro_xlsx(
        "Registro", encabezados, filas, ["", "TOTAL", "", ""] + totales,
    )
    registrar(request, Accion.ARCHIVO_GENERADO, objeto=periodo, descripcion="Registro de nómina (Excel)")
    respuesta = HttpResponse(contenido, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    respuesta["Content-Disposition"] = f'attachment; filename="registro_nomina_{periodo.fecha_pago:%Y%m%d}.xlsx"'
    return respuesta


# --- Deducciones recurrentes --------------------------------------------------------------


class DeduccionRecurrenteForm(forms.ModelForm):
    class Meta:
        model = DeduccionRecurrente
        fields = ["concepto", "monto", "desde", "hasta", "notas"]
        widgets = {"desde": FechaInput(), "hasta": FechaInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["concepto"].queryset = ConceptoDeduccion.objects.filter(activo=True)


@requiere_compania
def deducciones_empleado(request, pk):
    emp = get_object_or_404(Empleado, pk=pk, compania=request.compania)
    form = DeduccionRecurrenteForm(request.POST if request.POST.get("accion") == "nueva" else None)
    if request.method == "POST":
        if not request.user.puede_editar:
            messages.error(request, "No tiene permiso.")
            return redirect("nomina:deducciones_empleado", pk=emp.pk)
        accion = request.POST.get("accion")
        if accion == "nueva" and form.is_valid():
            ded = form.save(commit=False)
            ded.empleado = emp
            ded.save()
            registrar(request, Accion.DEDUCCION_RECURRENTE, objeto=emp,
                      cambios={"concepto": str(ded.concepto), "monto": ded.monto}, descripcion="Deducción añadida")
            messages.success(request, "Deducción recurrente añadida. Se aplicará en las próximas nóminas.")
            return redirect("nomina:deducciones_empleado", pk=emp.pk)
        if accion == "desactivar":
            ded = get_object_or_404(DeduccionRecurrente, pk=request.POST.get("id"), empleado=emp)
            ded.activo = False
            ded.save(update_fields=["activo"])
            registrar(request, Accion.DEDUCCION_RECURRENTE, objeto=emp,
                      cambios={"concepto": str(ded.concepto), "monto": ded.monto}, descripcion="Deducción desactivada")
            messages.success(request, "Deducción desactivada.")
            return redirect("nomina:deducciones_empleado", pk=emp.pk)
    return render(request, "nomina/deducciones.html",
                  {"empleado": emp, "deducciones": emp.deducciones_recurrentes.select_related("concepto"), "form": form})


# --- Cheques ---------------------------------------------------------------------------


class FormatoChequeForm(forms.ModelForm):
    class Meta:
        model = FormatoCheque
        fields = ["posicion", "idioma", "siguiente_numero", "ajuste_horizontal", "ajuste_vertical",
                  "imprimir_encabezado", "nombre_cuenta"]


@requiere_compania
@requiere_edicion
def formato_cheque(request):
    formato = cheques.formato_de(request.compania)
    antes = instantanea(formato)
    form = FormatoChequeForm(request.POST or None, instance=formato)
    if request.method == "POST" and form.is_valid():
        formato = form.save()
        cambios = diferencias(antes, instantanea(formato))
        if cambios:
            registrar(request, Accion.FORMATO_CHEQUE, objeto=request.compania, cambios=cambios)
        messages.success(request, "Formato de cheques guardado.")
        return redirect("nomina:formato_cheque")
    return render(request, "nomina/formato_cheque.html", {"form": form, "formato": formato})


@requiere_compania
@requiere_edicion
def prueba_alineacion(request):
    formato = cheques.formato_de(request.compania)
    return _pdf(pdf_cheques.generar_prueba(formato, request.compania), "prueba_alineacion.pdf")


def _entero(texto):
    texto = (texto or "").strip()
    return int(texto) if texto.isdigit() else None


@requiere_compania
def cheques_periodo(request, pk):
    periodo = _periodo(request, pk)
    formato = cheques.formato_de(request.compania)
    resultados = list(
        periodo.resultados.select_related("empleado").prefetch_related("cheques").order_by("empleado_nombre")
    )
    if request.method == "POST":
        if not request.user.puede_editar:
            raise PermissionDenied("No tiene permiso para esta acción.")
        accion = request.POST.get("accion")
        try:
            if accion == "emitir":
                elegidos = [r for r in resultados if request.POST.get(f"r_{r.pk}")]
                emitidos = cheques.emitir(periodo, elegidos, _entero(request.POST.get("primer_numero")), request.user)
                registrar(request, Accion.CHEQUE_EMITIDO, objeto=periodo,
                          descripcion=f"Cheques núm. {emitidos[0].numero}–{emitidos[-1].numero}",
                          cambios={str(c.numero): {"beneficiario": c.beneficiario, "monto": c.monto} for c in emitidos})
                messages.success(request, f"{len(emitidos)} cheque(s) emitido(s). Ponga el papel de cheques en la "
                                          f"impresora empezando por el núm. {emitidos[0].numero} e imprima.")
            elif accion in ("anular", "reemitir"):
                cheque = get_object_or_404(Cheque, pk=request.POST.get("cheque"), periodo=periodo)
                motivo = request.POST.get("motivo", "")
                if accion == "anular":
                    cheques.anular(cheque, motivo, request.user)
                    nuevo = None
                else:
                    nuevo = cheques.reemitir(cheque, motivo, request.user, _entero(request.POST.get("numero")))
                registrar(request, Accion.CHEQUE_ANULADO, objeto=periodo, descripcion=cheque.motivo_anulacion,
                          cambios={"cheque": cheque.numero, "monto": cheque.monto, "beneficiario": cheque.beneficiario,
                                   **({"reemplazo": nuevo.numero} if nuevo else {})})
                if nuevo:
                    registrar(request, Accion.CHEQUE_EMITIDO, objeto=periodo,
                              descripcion=f"Cheque núm. {nuevo.numero} (reemplaza el {cheque.numero})",
                              cambios={str(nuevo.numero): {"beneficiario": nuevo.beneficiario, "monto": nuevo.monto}})
                    messages.success(request, f"Cheque {cheque.numero} anulado. Nuevo cheque núm. {nuevo.numero}.")
                else:
                    messages.success(request, f"Cheque {cheque.numero} anulado.")
        except cheques.ErrorCheque as e:
            messages.error(request, str(e))
        return redirect("nomina:cheques", pk=periodo.pk)
    filas = []
    for r in resultados:
        todos = sorted(r.cheques.all(), key=lambda c: c.numero)
        filas.append({"resultado": r, "vigente": cheques.vigente(r), "anulados": [c for c in todos if c.estado == "anulado"],
                      "sugerido": cheques.por_cheque_sugerido(r)})
    pendientes = [f for f in filas if not f["vigente"] and f["resultado"].neto > 0]
    return render(request, "nomina/cheques.html", {
        "periodo": periodo, "formato": formato, "filas": filas, "pendientes": pendientes,
        "puede": request.user.puede_editar and periodo.estado == "cerrada" and periodo.tipo != "reverso",
        "hay_vigentes": any(f["vigente"] for f in filas),
        "hay_depositos": any(f["resultado"].empleado.deposito_directo and not f["vigente"] and f["resultado"].neto > 0
                             for f in filas),
    })


@requiere_compania
@requiere_edicion
def cheques_pdf(request, pk):
    periodo = _periodo(request, pk)
    emitidos = (Cheque.objects.filter(periodo=periodo, estado=Cheque.Estado.EMITIDO)
                .select_related("resultado__empleado", "resultado__periodo__compania")
                .prefetch_related("resultado__lineas"))
    numero = _entero(request.GET.get("cheque"))
    if numero is not None:
        emitidos = emitidos.filter(numero=numero)
    emitidos = list(emitidos)
    if not emitidos:
        messages.error(request, "No hay cheques emitidos para imprimir.")
        return redirect("nomina:cheques", pk=periodo.pk)
    registrar(request, Accion.ARCHIVO_GENERADO, objeto=periodo,
              descripcion="Cheques impresos núm. " + ", ".join(str(c.numero) for c in emitidos))
    return _pdf(pdf_cheques.generar_cheques(cheques.formato_de(request.compania), emitidos),
                f"cheques_{periodo.fecha_pago:%Y%m%d}.pdf")


@requiere_compania
def avisos_deposito(request, pk):
    periodo = _periodo(request, pk)
    resultados = [
        r for r in periodo.resultados.select_related("empleado", "periodo__compania").prefetch_related("lineas", "cheques")
        if r.empleado.deposito_directo and r.neto > 0 and not cheques.vigente(r)
    ]
    if periodo.estado != "cerrada" or periodo.tipo == "reverso" or not resultados:
        messages.error(request, "No hay avisos de depósito para imprimir (la nómina debe estar cerrada).")
        return redirect("nomina:cheques", pk=periodo.pk)
    registrar(request, Accion.ARCHIVO_GENERADO, objeto=periodo, descripcion=f"Avisos de depósito ({len(resultados)})")
    return _pdf(pdf_cheques.generar_avisos(cheques.formato_de(request.compania), resultados),
                f"avisos_deposito_{periodo.fecha_pago:%Y%m%d}.pdf")


# --- Importar horas -------------------------------------------------------------------


@requiere_compania
@requiere_edicion
def importar_horas(request, pk):
    from apps.empleados.forms import ImportarForm

    from . import importar_horas as importacion

    periodo = _periodo(request, pk)
    if not periodo.editable:
        messages.error(request, "La nómina está cerrada.")
        return redirect("nomina:detalle", pk=periodo.pk)
    if request.GET.get("plantilla") == "1":
        respuesta = HttpResponse(importacion.plantilla(periodo),
                                 content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        respuesta["Content-Disposition"] = f'attachment; filename="horas_{periodo.fecha_pago:%Y%m%d}.xlsx"'
        return respuesta
    form = ImportarForm(request.POST or None, request.FILES or None)
    resultado = None
    if request.method == "POST" and form.is_valid():
        resultado = importacion.procesar(form.cleaned_data["archivo"], periodo,
                                         solo_validar=form.cleaned_data["solo_validar"])
        if resultado.aplicadas:
            servicios.marcar_modificado(periodo)
            registrar(request, Accion.NOMINA_ENTRADAS, objeto=periodo,
                      descripcion=f"Horas importadas de {form.cleaned_data['archivo'].name[:100]}: "
                                  f"{resultado.aplicadas} empleado(s)",
                      cambios={"columnas": resultado.columnas_usadas})
            messages.success(request, f"Se importaron las horas de {resultado.aplicadas} empleado(s). "
                                      "Revíselas y calcule la pre-nómina.")
            return redirect("nomina:detalle", pk=periodo.pk)
    return render(request, "nomina/importar_horas.html",
                  {"periodo": periodo, "form": form, "resultado": resultado})


# --- Depósito directo (NACHA) ----------------------------------------------------------


class ConfiguracionNACHAForm(forms.ModelForm):
    cuenta_compania_nueva = forms.CharField(
        label="Cuenta de la compañía (para archivo balanceado)", required=False, max_length=17,
        help_text="Déjelo vacío para no cambiarla.")

    class Meta:
        model = ConfiguracionNACHA
        fields = ["nombre_banco", "ruta_banco", "origen_inmediato", "identificacion_compania", "nombre_compania",
                  "descripcion", "balanceado", "ruta_compania", "tipo_cuenta_compania"]

    def clean_ruta_banco(self):
        return validar_ruta_bancaria(self.cleaned_data["ruta_banco"])

    def clean_ruta_compania(self):
        ruta = self.cleaned_data.get("ruta_compania")
        return validar_ruta_bancaria(ruta) if ruta else ""

    def clean_cuenta_compania_nueva(self):
        cuenta = self.cleaned_data.get("cuenta_compania_nueva")
        return validar_cuenta_bancaria(cuenta) if cuenta else ""

    def clean(self):
        d = super().clean()
        if d.get("balanceado"):
            if not d.get("ruta_compania"):
                self.add_error("ruta_compania", "El archivo balanceado necesita la ruta de la cuenta de la compañía.")
            if not d.get("cuenta_compania_nueva") and not (self.instance.pk and self.instance.cuenta_compania):
                self.add_error("cuenta_compania_nueva", "El archivo balanceado necesita la cuenta de la compañía.")
        return d

    def save(self, commit=True):
        config = super().save(commit=False)
        cuenta = self.cleaned_data.get("cuenta_compania_nueva")
        if cuenta:
            config.cuenta_compania = cuenta
            config.cuenta_compania_ultimos4 = cuenta[-4:]
        if commit:
            config.save()
        return config


@requiere_compania
@requiere_admin
def configuracion_nacha(request):
    config = deposito_directo.configuracion(request.compania)
    if config is None:
        config = ConfiguracionNACHA(compania=request.compania, nombre_compania=request.compania.nombre[:16])
    antes = instantanea(config) if config.pk else {}
    form = ConfiguracionNACHAForm(request.POST or None, instance=config)
    if request.method == "POST" and form.is_valid():
        config = form.save()
        registrar(request, Accion.CONFIG_NACHA, objeto=request.compania,
                  cambios=diferencias(antes, instantanea(config)))
        messages.success(request, "Datos del banco guardados.")
        return redirect("nomina:configuracion_nacha")
    return render(request, "nomina/configuracion_nacha.html", {"form": form, "config": config})


@requiere_compania
@requiere_edicion
def deposito_directo_vista(request, pk):
    periodo = _periodo(request, pk)
    config = deposito_directo.configuracion(request.compania)
    resultados = deposito_directo.depositos(periodo)
    fecha = deposito_directo.fecha_efectiva_sugerida(periodo)
    if request.method == "POST":
        try:
            fecha = date.fromisoformat(request.POST.get("fecha_efectiva", ""))
            contenido, archivo = deposito_directo.generar(periodo, fecha, request.user)
        except ValueError:
            messages.error(request, "Indique la fecha efectiva.")
        except deposito_directo.ErrorDeposito as e:
            messages.error(request, str(e))
        else:
            registrar(request, Accion.ARCHIVO_GENERADO, objeto=periodo,
                      descripcion=f"Archivo NACHA: {archivo.depositos} depósito(s), ${archivo.total:,.2f}, "
                                  f"efectivo {archivo.fecha_efectiva:%m/%d/%Y}",
                      cambios={"sha256": archivo.huella})
            respuesta = HttpResponse(contenido, content_type="text/plain; charset=ascii")
            respuesta["Content-Disposition"] = f'attachment; filename="NOMINA_{periodo.fecha_pago:%Y%m%d}.ach"'
            return respuesta
    return render(request, "nomina/deposito_directo.html", {
        "periodo": periodo, "config": config, "resultados": resultados, "fecha": fecha,
        "total": sum((r.neto for r in resultados), Decimal("0")),
        "archivos": periodo.archivos_bancarios.select_related("generado_por"),
        "puede": periodo.estado == "cerrada" and periodo.tipo != "reverso" and config is not None,
    })


# --- Contabilidad (QuickBooks Online) ---------------------------------------------------


@requiere_compania
@requiere_admin
def cuentas_contables(request):
    asignadas = contabilidad.mapa(request.compania)
    claves = contabilidad.claves()
    if request.method == "POST":
        antes = dict(asignadas)
        with transaction.atomic():
            for clave in claves:
                valor = request.POST.get(f"c_{clave}", "").strip()[:150]
                if valor:
                    CuentaContable.objects.update_or_create(compania=request.compania, clave=clave,
                                                            defaults={"cuenta": valor})
                else:
                    CuentaContable.objects.filter(compania=request.compania, clave=clave).delete()
        despues = contabilidad.mapa(request.compania)
        cambios = {k: {"antes": antes.get(k, ""), "despues": despues.get(k, "")}
                   for k in set(antes) | set(despues) if antes.get(k) != despues.get(k)}
        if cambios:
            registrar(request, Accion.CUENTAS_CONTABLES, objeto=request.compania, cambios=cambios)
        messages.success(request, "Cuentas guardadas.")
        return redirect("nomina:cuentas_contables")
    filas = [
        {"clave": clave, "descripcion": descripcion, "valor": asignadas.get(clave, ""),
         "sugerida": contabilidad.cuenta_para({k: v for k, v in asignadas.items() if k != clave}, clave)}
        for clave, descripcion in claves.items()
    ]
    return render(request, "nomina/cuentas_contables.html", {"filas": filas})


@requiere_compania
def asiento_contable(request, pk):
    periodo = _periodo(request, pk)
    if not periodo.cerrado:
        messages.error(request, "El asiento se genera de una nómina cerrada.")
        return redirect("nomina:detalle", pk=periodo.pk)
    lineas = contabilidad.asiento(LineaResultado.objects.filter(resultado__periodo=periodo),
                                  contabilidad.mapa(request.compania))
    numero = f"NOM-{periodo.fecha_pago:%Y%m%d}-{periodo.pk}"
    memo = (f"{periodo.get_tipo_display()} {periodo.fecha_inicio:%m/%d/%Y}–{periodo.fecha_fin:%m/%d/%Y}"
            + (f" · {periodo.descripcion}" if periodo.descripcion else ""))
    formato = request.GET.get("formato")
    if formato in ("csv", "xlsx"):
        if not contabilidad.cuadra(lineas):  # no debería ocurrir
            messages.error(request, "El asiento no cuadra; no se exportó.")
            return redirect("nomina:asiento", pk=periodo.pk)
        registrar(request, Accion.ARCHIVO_GENERADO, objeto=periodo, descripcion=f"Asiento QuickBooks ({formato})")
        if formato == "csv":
            respuesta = HttpResponse(contabilidad.csv_qbo(lineas, numero, periodo.fecha_pago, memo),
                                     content_type="text/csv; charset=utf-8")
        else:
            respuesta = HttpResponse(
                hojas.libro_xlsx("Asiento", ["Journal No", "Journal Date", "Account", "Debits", "Credits",
                                             "Description", "Name", "Memo"],
                                 [[numero, periodo.fecha_pago, l.cuenta, l.debito or None, l.credito or None,
                                   l.descripcion, "", memo] for l in lineas]),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        respuesta["Content-Disposition"] = f'attachment; filename="asiento_{numero}.{formato}"'
        return respuesta
    return render(request, "nomina/asiento.html", {
        "periodo": periodo, "lineas": lineas, "numero": numero, "memo": memo,
        "debitos": sum((l.debito for l in lineas), Decimal("0")),
        "creditos": sum((l.credito for l in lineas), Decimal("0")),
    })


# --- Servicios prestados en el ciclo de nómina ---------------------------------------------


@requiere_compania
def servicios_periodo(request, pk):
    """Pagos a proveedores de servicios prestados con la fecha de pago de este ciclo de nómina."""
    from apps.servicios import pagos as servicio_pagos
    from apps.servicios.models import PagoServicio, ProveedorServicios

    periodo = _periodo(request, pk)
    puede = request.user.puede_editar and periodo.tipo != PeriodoNomina.Tipo.REVERSO
    proveedores = list(ProveedorServicios.objects.filter(compania=request.compania, activo=True)
                       .order_by("apellido_paterno", "nombre"))
    filas = [{"p": p, "monto": "", "referencia": "", "descripcion": "", "metodo": "cheque", "calculo": None}
             for p in proveedores]
    errores = []
    if request.method == "POST":
        if not puede:
            raise PermissionDenied("No tiene permiso para esta acción.")
        registrar_pagos = request.POST.get("accion") == "registrar"
        a_pagar = []
        for f in filas:
            p = f["p"]
            f.update({c: request.POST.get(f"{c}_{p.pk}", "").strip()[:200]
                      for c in ("monto", "referencia", "descripcion", "metodo")})
            if f["metodo"] not in PagoServicio.Metodo.values:
                f["metodo"] = "cheque"
            try:
                monto = _decimal(f["monto"])
            except InvalidOperation:
                errores.append(f"{p.nombre_mostrar}: el monto no es válido.")
                continue
            if not monto:
                continue
            try:
                f["calculo"] = servicio_pagos.calcular(p, periodo.fecha_pago, monto)
            except servicio_pagos.ErrorPago as e:
                errores.append(f"{p.nombre_mostrar}: {e}")
                continue
            a_pagar.append((f, monto))
        if not a_pagar and not errores:
            errores.append("Escriba el monto de al menos un pago.")
        if registrar_pagos and not errores:
            try:
                with transaction.atomic():
                    creados = [
                        servicio_pagos.registrar(
                            proveedor=f["p"], fecha=periodo.fecha_pago, monto=monto, usuario=request.user,
                            referencia=f["referencia"][:50], descripcion=f["descripcion"], metodo=f["metodo"],
                            origen=PagoServicio.Origen.NOMINA, periodo_nomina=periodo,
                        )[0]
                        for f, monto in a_pagar
                    ]
            except servicio_pagos.ErrorPago as e:
                errores.append(str(e))
            else:
                for pago in creados:
                    registrar(request, Accion.PAGO_SERVICIO_REGISTRADO, objeto=pago,
                              descripcion=f"Pago en el ciclo de nómina {periodo}",
                              cambios={"monto": pago.monto, "retencion": pago.retencion})
                messages.success(request, f"Se registraron {len(creados)} pago(s) a proveedores de servicios.")
                return redirect("nomina:servicios", pk=periodo.pk)
    pagados = periodo.pagos_servicios.select_related("proveedor")
    return render(request, "nomina/servicios.html", {
        "periodo": periodo, "filas": filas, "errores": errores, "puede": puede, "pagados": pagados,
        "metodos": PagoServicio.Metodo.choices,
        "vista_previa": request.method == "POST" and not errores,
        "totales": pagados.exclude(estado="anulado").aggregate(monto=Sum("monto"), retencion=Sum("retencion"),
                                                               neto=Sum("neto")),
    })
