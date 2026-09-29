from django.conf import settings


class CabecerasSeguridadMiddleware:
    """CSP estricta, Permissions-Policy y no-cache en páginas con datos sensibles."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", settings.NOMINA_CSP)
        response.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        usuario = getattr(request, "user", None)
        if usuario is not None and usuario.is_authenticated:
            # Evita que el navegador guarde en caché páginas con SSN/salarios.
            response["Cache-Control"] = "no-store, max-age=0"
            response["Pragma"] = "no-cache"
        return response
