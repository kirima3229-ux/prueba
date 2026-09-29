"""Montos en letras para cheques, en español y en inglés."""

from decimal import ROUND_HALF_UP, Decimal

_UNIDADES = ["", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce",
             "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte",
             "veintiuno", "veintidós", "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete",
             "veintiocho", "veintinueve"]
_DECENAS = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"]
_CENTENAS = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos",
             "setecientos", "ochocientos", "novecientos"]


def _es_menor_mil(n: int, apocope: bool) -> str:
    """0 < n < 1000. Con apócope, «uno» termina en «un» (un mil, veintiún mil, un dólar)."""
    partes = []
    centenas, resto = divmod(n, 100)
    if centenas:
        partes.append("cien" if n == 100 else _CENTENAS[centenas])
    if resto:
        if resto < 30:
            palabra = _UNIDADES[resto]
        else:
            decena, unidad = divmod(resto, 10)
            palabra = _DECENAS[decena] + (f" y {_UNIDADES[unidad]}" if unidad else "")
        if apocope and palabra.endswith("uno"):
            palabra = palabra[:-3] + ("ún" if palabra == "veintiuno" else "un")
        partes.append(palabra)
    return " ".join(partes)


def entero_es(n: int, apocope: bool = False) -> str:
    if n == 0:
        return "cero"
    partes = []
    millones, resto = divmod(n, 1_000_000)
    miles, unidades = divmod(resto, 1000)
    if millones:
        partes.append("un millón" if millones == 1 else f"{_es_menor_mil(millones, True)} millones")
    if miles:
        partes.append("mil" if miles == 1 else f"{_es_menor_mil(miles, True)} mil")
    if unidades:
        partes.append(_es_menor_mil(unidades, apocope))
    return " ".join(partes)


_EN_UNIDADES = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
_EN_DECENAS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _en_menor_mil(n: int) -> str:
    partes = []
    centenas, resto = divmod(n, 100)
    if centenas:
        partes.append(f"{_EN_UNIDADES[centenas]} hundred")
    if resto:
        if resto < 20:
            partes.append(_EN_UNIDADES[resto])
        else:
            decena, unidad = divmod(resto, 10)
            partes.append(_EN_DECENAS[decena] + (f"-{_EN_UNIDADES[unidad]}" if unidad else ""))
    return " ".join(partes)


def entero_en(n: int) -> str:
    if n == 0:
        return "zero"
    partes = []
    for valor, nombre in ((1_000_000, "million"), (1000, "thousand")):
        grupo, n = divmod(n, valor)
        if grupo:
            partes.append(f"{_en_menor_mil(grupo)} {nombre}")
    if n:
        partes.append(_en_menor_mil(n))
    return " ".join(partes)


def monto_en_letras(monto, idioma: str = "es") -> str:
    """Monto de cheque en letras, en mayúsculas: «MIL DOSCIENTOS TREINTA Y CUATRO DÓLARES CON 56/100»."""
    monto = Decimal(monto).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if monto < 0:
        raise ValueError("Un cheque no puede tener un monto negativo.")
    if monto >= 1_000_000_000:
        raise ValueError("Monto demasiado grande para un cheque.")
    dolares = int(monto)
    centavos = int((monto - dolares) * 100)
    if idioma == "en":
        texto = f"{entero_en(dolares)} and {centavos:02d}/100 dollar{'' if dolares == 1 else 's'}"
    else:
        if dolares == 1:
            moneda = "un dólar"
        else:
            # «un millón de dólares», pero «un millón cien dólares».
            de = "de " if dolares >= 1_000_000 and dolares % 1_000_000 == 0 else ""
            moneda = f"{entero_es(dolares, apocope=True)} {de}dólares"
        texto = f"{moneda} con {centavos:02d}/100"
    return texto.upper()
