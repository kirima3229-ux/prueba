from django.urls import path

from . import views

app_name = "calculo"

urlpatterns = [
    path("simulador/", views.simulador, name="simulador"),
    path("mesada/", views.mesada, name="mesada"),
]
