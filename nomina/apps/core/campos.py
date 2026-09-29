"""Campo de modelo cifrado y envoltorio que evita mostrar datos sensibles por error."""

from django.core.exceptions import FieldError
from django.db import models

from . import cifrado


def enmascarar(valor: str, visibles: int = 4) -> str:
    if not valor:
        return ""
    if len(valor) <= visibles:
        return "•" * len(valor)
    return "•" * 4 + valor[-visibles:]


class DatoSensible:
    """
    Valor descifrado envuelto. Al convertirlo a texto (plantillas, logs,
    mensajes de error) SIEMPRE sale enmascarado. Para obtener el valor real
    hay que llamar explícitamente a .revelar() — solo se hace para archivos
    de agencias y formularios oficiales.
    """

    __slots__ = ("_valor",)

    def __init__(self, valor: str):
        self._valor = valor

    def revelar(self) -> str:
        return self._valor

    def ultimos(self, n: int = 4) -> str:
        return self._valor[-n:]

    def __str__(self):
        return enmascarar(self._valor)

    def __repr__(self):
        return f"<DatoSensible {enmascarar(self._valor)}>"

    def __bool__(self):
        return bool(self._valor)

    def __eq__(self, otro):
        if isinstance(otro, DatoSensible):
            return self._valor == otro._valor
        if isinstance(otro, str):
            return self._valor == otro
        return NotImplemented

    def __hash__(self):
        return hash(self._valor)


class CampoCifrado(models.TextField):
    """
    Texto cifrado con AES-256-GCM. En Python el valor es un DatoSensible.
    No admite búsquedas (el texto cifrado cambia cada vez); para buscar se
    usa un índice ciego en otra columna.
    """

    description = "Texto cifrado (AES-256-GCM)"

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("null", True)
        kwargs.setdefault("blank", True)
        super().__init__(*args, **kwargs)

    def _contexto(self) -> str:
        return f"{self.model._meta.label_lower}.{self.name}"

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return None
        return DatoSensible(cifrado.descifrar(value, self._contexto()))

    def to_python(self, value):
        if value is None or isinstance(value, DatoSensible):
            return value
        if value == "":
            return None
        if cifrado.es_cifrado(value):
            return DatoSensible(cifrado.descifrar(value, self._contexto()))
        return DatoSensible(str(value))

    def get_prep_value(self, value):
        if value is None:
            return None
        texto = value.revelar() if isinstance(value, DatoSensible) else str(value)
        if texto == "":
            return None
        if cifrado.es_cifrado(texto):
            return texto
        return cifrado.cifrar(texto, self._contexto())

    def value_to_string(self, obj):
        # Serialización (dumpdata): se exporta cifrado, nunca en claro ni enmascarado.
        return self.get_prep_value(self.value_from_object(obj))

    def get_lookup(self, lookup_name):
        if lookup_name != "isnull":
            raise FieldError(
                f"El campo cifrado '{self.name}' no admite búsquedas '{lookup_name}'. "
                "Use el índice ciego correspondiente."
            )
        return super().get_lookup(lookup_name)
