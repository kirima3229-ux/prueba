"""
Tablas anuales del método de porcentaje de la Publicación 15-T (W-4 de 2020 o posterior), POR VERIFICAR.

El IRS construye cada tabla con los tramos de contribución del año desplazados por:
  - tabla estándar: deducción estándar − ajuste de la línea 1g ($12,900 casados, $8,600 los demás);
  - tabla «paso 2 marcado»: la mitad de la deducción estándar, con los tramos a la mitad.
Comprobado con la tabla 2026 publicada para casados: 0–19,300 → 0; 19,300–44,100 → 10%;
44,100 → $2,480 + 12%.

2025: tramos y deducciones estándar de la Rev. Proc. 2024-40 (las tablas de 2025 no cambiaron con la ley de
julio de 2025). 2026: Rev. Proc. 2025-32.
"""

from decimal import Decimal as D

from django.db import migrations

TASAS = (10, 12, 22, 24, 32, 35, 37)
DATOS = {
    2025: {
        "married": (D("30000"), (23850, 96950, 206700, 394600, 501050, 751600)),
        "single": (D("15000"), (11925, 48475, 103350, 197300, 250525, 626350)),
        "head": (D("22500"), (17000, 64850, 103350, 197300, 250500, 626350)),
    },
    2026: {
        "married": (D("32200"), (24800, 100800, 211400, 403550, 512450, 768700)),
        "single": (D("16100"), (12400, 50400, 105700, 201775, 256225, 640600)),
        "head": (D("24150"), (17700, 67450, 105700, 201775, 256200, 640600)),
    },
}
AJUSTE = {"married": D("12900"), "single": D("8600"), "head": D("8600")}


def tabla(limites, desplazamiento):
    filas = [(D("0"), D("0"), D("0"))]
    acumulado, anterior = D("0"), D("0")
    for i, tasa in enumerate(TASAS):
        filas.append((desplazamiento + anterior, acumulado, D(tasa)))
        if i < len(limites):
            limite = D(limites[i])
            acumulado += (limite - anterior) * D(tasa) / 100
            anterior = limite
    return filas


def cargar(apps, schema_editor):
    Parametros = apps.get_model("parametros", "ParametrosAnuales")
    Tramo = apps.get_model("parametros", "TramoRetencionFederal")
    for anio, por_estado in DATOS.items():
        p = Parametros.objects.filter(anio=anio).first()
        if p is None or Tramo.objects.filter(parametros=p).exists():
            continue
        for estado, (deduccion, limites) in por_estado.items():
            for nombre, desplazamiento, lims in (
                ("estandar", deduccion - AJUSTE[estado], limites),
                ("paso2", deduccion / 2, [D(l) / 2 for l in limites]),
            ):
                for desde, cuota, tasa in tabla(lims, desplazamiento):
                    Tramo.objects.create(parametros=p, estado_civil=estado, tabla=nombre, desde=desde,
                                         cuota_fija=cuota.quantize(D("0.01")), tasa=tasa)


def reembolso_no_tributa(apps, schema_editor):
    ConceptoIngreso = apps.get_model("parametros", "ConceptoIngreso")
    ConceptoIngreso.objects.filter(codigo="reembolso").update(tributable_federal=False)


class Migration(migrations.Migration):
    dependencies = [("parametros", "0010_retencion_federal")]
    operations = [
        migrations.RunPython(cargar, migrations.RunPython.noop),
        migrations.RunPython(reembolso_no_tributa, migrations.RunPython.noop),
    ]
