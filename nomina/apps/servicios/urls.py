from django.urls import path

from . import views

app_name = "servicios"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuevo/", views.nuevo, name="nuevo"),
    path("importar/", views.importar_proveedores, name="importar_proveedores"),
    path("importar/plantilla.xlsx", views.plantilla_proveedores, name="plantilla_proveedores"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/estado/", views.cambiar_estado, name="cambiar_estado"),
    path("pagos/", views.pagos_lista, name="pagos"),
    path("pagos/nuevo/", views.pago_nuevo, name="pago_nuevo"),
    path("pagos/importar/", views.importar_pagos, name="importar_pagos"),
    path("pagos/importar/plantilla.xlsx", views.plantilla_pagos, name="plantilla_pagos"),
    path("pagos/<int:pk>/", views.pago_detalle, name="pago_detalle"),
    path("pagos/<int:pk>/anular/", views.pago_anular, name="pago_anular"),
    path("resumen/", views.resumen_anual, name="resumen"),
    path("trimestral/", views.trimestral, name="trimestral"),
    path("depositos/", views.depositos_lista, name="depositos"),
    path("depositos/nuevo/", views.deposito_nuevo, name="deposito_nuevo"),
    path("depositos/<int:pk>/", views.deposito_detalle, name="deposito_detalle"),
    path("depositos/<int:pk>/anular/", views.deposito_anular, name="deposito_anular"),
    path("configuracion/", views.config_lista, name="config_lista"),
    path("configuracion/nueva/", views.config_form, name="config_nueva"),
    path("configuracion/<int:pk>/", views.config_form, name="config_editar"),
]
