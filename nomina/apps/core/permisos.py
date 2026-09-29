"""Decoradores de acceso por rol y por compañía activa."""

from functools import wraps

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect


def requiere_rol(*roles):
    """Permite la vista solo a los roles indicados; registra el intento denegado."""

    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if request.user.rol not in roles:
                from apps.auditoria.servicios import Accion, registrar

                registrar(
                    request,
                    Accion.ACCESO_DENEGADO,
                    descripcion=f"Intento de acceso a {request.path}",
                )
                raise PermissionDenied("No tiene permiso para esta acción.")
            return vista(request, *args, **kwargs)

        return envoltura

    return decorador


def requiere_admin(vista):
    from apps.cuentas.models import Usuario

    return requiere_rol(Usuario.Rol.ADMIN)(vista)


def requiere_edicion(vista):
    """Administradores y preparadores (no solo lectura)."""
    from apps.cuentas.models import Usuario

    return requiere_rol(Usuario.Rol.ADMIN, Usuario.Rol.PREPARADOR)(vista)


def requiere_compania(vista):
    """La vista trabaja sobre la compañía activa (request.compania)."""

    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if request.compania is None:
            messages.info(request, "Seleccione una compañía para continuar.")
            return redirect("companias:lista")
        return vista(request, *args, **kwargs)

    return envoltura


def exento_requisitos_cuenta(vista):
    """
    Marca vistas accesibles aunque el usuario tenga requisitos pendientes
    (configurar 2FA o cambiar contraseña temporal).
    """
    vista.exento_requisitos_cuenta = True
    return vista
