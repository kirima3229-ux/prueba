"""
Valores iniciales. TODO queda POR VERIFICAR: un administrador debe confirmarlos
en pantalla antes de procesar nóminas reales.

Confirmados en fuentes públicas al crear esta migración:
- Tope del Seguro Social: $176,100 (2025) y $184,500 (2026), SSA.
- Salario mínimo de PR: $9.50 (7/1/2023) y $10.50 (7/1/2024), Ley 47-2021.
Valores iniciales NO confirmados (verificar contra Hacienda/DTRH/IRS):
- Tabla de retención de PR por tramos, exenciones, Seguro Choferil,
  multiplicadores de horas extra y tributabilidad de los conceptos.
"""

from datetime import date
from decimal import Decimal as D

from django.db import migrations

NOTA_TABLA = (
    "Tramos iniciales según la tabla de contribución de individuos vigente (Ley 52-2022), "
    "sin confirmar contra las Tablas de Retención de Hacienda. VERIFICAR."
)

BASE = dict(
    ss_tasa_empleado=D("6.2"), ss_tasa_patrono=D("6.2"),
    medicare_tasa_empleado=D("1.45"), medicare_tasa_patrono=D("1.45"),
    medicare_adicional_tasa=D("0.9"), medicare_adicional_umbral=D("200000"),
    futa_tasa=D("0.6"), futa_tope=D("7000"),
    desempleo_tope=D("7000"), sinot_tope=D("9000"),
    choferil_empleado_semanal=D("0.50"), choferil_patrono_semanal=D("0.30"),
    exencion_personal_individuo=D("0"), exencion_personal_casado=D("0"),
    exencion_dependiente=D("2500"), exencion_dependiente_custodia=D("1250"), exencion_veterano=D("1500"),
)
TOPES_SS = {2025: D("176100"), 2026: D("184500")}
TRAMOS = [
    (D("0"), D("9000"), D("0"), D("0")),
    (D("9000"), D("25000"), D("0"), D("7")),
    (D("25000"), D("41500"), D("1120"), D("14")),
    (D("41500"), D("61500"), D("3430"), D("25")),
    (D("61500"), None, D("8430"), D("33")),
]
HORAS_EXTRA = {
    # Antes de Ley 4-2017: tipo doble. Si el patrono está cubierto por la FLSA puede
    # corresponder tiempo y medio en algunos casos: VERIFICAR.
    "anterior": dict(diario=D("2"), semanal=D("2"), septimo_dia=D("2"), periodo_alimentos=D("2")),
    "ley4": dict(diario=D("1.5"), semanal=D("1.5"), septimo_dia=D("1.5"), periodo_alimentos=D("1.5")),
}
INGRESOS = [
    # codigo, nombre, pr, ss, medicare, futa, desempleo, sinot, cfse
    ("regular", "Salario regular", 1, 1, 1, 1, 1, 1, 1),
    ("horas_extra", "Horas extra", 1, 1, 1, 1, 1, 1, 1),
    ("vacaciones", "Vacaciones pagadas", 1, 1, 1, 1, 1, 1, 1),
    ("enfermedad", "Licencia por enfermedad pagada", 1, 1, 1, 1, 1, 1, 1),
    ("propinas", "Propinas", 1, 1, 1, 1, 1, 1, 0),
    ("comisiones", "Comisiones", 1, 1, 1, 1, 1, 1, 1),
    ("bono", "Bono", 1, 1, 1, 1, 1, 1, 1),
    ("bono_navidad", "Bono de Navidad", 1, 1, 1, 1, 0, 0, 0),
    ("reembolso", "Reembolso no tributable", 0, 0, 0, 0, 0, 0, 0),
    ("miscelaneo", "Pago misceláneo", 1, 1, 1, 1, 1, 1, 1),
]
DEDUCCIONES = [
    # codigo, nombre, antes_pr, antes_federal, antes_fica
    ("plan_medico", "Plan médico (Sección 125)", 1, 1, 1),
    ("retiro_1165e", "Retiro 1165(e) (PR)", 1, 0, 0),
    ("retiro_401k", "Retiro 401(k)", 0, 1, 0),
    ("prestamo", "Préstamo", 0, 0, 0),
    ("embargo", "Embargo / pensión alimentaria (ASUME)", 0, 0, 0),
    ("otra", "Otra deducción", 0, 0, 0),
]


def cargar(apps, schema_editor):
    Parametros = apps.get_model("parametros", "ParametrosAnuales")
    Tramo = apps.get_model("parametros", "TramoRetencionPR")
    Regla = apps.get_model("parametros", "ReglaHorasExtra")
    Minimo = apps.get_model("parametros", "SalarioMinimo")
    Ingreso = apps.get_model("parametros", "ConceptoIngreso")
    Deduccion = apps.get_model("parametros", "ConceptoDeduccion")

    for anio, tope in TOPES_SS.items():
        p = Parametros.objects.create(anio=anio, ss_tope=tope, notas=NOTA_TABLA, **BASE)
        for desde, hasta, cuota, tasa in TRAMOS:
            Tramo.objects.create(parametros=p, desde=desde, hasta=hasta, cuota_fija=cuota, tasa=tasa)
        for regimen, valores in HORAS_EXTRA.items():
            Regla.objects.create(parametros=p, regimen=regimen, **valores)

    Minimo.objects.create(vigente_desde=date(2023, 7, 1), tarifa_hora=D("9.50"), notas="Ley 47-2021")
    Minimo.objects.create(vigente_desde=date(2024, 7, 1), tarifa_hora=D("10.50"), notas="Ley 47-2021")

    for codigo, nombre, pr, ss, med, futa, des, sinot, cfse in INGRESOS:
        Ingreso.objects.create(
            codigo=codigo, nombre=nombre, tributable_pr=pr, tributable_ss=ss, tributable_medicare=med,
            tributable_futa=futa, tributable_desempleo=des, tributable_sinot=sinot, tributable_cfse=cfse,
            del_sistema=True,
        )
    for codigo, nombre, pr, fed, fica in DEDUCCIONES:
        Deduccion.objects.create(
            codigo=codigo, nombre=nombre, antes_de_pr=pr, antes_de_federal=fed, antes_de_fica=fica
        )


class Migration(migrations.Migration):
    dependencies = [("parametros", "0001_initial")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
