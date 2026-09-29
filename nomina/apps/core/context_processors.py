from django.conf import settings


def sistema(request):
    return {
        "NOMBRE_SISTEMA": "Nómina PR",
        "NOMBRE_FIRMA": "Quality Group",
        "MINUTOS_SESION": settings.SESSION_COOKIE_AGE // 60,
        "ENTORNO": settings.ENTORNO,
    }
