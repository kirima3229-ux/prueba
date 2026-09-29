from django.urls import path

from . import views

app_name = "planillas"

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("<slug:codigo>/", views.planilla, name="planilla"),
]
