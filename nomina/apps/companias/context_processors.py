def compania_activa(request):
    usuario = getattr(request, "user", None)
    if usuario is None or not usuario.is_authenticated:
        return {}
    return {
        "compania_activa": getattr(request, "compania", None),
        "companias_disponibles": usuario.companias_accesibles().filter(activa=True),
    }
