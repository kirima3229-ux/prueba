"""
Motor de cálculo de nómina de Puerto Rico (un empleado, un período).

Python puro: no depende de Django ni de la base de datos. Recibe los
parámetros del año, las tasas de la compañía, los datos del empleado, las
horas/ingresos/deducciones del período y los acumulados del año; devuelve
cada línea con su explicación.

Reglas generales:
- Todo en Decimal; cada contribución se redondea al centavo (mitad hacia arriba).
- Cada ingreso está marcado como sujeto o no a cada contribución (catálogo).
- Cada deducción indica si se resta antes de la retención de PR y/o antes de
  Seguro Social, Medicare, FUTA, desempleo estatal y SINOT.
- Los topes anuales se aplican con los acumulados del año.
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

CERO = Decimal("0")
CENTAVO = Decimal("0.01")
CIEN = Decimal("100")

PERIODOS_POR_ANIO = {"semanal": 52, "bisemanal": 26, "quincenal": 24, "mensual": 12}
SEMANAS_CHOFERIL = {"semanal": 1, "bisemanal": 2, "quincenal": 2, "mensual": 4}


def redondear(valor) -> Decimal:
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def dinero(valor) -> str:
    return f"${Decimal(valor):,.2f}"


def pct(valor) -> str:
    return f"{Decimal(valor).normalize():f}%"


# --- Entradas -----------------------------------------------------------------------


@dataclass(frozen=True)
class Tramo:
    desde: Decimal
    hasta: Decimal | None
    cuota_fija: Decimal
    tasa: Decimal


@dataclass(frozen=True)
class ReglaHorasExtra:
    diario: Decimal
    semanal: Decimal
    septimo_dia: Decimal
    periodo_alimentos: Decimal


@dataclass(frozen=True)
class Parametros:
    anio: int
    ss_tasa_empleado: Decimal
    ss_tasa_patrono: Decimal
    ss_tope: Decimal
    medicare_tasa_empleado: Decimal
    medicare_tasa_patrono: Decimal
    medicare_adicional_tasa: Decimal
    medicare_adicional_umbral: Decimal
    futa_tasa: Decimal
    futa_tope: Decimal
    desempleo_tope: Decimal
    sinot_tope: Decimal
    choferil_empleado_semanal: Decimal
    choferil_patrono_semanal: Decimal
    exencion_personal_individuo: Decimal
    exencion_personal_casado: Decimal
    exencion_dependiente: Decimal
    exencion_dependiente_custodia: Decimal
    exencion_veterano: Decimal
    tramos: tuple
    horas_extra: dict  # regimen -> ReglaHorasExtra
    salario_minimo: Decimal | None = None
    verificado: bool = False


@dataclass(frozen=True)
class TasasCompania:
    suta: Decimal
    aportacion_especial: Decimal
    sinot_empleado: Decimal
    sinot_patrono: Decimal
    cfse_por_100: Decimal | None = None
    verificadas: bool = False


@dataclass(frozen=True)
class Empleado:
    regimen: str  # "anterior" | "ley4"
    tipo_pago: str  # "hora" | "salario" | "exento"
    tarifa: Decimal
    horas_regulares_periodo: Decimal | None = None
    aplica_choferil: bool = False
    recibe_propinas: bool = False
    r4_estado_civil: str = "soltero"
    r4_exencion_personal: str = "completa"
    r4_dependientes: int = 0
    r4_dependientes_custodia_compartida: int = 0
    r4_veterano: bool = False
    r4_concesion_deducciones: Decimal = CERO
    r4_retencion_adicional: Decimal = CERO
    w4_aplica: bool = False


@dataclass(frozen=True)
class Horas:
    regulares: Decimal = CERO
    extra_diarias: Decimal = CERO
    extra_semanales: Decimal = CERO
    septimo_dia: Decimal = CERO
    periodo_alimentos: Decimal = CERO
    vacaciones: Decimal = CERO
    enfermedad: Decimal = CERO


@dataclass(frozen=True)
class Concepto:
    """Sujeción de un ingreso a cada contribución."""

    codigo: str
    nombre: str
    pr: bool = True
    ss: bool = True
    medicare: bool = True
    futa: bool = True
    desempleo: bool = True
    sinot: bool = True
    cfse: bool = True


@dataclass(frozen=True)
class TipoDeduccion:
    codigo: str
    nombre: str
    antes_de_pr: bool = False
    antes_de_federal: bool = False
    antes_de_fica: bool = False


@dataclass(frozen=True)
class Monto:
    concepto: object  # Concepto o TipoDeduccion
    monto: Decimal
    descripcion: str = ""


@dataclass(frozen=True)
class Acumulados:
    """Salarios tributables acumulados en el año ANTES de este período."""

    ss: Decimal = CERO
    medicare: Decimal = CERO
    futa: Decimal = CERO
    desempleo: Decimal = CERO
    sinot: Decimal = CERO


# --- Salidas ------------------------------------------------------------------------


@dataclass(frozen=True)
class Linea:
    codigo: str
    nombre: str
    monto: Decimal
    base: Decimal | None = None
    tasa: Decimal | None = None
    explicacion: str = ""


@dataclass
class Resultado:
    ingresos: list = field(default_factory=list)
    retenciones: list = field(default_factory=list)  # contribuciones al empleado
    deducciones: list = field(default_factory=list)  # deducciones voluntarias/legales
    patronales: list = field(default_factory=list)
    tributables: dict = field(default_factory=dict)
    alertas: list = field(default_factory=list)

    @property
    def bruto(self):
        return sum((l.monto for l in self.ingresos), CERO)

    @property
    def total_retenciones(self):
        return sum((l.monto for l in self.retenciones), CERO)

    @property
    def total_deducciones(self):
        return sum((l.monto for l in self.deducciones), CERO)

    @property
    def total_descuentos(self):
        return self.total_retenciones + self.total_deducciones

    @property
    def neto(self):
        return self.bruto - self.total_retenciones - self.total_deducciones

    @property
    def total_patronal(self):
        return sum((l.monto for l in self.patronales), CERO)

    @property
    def costo_total(self):
        return self.bruto + self.total_patronal

    def monto(self, codigo) -> Decimal:
        for grupo in (self.ingresos, self.retenciones, self.deducciones, self.patronales):
            for linea in grupo:
                if linea.codigo == codigo:
                    return linea.monto
        return CERO


class ErrorCalculo(ValueError):
    pass


# --- Cálculo ------------------------------------------------------------------------


def tarifa_por_hora(emp: Empleado) -> Decimal | None:
    if emp.tipo_pago == "hora":
        return Decimal(emp.tarifa)
    if emp.horas_regulares_periodo:
        return Decimal(emp.tarifa) / Decimal(emp.horas_regulares_periodo)
    return None


def impuesto_por_tabla(ingreso_anual: Decimal, tramos) -> tuple[Decimal, str]:
    if ingreso_anual <= 0:
        return CERO, "Ingreso anual sujeto $0.00: sin retención."
    for tramo in sorted(tramos, key=lambda t: t.desde, reverse=True):
        if ingreso_anual > tramo.desde or tramo.desde == 0:
            exceso = ingreso_anual - tramo.desde
            impuesto = tramo.cuota_fija + exceso * tramo.tasa / CIEN
            texto = (
                f"Tramo desde {dinero(tramo.desde)}: {dinero(tramo.cuota_fija)} + {pct(tramo.tasa)} × "
                f"{dinero(exceso)} = {dinero(impuesto)} anual."
            )
            return impuesto, texto
    raise ErrorCalculo("La tabla de retención no tiene tramos.")


def _base_con_tope(tributable: Decimal, acumulado: Decimal, tope: Decimal) -> Decimal:
    disponible = max(CERO, tope - acumulado)
    return max(CERO, min(tributable, disponible))


def calcular(
    *,
    empleado: Empleado,
    parametros: Parametros,
    tasas: TasasCompania,
    frecuencia: str,
    horas: Horas = Horas(),
    otros_ingresos=(),
    deducciones=(),
    acumulados: Acumulados = Acumulados(),
    semanas_choferil: int | None = None,
    conceptos: dict | None = None,
) -> Resultado:
    """
    `conceptos` = {codigo: Concepto} para los ingresos que genera el motor
    (regular, horas_extra, vacaciones, enfermedad). Si falta, todos tributan.
    """
    if frecuencia not in PERIODOS_POR_ANIO:
        raise ErrorCalculo(f"Frecuencia de pago desconocida: {frecuencia}")
    conceptos = conceptos or {}
    periodos = PERIODOS_POR_ANIO[frecuencia]
    r = Resultado()

    def concepto(codigo, nombre):
        return conceptos.get(codigo) or Concepto(codigo, nombre)

    ingresos: list[Monto] = []
    tarifa_hora = tarifa_por_hora(empleado)

    # 1. Salario regular
    if empleado.tipo_pago == "hora":
        monto = redondear(Decimal(horas.regulares) * Decimal(empleado.tarifa))
        explic = f"{horas.regulares} horas × {dinero(empleado.tarifa)} = {dinero(monto)}"
    else:
        monto = redondear(empleado.tarifa)
        explic = f"Salario del período {dinero(monto)}"
    if monto:
        ingresos.append(Monto(concepto("regular", "Salario regular"), monto, explic))

    # 2. Horas extra según el régimen (Ley 379 / Ley 4-2017)
    extras = [
        ("diario", horas.extra_diarias, "exceso de 8 horas diarias"),
        ("semanal", horas.extra_semanales, "exceso de 40 horas semanales"),
        ("septimo_dia", horas.septimo_dia, "séptimo día / día de descanso"),
        ("periodo_alimentos", horas.periodo_alimentos, "período de tomar alimentos"),
    ]
    if any(h for _, h, _ in extras):
        if empleado.tipo_pago == "exento":
            r.alertas.append("Empleado exento: no se pagan horas extra; se ignoraron las horas extra entradas.")
        elif tarifa_hora is None:
            raise ErrorCalculo(
                "El empleado asalariado no tiene 'horas regulares por período': no se puede calcular la tarifa "
                "por hora para las horas extra."
            )
        else:
            regla = parametros.horas_extra.get(empleado.regimen)
            if regla is None:
                raise ErrorCalculo(f"No hay multiplicadores de horas extra para el régimen '{empleado.regimen}'.")
            for campo, cantidad, nombre in extras:
                if not cantidad:
                    continue
                factor = getattr(regla, campo)
                monto = redondear(Decimal(cantidad) * tarifa_hora * factor)
                ingresos.append(
                    Monto(
                        concepto("horas_extra", "Horas extra"),
                        monto,
                        f"{cantidad} h ({nombre}) × {dinero(redondear(tarifa_hora))} × {factor} "
                        f"[{'antes de Ley 4-2017' if empleado.regimen == 'anterior' else 'Ley 4-2017'}] = {dinero(monto)}",
                    )
                )

    # 3. Licencias pagadas
    for codigo, cantidad, nombre in (
        ("vacaciones", horas.vacaciones, "Vacaciones pagadas"),
        ("enfermedad", horas.enfermedad, "Licencia por enfermedad pagada"),
    ):
        if cantidad:
            if tarifa_hora is None:
                raise ErrorCalculo("No se puede pagar licencia en horas sin tarifa por hora.")
            monto = redondear(Decimal(cantidad) * tarifa_hora)
            ingresos.append(Monto(concepto(codigo, nombre), monto, f"{cantidad} h × {dinero(redondear(tarifa_hora))} = {dinero(monto)}"))

    # 4. Otros ingresos (propinas, comisiones, bonos, reembolsos, misceláneos)
    ingresos.extend(m for m in otros_ingresos if m.monto)

    for m in ingresos:
        r.ingresos.append(Linea(m.concepto.codigo, m.concepto.nombre, redondear(m.monto), explicacion=m.descripcion))

    # 5. Salarios tributables por contribución
    def suma(atributo):
        return sum((redondear(m.monto) for m in ingresos if getattr(m.concepto, atributo)), CERO)

    pre_pr = sum((redondear(d.monto) for d in deducciones if d.concepto.antes_de_pr), CERO)
    pre_fica = sum((redondear(d.monto) for d in deducciones if d.concepto.antes_de_fica), CERO)
    trib = {
        "pr": max(CERO, suma("pr") - pre_pr),
        "ss": max(CERO, suma("ss") - pre_fica),
        "medicare": max(CERO, suma("medicare") - pre_fica),
        "futa": max(CERO, suma("futa") - pre_fica),
        "desempleo": max(CERO, suma("desempleo") - pre_fica),
        "sinot": max(CERO, suma("sinot") - pre_fica),
        "cfse": suma("cfse"),
    }
    r.tributables = trib

    # 6. Retención de PR (método anualizado)
    p = parametros
    exencion_personal = CERO
    base_personal = (
        p.exencion_personal_casado if empleado.r4_estado_civil in ("casado", "casado_separado")
        else p.exencion_personal_individuo
    )
    if empleado.r4_exencion_personal == "completa":
        exencion_personal = base_personal
    elif empleado.r4_exencion_personal == "mitad":
        exencion_personal = base_personal / 2
    exenciones = (
        exencion_personal
        + p.exencion_dependiente * empleado.r4_dependientes
        + p.exencion_dependiente_custodia * empleado.r4_dependientes_custodia_compartida
        + (p.exencion_veterano if empleado.r4_veterano else CERO)
        + Decimal(empleado.r4_concesion_deducciones)
    )
    anual = trib["pr"] * periodos
    sujeto_anual = max(CERO, anual - exenciones)
    impuesto_anual, texto_tabla = impuesto_por_tabla(sujeto_anual, p.tramos)
    retencion_pr = redondear(impuesto_anual / periodos) + redondear(empleado.r4_retencion_adicional)
    r.retenciones.append(
        Linea(
            "retencion_pr", "Retención de contribución sobre ingresos (PR)", retencion_pr, trib["pr"], None,
            f"{dinero(trib['pr'])} × {periodos} períodos = {dinero(anual)} anual; menos exenciones y concesión "
            f"{dinero(exenciones)} = {dinero(sujeto_anual)}. {texto_tabla} ÷ {periodos} = "
            f"{dinero(redondear(impuesto_anual / periodos))}"
            + (f" + retención adicional {dinero(empleado.r4_retencion_adicional)}" if empleado.r4_retencion_adicional else "")
            + ".",
        )
    )
    if empleado.w4_aplica:
        r.alertas.append(
            "El empleado tiene W-4 federal: la retención federal todavía no se calcula (falta la tabla del IRS)."
        )

    # 7. Seguro Social y Medicare
    base_ss = _base_con_tope(trib["ss"], acumulados.ss, p.ss_tope)
    nota_tope = (
        f" (tope anual {dinero(p.ss_tope)}; acumulado {dinero(acumulados.ss)})" if base_ss < trib["ss"] else ""
    )
    r.retenciones.append(Linea("ss_empleado", "Seguro Social", redondear(base_ss * p.ss_tasa_empleado / CIEN),
                               base_ss, p.ss_tasa_empleado, f"{dinero(base_ss)} × {pct(p.ss_tasa_empleado)}{nota_tope}"))
    r.patronales.append(Linea("ss_patrono", "Seguro Social patronal", redondear(base_ss * p.ss_tasa_patrono / CIEN),
                              base_ss, p.ss_tasa_patrono, f"{dinero(base_ss)} × {pct(p.ss_tasa_patrono)}{nota_tope}"))

    base_med = trib["medicare"]
    r.retenciones.append(Linea("medicare_empleado", "Medicare", redondear(base_med * p.medicare_tasa_empleado / CIEN),
                               base_med, p.medicare_tasa_empleado, f"{dinero(base_med)} × {pct(p.medicare_tasa_empleado)}"))
    r.patronales.append(Linea("medicare_patrono", "Medicare patronal", redondear(base_med * p.medicare_tasa_patrono / CIEN),
                              base_med, p.medicare_tasa_patrono, f"{dinero(base_med)} × {pct(p.medicare_tasa_patrono)}"))
    exceso = max(CERO, acumulados.medicare + base_med - max(acumulados.medicare, p.medicare_adicional_umbral))
    exceso = min(exceso, base_med)
    if exceso > 0:
        r.retenciones.append(Linea(
            "medicare_adicional", "Medicare adicional", redondear(exceso * p.medicare_adicional_tasa / CIEN),
            exceso, p.medicare_adicional_tasa,
            f"Salarios del año sobre {dinero(p.medicare_adicional_umbral)}: {dinero(exceso)} × {pct(p.medicare_adicional_tasa)}",
        ))

    # 8. SINOT (incapacidad)
    base_sinot = _base_con_tope(trib["sinot"], acumulados.sinot, p.sinot_tope)
    r.retenciones.append(Linea("sinot_empleado", "Incapacidad (SINOT)", redondear(base_sinot * tasas.sinot_empleado / CIEN),
                               base_sinot, tasas.sinot_empleado,
                               f"{dinero(base_sinot)} × {pct(tasas.sinot_empleado)} (tope {dinero(p.sinot_tope)})"))
    r.patronales.append(Linea("sinot_patrono", "Incapacidad (SINOT) patronal", redondear(base_sinot * tasas.sinot_patrono / CIEN),
                              base_sinot, tasas.sinot_patrono,
                              f"{dinero(base_sinot)} × {pct(tasas.sinot_patrono)} (tope {dinero(p.sinot_tope)})"))

    # 9. Seguro Choferil (cuota fija por semana)
    if empleado.aplica_choferil:
        semanas = semanas_choferil if semanas_choferil is not None else SEMANAS_CHOFERIL[frecuencia]
        r.retenciones.append(Linea("choferil_empleado", "Seguro Choferil", redondear(p.choferil_empleado_semanal * semanas),
                                   explicacion=f"{semanas} semana(s) × {dinero(p.choferil_empleado_semanal)}"))
        r.patronales.append(Linea("choferil_patrono", "Seguro Choferil patronal", redondear(p.choferil_patrono_semanal * semanas),
                                  explicacion=f"{semanas} semana(s) × {dinero(p.choferil_patrono_semanal)}"))

    # 10. Desempleo federal y estatal (solo patrono)
    base_futa = _base_con_tope(trib["futa"], acumulados.futa, p.futa_tope)
    r.patronales.append(Linea("futa", "FUTA", redondear(base_futa * p.futa_tasa / CIEN), base_futa, p.futa_tasa,
                              f"{dinero(base_futa)} × {pct(p.futa_tasa)} (tope {dinero(p.futa_tope)})"))
    base_des = _base_con_tope(trib["desempleo"], acumulados.desempleo, p.desempleo_tope)
    r.patronales.append(Linea("suta", "Desempleo estatal (SUTA)", redondear(base_des * tasas.suta / CIEN), base_des, tasas.suta,
                              f"{dinero(base_des)} × {pct(tasas.suta)} (tope {dinero(p.desempleo_tope)})"))
    r.patronales.append(Linea("aportacion_especial", "Aportación especial", redondear(base_des * tasas.aportacion_especial / CIEN),
                              base_des, tasas.aportacion_especial,
                              f"{dinero(base_des)} × {pct(tasas.aportacion_especial)} (tope {dinero(p.desempleo_tope)})"))

    # 11. CFSE (provisión según la clasificación del empleado)
    if tasas.cfse_por_100 is not None:
        r.patronales.append(Linea("cfse", "CFSE (provisión)", redondear(trib["cfse"] * tasas.cfse_por_100 / CIEN),
                                  trib["cfse"], tasas.cfse_por_100,
                                  f"{dinero(trib['cfse'])} × {tasas.cfse_por_100} por cada $100"))
    else:
        r.alertas.append("Sin tasa CFSE para la clasificación del empleado: no se calculó la provisión de CFSE.")

    # 12. Deducciones del empleado
    for d in deducciones:
        if d.monto:
            momento = []
            if d.concepto.antes_de_pr:
                momento.append("antes de PR")
            if d.concepto.antes_de_fica:
                momento.append("antes de SS/Medicare")
            r.deducciones.append(Linea(d.concepto.codigo, d.concepto.nombre, redondear(d.monto),
                                       explicacion=(", ".join(momento) or "después de contribuciones")
                                       + (f" — {d.descripcion}" if d.descripcion else "")))

    # 13. Alertas
    if p.salario_minimo is not None and tarifa_hora is not None and tarifa_hora < p.salario_minimo:
        r.alertas.append(
            f"La tarifa por hora {dinero(redondear(tarifa_hora))} está por debajo del salario mínimo "
            f"{dinero(p.salario_minimo)}" + (" (el empleado recibe propinas: verifique si aplica)." if empleado.recibe_propinas else ".")
        )
    if r.neto < 0:
        r.alertas.append(f"El neto a pagar es negativo ({dinero(r.neto)}): revise las deducciones.")
    if not p.verificado:
        r.alertas.append(f"Los parámetros de {p.anio} están POR VERIFICAR.")
    if not tasas.verificadas:
        r.alertas.append("Las tasas de la compañía están POR VERIFICAR.")
    return r
