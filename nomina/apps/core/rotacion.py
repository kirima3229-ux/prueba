"""
Rotación de llaves de cifrado.

1. Llaves de los campos: se añade una llave nueva a NOMINA_LLAVES_CIFRADO, se hace activa en NOMINA_LLAVE_ACTIVA
   y `rotar_llaves` vuelve a cifrar con ella todos los valores que tengan otra llave. Después se puede quitar la
   llave vieja del .env (cuando no quede ningún valor ni respaldo que se necesite con ella).
2. Llave del índice ciego: `rotar_llaves --llave-indice-nueva=...` recalcula los índices (SSN, EIN,
   identificación de proveedores) con la llave nueva; después se cambia NOMINA_LLAVE_INDICE en el .env.

Se hace con SQL directo sobre cada columna para no disparar reglas de los modelos (registros cerrados o
inmutables): sólo cambia el texto cifrado, nunca el valor. Todo en una transacción.
"""

from collections import Counter
from dataclasses import dataclass, field

from django.apps import apps
from django.conf import settings
from django.db import connection, transaction

from . import cifrado
from .campos import CampoCifrado


@dataclass
class Resumen:
    por_llave: Counter = field(default_factory=Counter)  # (modelo.campo, llave) → valores
    recifrados: int = 0
    indices: int = 0


def campos_cifrados():
    for modelo in apps.get_models():
        for campo in modelo._meta.concrete_fields:
            if isinstance(campo, CampoCifrado):
                yield modelo, campo


def _filas(modelo, columnas):
    q = connection.ops.quote_name
    tabla = q(modelo._meta.db_table)
    pk = q(modelo._meta.pk.column)
    with connection.cursor() as cursor:
        # Tabla y columnas salen de los modelos (no del usuario) y van entre comillas.
        cursor.execute(f"SELECT {pk}, {', '.join(q(c) for c in columnas)} FROM {tabla}")  # nosec B608
        return cursor.fetchall()


def _actualizar(modelo, pk_valor, columna, valor):
    q = connection.ops.quote_name
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {q(modelo._meta.db_table)} SET {q(columna)} = %s WHERE {q(modelo._meta.pk.column)} = %s",  # nosec B608
            [valor, pk_valor],
        )


def inventario() -> Resumen:
    """Cuántos valores cifrados hay con cada llave (no cambia nada)."""
    resumen = Resumen()
    for modelo, campo in campos_cifrados():
        for _, valor in _filas(modelo, [campo.column]):
            if valor:
                resumen.por_llave[(f"{modelo._meta.label}.{campo.name}", cifrado.id_llave_de(valor))] += 1
    return resumen


# Índices ciegos: modelo, columna del índice, campo cifrado, columna auxiliar, contexto del HMAC.
INDICES = [
    ("empleados.Empleado", "ssn_indice", "ssn", None, lambda aux: "ssn"),
    ("companias.Compania", "ein_indice", "ein", None, lambda aux: "ein"),
    ("servicios.ProveedorServicios", "identificacion_indice", "identificacion", "tipo_identificacion",
     lambda aux: aux),
]


@transaction.atomic
def rotar(llave_indice_nueva: bytes | None = None) -> Resumen:
    activa = str(settings.NOMINA_LLAVE_ACTIVA).strip()
    resumen = Resumen()
    for modelo, campo in campos_cifrados():
        contexto = f"{modelo._meta.label_lower}.{campo.name}"
        for pk_valor, valor in _filas(modelo, [campo.column]):
            if not valor:
                continue
            if cifrado.id_llave_de(valor) != activa:
                texto = cifrado.descifrar(valor, contexto)
                nuevo = cifrado.cifrar(texto, contexto)
                if cifrado.descifrar(nuevo, contexto) != texto:  # comprobación antes de escribir
                    raise cifrado.ErrorCifrado("La verificación del recifrado falló; no se cambió nada.")
                _actualizar(modelo, pk_valor, campo.column, nuevo)
                resumen.recifrados += 1
            resumen.por_llave[(f"{modelo._meta.label}.{campo.name}", activa)] += 1
    if llave_indice_nueva is not None:
        for etiqueta, col_indice, nombre_campo, col_aux, contexto_indice in INDICES:
            modelo = apps.get_model(etiqueta)
            campo = modelo._meta.get_field(nombre_campo)
            contexto = f"{modelo._meta.label_lower}.{campo.name}"
            columnas = [campo.column] + ([col_aux] if col_aux else [])
            for fila in _filas(modelo, columnas):
                pk_valor, valor = fila[0], fila[1]
                if not valor:
                    continue
                texto = cifrado.descifrar(valor, contexto)
                aux = fila[2] if col_aux else None
                _actualizar(modelo, pk_valor, col_indice,
                            cifrado.indice_ciego(texto, contexto_indice(aux), llave=llave_indice_nueva))
                resumen.indices += 1
    return resumen
