from django.shortcuts import render

from apps.auditoria.models import RegistroAuditoria
from apps.companias.models import EstadoVerificacion


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
        )
    if request.user.es_admin:
        contexto["actividad"] = RegistroAuditoria.objects.all()[:10]
    return render(request, "inicio.html", contexto)


def error_403(request, exception=None):
    return render(request, "errores/403.html", status=403)


def error_404(request, exception=None):
    return render(request, "errores/404.html", status=404)
