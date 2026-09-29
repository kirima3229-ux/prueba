from django.conf import settings


def obtener_ip(request) -> str | None:
    """
    IP del cliente. Solo confía en X-Forwarded-For si hay proxies configurados
    (NOMINA_PROXIES_CONFIABLES); si no, un usuario podría falsificarla.
    """
    proxies = settings.NOMINA_PROXIES_CONFIABLES
    if proxies > 0:
        cadena = request.META.get("HTTP_X_FORWARDED_FOR", "")
        ips = [ip.strip() for ip in cadena.split(",") if ip.strip()]
        if len(ips) >= proxies:
            return ips[-proxies]
    return request.META.get("REMOTE_ADDR")
