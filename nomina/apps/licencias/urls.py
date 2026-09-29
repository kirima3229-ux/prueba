from django.urls import path

from . import views

app_name = "licencias"

urlpatterns = [
    path("", views.balances, name="balances"),
    path("acumular/", views.acumular, name="acumular"),
    path("empleado/<int:pk>/", views.empleado, name="empleado"),
    path("bono-navidad/", views.bono, name="bono"),
]
