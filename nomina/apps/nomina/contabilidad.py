"""
Asiento de diario de la nómina para QuickBooks Online.

Débitos: salarios (ingresos) y aportaciones patronales (gasto).
Créditos: retenciones y aportaciones por pagar (pasivo), deducciones por pagar y el neto por pagar.
Bruto = retenciones + deducciones + neto, así que el asiento siempre cuadra.

Cada concepto se asigna a una cuenta del catálogo de la compañía; si no se asigna, se usa la cuenta
por defecto del grupo.
"""

import csv
import io
from collections import OrderedDict
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Sum

from .models import CuentaContable, LineaResultado

CERO = Decimal("0")

# clave → (descripción, cuenta sugerida). Las claves «grupo:*» son la cuenta por defecto del grupo.
POR_DEFECTO = OrderedDict([
    ("gasto:*", ("Salarios y demás ingresos de los empleados", "Gastos de nómina:Salarios")),
    ("patronal:*", ("Aportaciones patronales (gasto)", "Gastos de nómina:Contribuciones patronales")),
    ("pasivo:retencion_pr", ("Retención de contribución sobre ingresos (PR)", "Retención de PR por pagar")),
    ("pasivo:retencion_federal", ("Retención federal", "IRS 941 por pagar")),
    ("pasivo:ss_empleado", ("Seguro Social del empleado", "IRS 941 por pagar")),
    ("pasivo:ss_patrono", ("Seguro Social patronal", "IRS 941 por pagar")),
    ("pasivo:medicare_empleado", ("Medicare del empleado", "IRS 941 por pagar")),
    ("pasivo:medicare_adicional", ("Medicare adicional", "IRS 941 por pagar")),
    ("pasivo:medicare_patrono", ("Medicare patronal", "IRS 941 por pagar")),
    ("pasivo:futa", ("FUTA", "FUTA por pagar")),
    ("pasivo:suta", ("Desempleo estatal", "Desempleo estatal por pagar")),
    ("pasivo:aportacion_especial", ("Aportación especial", "Desempleo estatal por pagar")),
    ("pasivo:sinot_empleado", ("SINOT del empleado", "SINOT por pagar")),
    ("pasivo:sinot_patrono", ("SINOT patronal", "SINOT por pagar")),
    ("pasivo:choferil_empleado", ("Seguro Choferil del empleado", "Seguro Choferil por pagar")),
    ("pasivo:choferil_patrono", ("Seguro Choferil patronal", "Seguro Choferil por pagar")),
    ("pasivo:cfse", ("CFSE (provisión)", "CFSE por pagar")),
    ("pasivo:*", ("Otras retenciones por pagar", "Retenciones por pagar")),
    ("deduccion:*", ("Deducciones de los empleados", "Deducciones de empleados por pagar")),
    ("neto", ("Neto pagado a los empleados", "Nómina por pagar")),
])


def claves(compania=None):
    """Todas las claves que se pueden asignar: las fijas y una por cada concepto de ingreso y deducción."""
    from apps.parametros.models import ConceptoDeduccion, ConceptoIngreso

    salida = OrderedDict((k, v[0]) for k, v in POR_DEFECTO.items())
    for c in ConceptoIngreso.objects.order_by("nombre"):
        salida[f"gasto:{c.codigo}"] = f"Ingreso: {c.nombre}"
    for c in ConceptoDeduccion.objects.order_by("nombre"):
        salida[f"deduccion:{c.codigo}"] = f"Deducción: {c.nombre}"
    for codigo in ("ss_patrono", "medicare_patrono", "futa", "suta", "aportacion_especial", "sinot_patrono",
                   "choferil_patrono", "cfse"):
        salida[f"patronal:{codigo}"] = f"Gasto: {POR_DEFECTO['pasivo:' + codigo][0]}"
    return salida


def mapa(compania) -> dict:
    return dict(CuentaContable.objects.filter(compania=compania).values_list("clave", "cuenta"))


def cuenta_para(asignadas: dict, clave: str) -> str:
    """
    Orden: la asignada al concepto; la sugerida para ese concepto (p. ej. el 941); la asignada al grupo
    («otras»); la sugerida para el grupo.
    """
    grupo = clave.split(":")[0] + ":*" if ":" in clave else clave
    if asignadas.get(clave):
        return asignadas[clave]
    if clave in POR_DEFECTO:
        return POR_DEFECTO[clave][1]
    return asignadas.get(grupo) or POR_DEFECTO[grupo][1]


@dataclass
class Linea:
    cuenta: str
    debito: Decimal
    credito: Decimal
    descripcion: str


def asiento(lineas_qs, asignadas: dict) -> list[Linea]:
    """Agrupa por cuenta. `lineas_qs` son las LineaResultado de una o varias nóminas cerradas."""
    movimientos = OrderedDict()  # cuenta → [debito, credito, descripciones]

    def sumar(cuenta, monto, lado, descripcion):
        m = movimientos.setdefault(cuenta, [CERO, CERO, []])
        if monto < 0:  # reversos: el monto negativo va al otro lado
            lado, monto = 1 - lado, -monto
        m[lado] += monto
        if descripcion not in m[2]:
            m[2].append(descripcion)

    datos = lineas_qs.values("grupo", "codigo", "nombre").annotate(total=Sum("monto")).order_by("grupo", "codigo")
    neto = CERO
    for d in datos:
        monto = Decimal(d["total"] or 0).quantize(Decimal("0.01"))
        if not monto:
            continue
        grupo, codigo, nombre = d["grupo"], d["codigo"], d["nombre"]
        if grupo == LineaResultado.Grupo.INGRESO:
            sumar(cuenta_para(asignadas, f"gasto:{codigo}"), monto, 0, nombre)
            neto += monto
        elif grupo == LineaResultado.Grupo.RETENCION:
            sumar(cuenta_para(asignadas, f"pasivo:{codigo}"), monto, 1, nombre)
            neto -= monto
        elif grupo == LineaResultado.Grupo.DEDUCCION:
            sumar(cuenta_para(asignadas, f"deduccion:{codigo}"), monto, 1, nombre)
            neto -= monto
        else:
            sumar(cuenta_para(asignadas, f"patronal:{codigo}"), monto, 0, nombre)
            sumar(cuenta_para(asignadas, f"pasivo:{codigo}"), monto, 1, nombre)
    if neto:
        sumar(cuenta_para(asignadas, "neto"), neto, 1, "Neto a pagar")
    salida = []
    for cuenta, (debito, credito, descripciones) in movimientos.items():
        # Si la misma cuenta tiene débito y crédito, queda la diferencia.
        diferencia = debito - credito
        if diferencia:
            salida.append(Linea(cuenta, max(diferencia, CERO), max(-diferencia, CERO), ", ".join(descripciones)[:200]))
    return salida


def cuadra(lineas: list[Linea]) -> bool:
    return sum((l.debito for l in lineas), CERO) == sum((l.credito for l in lineas), CERO)


def csv_qbo(lineas: list[Linea], numero: str, fecha, memo: str) -> bytes:
    """CSV para *Importar datos → Asientos de diario* de QuickBooks Online (las columnas se asocian al importar)."""
    salida = io.StringIO()
    escritor = csv.writer(salida)
    escritor.writerow(["Journal No", "Journal Date", "Account", "Debits", "Credits", "Description", "Name", "Memo"])
    for l in lineas:
        escritor.writerow([
            numero, f"{fecha:%m/%d/%Y}", _seguro(l.cuenta),
            f"{l.debito:.2f}" if l.debito else "", f"{l.credito:.2f}" if l.credito else "",
            _seguro(l.descripcion), "", _seguro(memo),
        ])
    return salida.getvalue().encode("utf-8-sig")


def _seguro(texto):
    from apps.core.hojas import celda_segura

    return celda_segura(texto)
