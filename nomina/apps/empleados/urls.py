from django.urls import path

from . import views

app_name = "empleados"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuevo/", views.nuevo, name="nuevo"),
    path("importar/", views.importar, name="importar"),
    path("importar/plantilla.xlsx", views.plantilla, name="plantilla"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/terminar/", views.terminar, name="terminar"),
    path("<int:pk>/reactivar/", views.reactivar, name="reactivar"),
]
