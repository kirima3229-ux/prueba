from django.urls import path

from . import views, views_reportes

app_name = "nomina"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuevo/", views.nuevo, name="nuevo"),
    path("reportes/", views_reportes.reportes_vista, name="reportes"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/calcular/", views.calcular, name="calcular"),
    path("<int:pk>/cerrar/", views.cerrar, name="cerrar"),
    path("<int:pk>/reversar/", views.reversar, name="reversar"),
    path("<int:pk>/talonarios.pdf", views.talonarios, name="talonarios"),
    path("<int:pk>/registro.xlsx", views.registro, name="registro"),
    path("<int:pk>/empleado/<int:entrada_pk>/", views.entrada, name="entrada"),
    path("<int:pk>/importar-horas/", views.importar_horas, name="importar_horas"),
    path("<int:pk>/cheques/", views.cheques_periodo, name="cheques"),
    path("<int:pk>/cheques.pdf", views.cheques_pdf, name="cheques_pdf"),
    path("<int:pk>/avisos-deposito.pdf", views.avisos_deposito, name="avisos_deposito"),
    path("cheques/formato/", views.formato_cheque, name="formato_cheque"),
    path("cheques/prueba-alineacion.pdf", views.prueba_alineacion, name="prueba_alineacion"),
    path("empleado/<int:pk>/deducciones/", views.deducciones_empleado, name="deducciones_empleado"),
]
