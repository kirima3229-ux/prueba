from django.urls import path

from . import views

app_name = "cuentas"

urlpatterns = [
    path("entrar/", views.entrar, name="entrar"),
    path("verificar/", views.verificar, name="verificar"),
    path("salir/", views.salir, name="salir"),
    path("contrasena/", views.cambiar_contrasena, name="cambiar_contrasena"),
    path("2fa/", views.configurar_2fa, name="configurar_2fa"),
    path("2fa/desactivar/", views.desactivar_2fa, name="desactivar_2fa"),
    path("usuarios/", views.usuarios_lista, name="usuarios"),
    path("usuarios/nuevo/", views.usuario_nuevo, name="usuario_nuevo"),
    path("usuarios/<int:pk>/", views.usuario_editar, name="usuario_editar"),
    path("usuarios/<int:pk>/contrasena/", views.usuario_restablecer_contrasena, name="usuario_contrasena"),
    path("usuarios/<int:pk>/desbloquear/", views.usuario_desbloquear, name="usuario_desbloquear"),
    path("usuarios/<int:pk>/reiniciar-2fa/", views.usuario_reiniciar_2fa, name="usuario_reiniciar_2fa"),
]
