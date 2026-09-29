from django.urls import path

from . import views

app_name = "parametros"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("copiar/", views.copiar, name="copiar"),
    path("anio/<int:anio>/", views.anio, name="anio"),
    path("salario-minimo/nuevo/", views.salario_minimo, name="minimo_nuevo"),
    path("salario-minimo/<int:pk>/", views.salario_minimo, name="minimo_editar"),
    path("ingresos/nuevo/", views.concepto_ingreso, name="ingreso_nuevo"),
    path("ingresos/<int:pk>/", views.concepto_ingreso, name="ingreso_editar"),
    path("deducciones/nuevo/", views.concepto_deduccion, name="deduccion_nuevo"),
    path("deducciones/<int:pk>/", views.concepto_deduccion, name="deduccion_editar"),
]
