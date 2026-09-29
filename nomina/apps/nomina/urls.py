from django.urls import path

from . import views

app_name = "nomina"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuevo/", views.nuevo, name="nuevo"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/calcular/", views.calcular, name="calcular"),
    path("<int:pk>/cerrar/", views.cerrar, name="cerrar"),
    path("<int:pk>/reversar/", views.reversar, name="reversar"),
    path("<int:pk>/talonarios.pdf", views.talonarios, name="talonarios"),
    path("<int:pk>/registro.xlsx", views.registro, name="registro"),
    path("<int:pk>/empleado/<int:entrada_pk>/", views.entrada, name="entrada"),
    path("empleado/<int:pk>/deducciones/", views.deducciones_empleado, name="deducciones_empleado"),
]
