"""Registro de eventos en la bitácora y utilidades para describir cambios."""

import json
from decimal import Decimal

from django.db import connection, models, transaction
from django.utils import timezone

from apps.core.campos import CampoCifrado, DatoSensible
from apps.core.red import obtener_ip

from .models import Accion, RegistroAuditoria

__all__ = ["Accion", "registrar", "instantanea", "diferencias", "verificar_cadena"]

HASH_INICIAL = "0" * 64
# Número arbitrario para el candado de PostgreSQL que serializa la cadena.
_CANDADO_AUDITORIA = 7_301_964


def _normalizar_json(valor):
    return json.loads(json.dumps(valor, default=str, ensure_ascii=False))


def registrar(
    request=None,
    accion=None,
    *,
    usuario=None,
    objeto=None,
    compania=None,
    descripcion="",
    cambios=None,
    ip=None,
):
    """Agrega un registro a la bitácora. Nunca incluir datos sensibles en claro."""
    if request is not None:
        if usuario is None and getattr(request, "user", None) is not None:
            if request.user.is_authenticated:
                usuario = request.user
        if ip is None:
            ip = obtener_ip(request)
        if compania is None:
            compania = getattr(request, "compania", None)

    registro = RegistroAuditoria(
        fecha=timezone.now(),
        usuario=usuario if usuario is not None and usuario.pk else None,
        usuario_nombre=usuario.get_username() if usuario is not None else "",
        ip=ip,
        accion=accion,
        compania_id=compania.pk if compania is not None else None,
        compania_nombre=str(compania) if compania is not None else "",
        objeto_tipo=objeto._meta.label if objeto is not None else "",
        objeto_id=str(objeto.pk) if objeto is not None and objeto.pk is not None else "",
        objeto_repr=str(objeto)[:255] if objeto is not None else "",
        descripcion=descripcion,
        cambios=_normalizar_json(cambios or {}),
    )
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(%s)", [_CANDADO_AUDITORIA])
        ultimo = RegistroAuditoria.objects.order_by("-id").values_list("hash", flat=True).first()
        registro.hash_anterior = ultimo or HASH_INICIAL
        registro.hash = registro.calcular_hash()
        registro.save()
    return registro


def _valor_legible(campo, valor):
    if valor is None:
        return None
    if isinstance(campo, models.DecimalField):
        # Misma precisión antes y después de guardar (10.5 y 10.5000 son iguales).
        return str(Decimal(str(valor)).quantize(Decimal(1).scaleb(-campo.decimal_places)))
    if isinstance(valor, Decimal):
        return str(valor)
    if hasattr(valor, "isoformat"):
        return valor.isoformat()
    if campo.choices:
        return str(dict(campo.flatchoices).get(valor, valor))
    return valor


def instantanea(obj) -> dict:
    """
    Foto de los campos de un objeto para comparar antes/después.
    Los campos cifrados se guardan solo en memoria para detectar cambios;
    `diferencias` nunca los escribe en la bitácora.
    """
    excluir = set(getattr(obj, "CAMPOS_NO_AUDITABLES", ()))
    foto = {}
    for campo in obj._meta.concrete_fields:
        if campo.primary_key or campo.name in excluir:
            continue
        valor = getattr(obj, campo.attname)
        if isinstance(campo, CampoCifrado):
            foto[campo.name] = ("__sensible__", valor.revelar() if isinstance(valor, DatoSensible) else valor)
        else:
            foto[campo.name] = _valor_legible(campo, valor)
    return foto


def diferencias(antes: dict, despues: dict) -> dict:
    cambios = {}
    for nombre in sorted(set(antes) | set(despues)):
        a, d = antes.get(nombre), despues.get(nombre)
        if a == d:
            continue
        if isinstance(a, tuple) or isinstance(d, tuple):
            # Campo cifrado: se registra que cambió, nunca el valor.
            cambios[nombre] = {"modificado": True, "sensible": True}
        else:
            cambios[nombre] = {"antes": a, "despues": d}
    return cambios


def verificar_cadena():
    """Recorre la bitácora y devuelve (ok, total, lista_de_problemas)."""
    problemas = []
    anterior = HASH_INICIAL
    total = 0
    for registro in RegistroAuditoria.objects.order_by("id").iterator(chunk_size=2000):
        total += 1
        if registro.hash_anterior != anterior:
            problemas.append(f"Registro #{registro.pk}: la cadena está rota (falta o se alteró un registro anterior).")
        if registro.calcular_hash() != registro.hash:
            problemas.append(f"Registro #{registro.pk}: el contenido fue alterado.")
        anterior = registro.hash
    return (not problemas, total, problemas)
