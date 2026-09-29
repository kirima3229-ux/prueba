from django.urls import include, path

from apps.core import views as core_views

# El panel de administración de Django no se publica: toda la administración
# pasa por pantallas propias que registran cada cambio en la bitácora.
urlpatterns = [
    path("", core_views.inicio, name="inicio"),
    path("cuenta/", include("apps.cuentas.urls")),
    path("companias/", include("apps.companias.urls")),
    path("empleados/", include("apps.empleados.urls")),
    path("servicios/", include("apps.servicios.urls")),
    path("configuracion/", include("apps.parametros.urls")),
    path("calculo/", include("apps.calculo.urls")),
    path("licencias/", include("apps.licencias.urls")),
    path("nomina/", include("apps.nomina.urls")),
    path("planillas/", include("apps.planillas.urls")),
    path("auditoria/", include("apps.auditoria.urls")),
]

handler403 = "apps.core.views.error_403"
handler404 = "apps.core.views.error_404"
