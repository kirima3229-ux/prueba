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
    path("auditoria/", include("apps.auditoria.urls")),
]

handler403 = "apps.core.views.error_403"
handler404 = "apps.core.views.error_404"
