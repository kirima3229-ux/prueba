from datetime import datetime, time

from django.core.paginator import Paginator
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.permisos import requiere_admin

from .models import Accion, RegistroAuditoria
from .servicios import verificar_cadena


def _fecha(texto):
    try:
        return datetime.strptime(texto, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


@requiere_admin
def lista(request):
    registros = RegistroAuditoria.objects.all()
    filtros = {
        "accion": request.GET.get("accion", ""),
        "usuario": request.GET.get("usuario", "").strip(),
        "compania": request.GET.get("compania", ""),
        "desde": request.GET.get("desde", ""),
        "hasta": request.GET.get("hasta", ""),
    }
    if filtros["accion"] in Accion.values:
        registros = registros.filter(accion=filtros["accion"])
    if filtros["usuario"]:
        registros = registros.filter(usuario_nombre__icontains=filtros["usuario"])
    if filtros["compania"].isdigit():
        registros = registros.filter(compania_id=int(filtros["compania"]))
    zona = timezone.get_current_timezone()
    if desde := _fecha(filtros["desde"]):
        registros = registros.filter(fecha__gte=datetime.combine(desde, time.min, tzinfo=zona))
    if hasta := _fecha(filtros["hasta"]):
        registros = registros.filter(fecha__lte=datetime.combine(hasta, time.max, tzinfo=zona))
    pagina = Paginator(registros, 100).get_page(request.GET.get("pagina"))
    parametros = request.GET.copy()
    parametros.pop("pagina", None)
    return render(
        request,
        "auditoria/lista.html",
        {
            "pagina": pagina,
            "filtros": filtros,
            "acciones": Accion.choices,
            "companias": request.user.companias_accesibles(),
            "parametros": parametros.urlencode(),
        },
    )


@requiere_admin
@require_POST
def verificar(request):
    ok, total, problemas = verificar_cadena()
    return render(request, "auditoria/verificacion.html", {"ok": ok, "total": total, "problemas": problemas})
