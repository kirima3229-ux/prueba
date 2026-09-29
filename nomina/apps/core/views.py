from django.contrib.auth.decorators import login_not_required
from django.db import DatabaseError, connection
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.utils import timezone

from apps.auditoria.models import RegistroAuditoria
from apps.companias.models import EstadoVerificacion
from apps.servicios.depositos import total_pendiente


def inicio(request):
    compania = request.compania
    contexto = {}
    if compania is not None:
        empleados = compania.empleados.all()
        contexto.update(
            activos=empleados.filter(activo=True).count(),
            inactivos=empleados.filter(activo=False).count(),
            tasas_pendientes=compania.tasas.filter(estado=EstadoVerificacion.POR_VERIFICAR),
            departamentos=compania.departamentos.count(),
            proveedores=compania.proveedores_servicios.filter(activo=True).count(),
            relevos_vencidos=compania.proveedores_servicios.filter(
                activo=True, relevo_vigente_hasta__lt=timezone.localdate()
            ).exclude(relevo="ninguno"),
            retencion_pendiente=total_pendiente(compania),
        )
    if request.user.es_admin:
        contexto["actividad"] = RegistroAuditoria.objects.all()[:10]
    return render(request, "inicio.html", contexto)


def error_403(request, exception=None):
    return render(request, "errores/403.html", status=403)


def error_404(request, exception=None):
    return render(request, "errores/404.html", status=404)


@login_not_required
@require_GET
def salud(request):
    """Chequeo de salud para Docker/monitoreo: sin sesión, sin datos; sólo confirma que la base de datos responde."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except DatabaseError:
        return HttpResponse("base de datos no disponible", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")
