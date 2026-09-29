from django.urls import path

from . import views

app_name = "companias"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nueva/", views.nueva, name="nueva"),
    path("seleccionar/", views.seleccionar, name="seleccionar"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/tasas/nuevas/", views.tasas_form, name="tasas_nuevas"),
    path("<int:pk>/tasas/<int:tasas_pk>/", views.tasas_form, name="tasas_editar"),
    path("<int:pk>/cfse/<int:cls_pk>/tasas/nueva/", views.tasa_cfse_form, name="tasa_cfse_nueva"),
    path("<int:pk>/cfse/<int:cls_pk>/tasas/<int:tasa_pk>/", views.tasa_cfse_form, name="tasa_cfse_editar"),
    path("<int:pk>/<slug:catalogo>/nuevo/", views.catalogo_form, name="catalogo_nuevo"),
    path("<int:pk>/<slug:catalogo>/<int:item_pk>/", views.catalogo_form, name="catalogo_editar"),
]
