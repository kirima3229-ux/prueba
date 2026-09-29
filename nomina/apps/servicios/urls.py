from django.urls import path

from . import views

app_name = "servicios"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuevo/", views.nuevo, name="nuevo"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/estado/", views.cambiar_estado, name="cambiar_estado"),
]
