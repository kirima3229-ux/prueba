CLAVE_SESION = "compania_activa_id"


class CompaniaActivaMiddleware:
    """
    Pone en request.compania la compañía seleccionada, validando que el
    usuario tenga acceso. Si la compañía guardada en la sesión ya no es
    accesible, se descarta.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.compania = None
        usuario = getattr(request, "user", None)
        if usuario is not None and usuario.is_authenticated:
            accesibles = usuario.companias_accesibles()
            compania_id = request.session.get(CLAVE_SESION)
            compania = accesibles.filter(pk=compania_id).first() if compania_id else None
            if compania is None:
                compania = accesibles.filter(activa=True).first()
                if compania is not None:
                    request.session[CLAVE_SESION] = compania.pk
                else:
                    request.session.pop(CLAVE_SESION, None)
            request.compania = compania
        return self.get_response(request)
