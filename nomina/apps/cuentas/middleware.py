from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect


class RequisitosCuentaMiddleware:
    """
    Tras la entrada, hace cumplir:
    1. Si el usuario tiene 2FA, la sesión debe estar verificada con el código
       (se aplica a todas las páginas con sesión, sin excepciones).
    2. Si la contraseña es temporal, debe cambiarla antes de seguir.
    3. Los administradores deben tener 2FA configurado.
    Las vistas marcadas con @exento_requisitos_cuenta (cambiar contraseña,
    configurar 2FA, salir) se saltan solo los puntos 2 y 3.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, vista, args, kwargs):
        usuario = request.user
        if not usuario.is_authenticated or getattr(vista, "login_required", True) is False:
            return None

        if usuario.tiene_2fa() and not usuario.is_verified():
            logout(request)
            messages.error(request, "Debe verificar su código de autenticación.")
            return redirect("cuentas:entrar")

        if getattr(vista, "exento_requisitos_cuenta", False):
            return None

        if usuario.debe_cambiar_contrasena:
            messages.warning(request, "Debe cambiar su contraseña temporal antes de continuar.")
            return redirect("cuentas:cambiar_contrasena")

        if usuario.es_admin and not usuario.tiene_2fa():
            messages.warning(
                request,
                "Los administradores deben configurar la autenticación de dos pasos (2FA).",
            )
            return redirect("cuentas:configurar_2fa")
        return None
