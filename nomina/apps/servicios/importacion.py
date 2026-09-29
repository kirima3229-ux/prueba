"""
Importación de proveedores de servicios y de pagos desde Excel/CSV.
Mismas reglas que empleados: cada fila se valida con el formulario de la
pantalla y es "todo o nada".
"""

from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from apps.core import hojas
from apps.core.hojas import ErrorFila

from . import pagos as servicio_pagos
from .forms import PagoForm, ProveedorServiciosForm
from .models import PagoServicio, ProveedorServicios

MAX_FILAS = 2000


@dataclass
class Resultado:
    total_filas: int = 0
    errores: list = field(default_factory=list)
    creados: list = field(default_factory=list)
    vista_previa: list = field(default_factory=list)
    columnas_desconocidas: list = field(default_factory=list)
    avisos: set = field(default_factory=set)

    @property
    def ok(self):
        return not self.errores and self.total_filas > 0


def _leer(archivo, hoja, columnas, relleno, resultado):
    try:
        filas = hojas.leer_archivo(archivo, hoja, relleno)
    except Exception:  # archivo dañado o formato inesperado
        resultado.errores.append(ErrorFila(0, "", "No se pudo leer el archivo. Verifique que sea .xlsx o .csv válido."))
        return None
    if filas:
        conocidas = {c[0] for c in columnas}
        resultado.columnas_desconocidas = sorted(set(filas[0]) - conocidas)
        faltan = [c[0] for c in columnas if c[2] and c[0] not in filas[0]]
        if faltan:
            resultado.errores.append(ErrorFila(1, ", ".join(faltan), "Faltan columnas requeridas en el encabezado."))
            return None
    return filas


def _datos_de_fila(fila, columnas, booleanos, modelo_choices, defectos, indice, resultado):
    datos = {}
    for columna, campo, _req, _desc in columnas:
        valor = fila.get(columna, "")
        if not valor and campo in defectos:
            valor = defectos[campo]
        if campo in booleanos:
            booleano = hojas.a_booleano(valor)
            if booleano is None:
                resultado.errores.append(ErrorFila(indice, columna, f"Valor '{valor}' no es si/no."))
            elif booleano:
                datos[campo] = "on"
            continue
        if valor and campo in modelo_choices:
            valor = hojas.opcion(valor, modelo_choices[campo])
        datos[campo] = valor
    return datos


def _errores_de_form(form, columnas, indice, resultado):
    columna_de = {c[1]: c[0] for c in columnas}
    for campo, mensajes in form.errors.items():
        for mensaje in mensajes:
            resultado.errores.append(ErrorFila(indice, columna_de.get(campo, "") if campo != "__all__" else "", mensaje))


# --- Proveedores -----------------------------------------------------------------

COLUMNAS_PROVEEDORES = [
    ("numero", "numero", True, "Número único dentro de la compañía"),
    ("tipo_persona", "tipo_persona", True, "individuo | entidad"),
    ("nombre", "nombre", True, "Individuo: primer nombre. Entidad: razón social"),
    ("segundo_nombre", "segundo_nombre", False, ""),
    ("apellido_paterno", "apellido_paterno", False, "Requerido para individuos"),
    ("apellido_materno", "apellido_materno", False, ""),
    ("nombre_comercial", "nombre_comercial", False, ""),
    ("tipo_identificacion", "tipo_identificacion", True, "ssn | ein"),
    ("identificacion", "identificacion_nueva", True, "9 dígitos, con o sin guiones"),
    ("direccion", "direccion_linea1", False, ""),
    ("direccion_2", "direccion_linea2", False, ""),
    ("ciudad", "ciudad", False, ""),
    ("estado", "estado", False, "PR por defecto"),
    ("codigo_postal", "codigo_postal", False, ""),
    ("telefono", "telefono", False, ""),
    ("email", "email", False, ""),
    ("descripcion_servicio", "descripcion_servicio", False, "Servicio que presta"),
    ("fecha_inicio", "fecha_inicio", False, "AAAA-MM-DD o MM/DD/AAAA"),
    ("relevo", "relevo", False, "ninguno | parcial | total | declaracion_jurada"),
    ("relevo_porcentaje", "relevo_porcentaje", False, "Solo relevo parcial (%)"),
    ("relevo_vigente_hasta", "relevo_vigente_hasta", False, "Requerido para relevo parcial o total"),
    ("relevo_numero", "relevo_numero", False, "Número del certificado"),
    ("deposito_directo", "deposito_directo", False, "si | no"),
    ("banco_nombre", "banco_nombre", False, ""),
    ("banco_ruta", "banco_ruta", False, "9 dígitos"),
    ("banco_cuenta", "cuenta_nueva", False, ""),
    ("banco_tipo_cuenta", "banco_tipo_cuenta", False, "cheques | ahorros"),
    ("notas", "notas", False, ""),
]
DEFECTOS_PROVEEDOR = {
    "estado": "PR",
    "relevo": ProveedorServicios.Relevo.NINGUNO,
    "banco_tipo_cuenta": ProveedorServicios.TipoCuenta.CHEQUES,
}


def procesar_proveedores(archivo, compania, usuario, solo_validar=True) -> Resultado:
    resultado = Resultado()
    filas = _leer(
        archivo, "Proveedores", COLUMNAS_PROVEEDORES,
        {"identificacion": 9, "banco_ruta": 9, "codigo_postal": 5}, resultado,
    )
    if filas is None:
        return resultado
    choices = {
        f.name: f.choices for f in ProveedorServicios._meta.fields if f.choices
    }
    vistos_id, vistos_num, validos = {}, {}, []
    for indice, fila in enumerate(filas, start=2):
        if hojas.fila_vacia(fila):
            continue
        resultado.total_filas += 1
        if resultado.total_filas > MAX_FILAS:
            resultado.errores.append(ErrorFila(indice, "", f"Máximo {MAX_FILAS} filas por archivo."))
            break
        errores_antes = len(resultado.errores)
        datos = _datos_de_fila(fila, COLUMNAS_PROVEEDORES, {"deposito_directo"}, choices, DEFECTOS_PROVEEDOR, indice, resultado)
        form = ProveedorServiciosForm(datos, compania=compania)
        if not form.is_valid():
            _errores_de_form(form, COLUMNAS_PROVEEDORES, indice, resultado)
            continue
        if len(resultado.errores) > errores_antes:
            continue
        clave = (form.cleaned_data["tipo_identificacion"], form.cleaned_data["identificacion_nueva"])
        if clave in vistos_id:
            resultado.errores.append(ErrorFila(indice, "identificacion", f"Identificación repetida en el archivo (fila {vistos_id[clave]})."))
            continue
        vistos_id[clave] = indice
        numero = form.cleaned_data["numero"]
        if numero in vistos_num:
            resultado.errores.append(ErrorFila(indice, "numero", f"Número repetido en el archivo (fila {vistos_num[numero]})."))
            continue
        vistos_num[numero] = indice
        validos.append(form)

    if resultado.errores or solo_validar or not validos:
        return resultado
    with transaction.atomic():
        for form in validos:
            proveedor = form.save(commit=False)
            proveedor.creado_por = usuario
            proveedor.save()
            resultado.creados.append(proveedor)
    return resultado


def plantilla_proveedores() -> bytes:
    return hojas.plantilla_xlsx(
        "Proveedores",
        [(c[0], c[2], c[3]) for c in COLUMNAS_PROVEEDORES],
        ("numero", "identificacion", "banco_ruta", "banco_cuenta", "codigo_postal"),
        [
            "Las columnas en amarillo son requeridas. Un proveedor por fila.",
            "Si alguna fila tiene errores, no se importa ninguna. Corrija y vuelva a subir.",
        ],
    )


# --- Pagos -------------------------------------------------------------------------

COLUMNAS_PAGOS = [
    ("numero_proveedor", "proveedor", True, "Número del proveedor en el sistema"),
    ("fecha", "fecha", True, "AAAA-MM-DD o MM/DD/AAAA"),
    ("monto", "monto", True, "Monto bruto, sin signo de $"),
    ("referencia", "referencia", False, "Número de factura"),
    ("descripcion", "descripcion", False, ""),
    ("metodo_pago", "metodo", False, "cheque | deposito | transferencia | efectivo | otro (cheque por defecto)"),
    ("numero_cheque", "numero_cheque", False, "Requerido si el método es cheque"),
    ("exento", "exento", False, "si | no — pago exento de retención"),
    ("motivo_exencion", "motivo_exencion", False, "Requerido si exento = si"),
]


def procesar_pagos(archivo, compania, usuario, solo_validar=True) -> Resultado:
    """
    Los pagos se calculan en el orden del archivo: la exención anual de cada
    proveedor se va consumiendo fila por fila.
    """
    resultado = Resultado()
    filas = _leer(archivo, "Pagos", COLUMNAS_PAGOS, {}, resultado)
    if filas is None:
        return resultado
    proveedores = {p.numero.lower(): p for p in ProveedorServicios.objects.filter(compania=compania, activo=True)}
    extra = {}  # acumulado de filas anteriores del archivo, por proveedor y año
    validos = []
    for indice, fila in enumerate(filas, start=2):
        if hojas.fila_vacia(fila):
            continue
        resultado.total_filas += 1
        if resultado.total_filas > MAX_FILAS:
            resultado.errores.append(ErrorFila(indice, "", f"Máximo {MAX_FILAS} filas por archivo."))
            break
        errores_antes = len(resultado.errores)
        datos = _datos_de_fila(
            fila, COLUMNAS_PAGOS, {"exento"}, {"metodo": PagoServicio.Metodo.choices},
            {"metodo": PagoServicio.Metodo.CHEQUE}, indice, resultado,
        )
        proveedor = proveedores.get(fila.get("numero_proveedor", "").strip().lower())
        if proveedor is None:
            resultado.errores.append(
                ErrorFila(indice, "numero_proveedor", "No existe un proveedor activo con ese número en esta compañía.")
            )
            continue
        datos["proveedor"] = proveedor.pk
        datos["monto"] = datos.get("monto", "").replace("$", "").replace(",", "")
        form = PagoForm(datos, compania=compania)
        if not form.is_valid():
            _errores_de_form(form, COLUMNAS_PAGOS, indice, resultado)
            continue
        if len(resultado.errores) > errores_antes:
            continue
        d = form.cleaned_data
        clave = (proveedor.pk, d["fecha"].year)
        try:
            calculo = servicio_pagos.calcular(
                proveedor, d["fecha"], d["monto"], exento=d["exento"], acumulado_extra=extra.get(clave, Decimal("0"))
            )
        except (servicio_pagos.ErrorPago, ValueError) as error:
            resultado.errores.append(ErrorFila(indice, "fecha", str(error)))
            continue
        extra[clave] = extra.get(clave, Decimal("0")) + calculo.resultado.monto
        resultado.avisos.update(calculo.avisos)
        resultado.vista_previa.append({"fila": indice, "proveedor": proveedor, "fecha": d["fecha"], "r": calculo.resultado})
        validos.append(d)

    if resultado.errores or solo_validar or not validos:
        return resultado
    with transaction.atomic():
        for d in validos:
            pago, _avisos = servicio_pagos.registrar(
                proveedor=d["proveedor"],
                fecha=d["fecha"],
                monto=d["monto"],
                usuario=usuario,
                exento=d["exento"],
                motivo_exencion=d.get("motivo_exencion", ""),
                referencia=d.get("referencia", ""),
                descripcion=d.get("descripcion", ""),
                metodo=d["metodo"],
                numero_cheque=d.get("numero_cheque", ""),
                origen=PagoServicio.Origen.IMPORTADO,
            )
            resultado.creados.append(pago)
    return resultado


def plantilla_pagos() -> bytes:
    return hojas.plantilla_xlsx(
        "Pagos",
        [(c[0], c[2], c[3]) for c in COLUMNAS_PAGOS],
        ("numero_proveedor", "referencia", "numero_cheque"),
        [
            "Un pago por fila. La retención se calcula sola con la tasa y la exención anual configuradas",
            "para el año del pago, respetando el relevo de cada proveedor, en el orden de las filas.",
            "Si alguna fila tiene errores, no se importa ninguna.",
        ],
    )
