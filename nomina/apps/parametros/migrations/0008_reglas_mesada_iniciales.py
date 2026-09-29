"""
Reglas iniciales de mesada (Ley 80-1976), POR VERIFICAR.

- Antes de Ley 4-2017 (Ley 128-2005): hasta 5 años, 2 meses + 1 semana por año;
  de 5 a 15 años, 3 meses + 2 semanas por año; más de 15 años, 6 meses + 3
  semanas por año. Sin tope.
- Ley 4-2017: 3 meses + 2 semanas por año, hasta un máximo de 9 meses.
"""

from decimal import Decimal as D

from django.db import migrations

REGLAS = [
    ("anterior", "0", "5", "2", "1", None),
    ("anterior", "5", "15", "3", "2", None),
    ("anterior", "15", None, "6", "3", None),
    ("ley4", "0", None, "3", "2", "9"),
]


def cargar(apps, schema_editor):
    Parametros = apps.get_model("parametros", "ParametrosAnuales")
    Regla = apps.get_model("parametros", "ReglaMesada")
    for p in Parametros.objects.all():
        if Regla.objects.filter(parametros=p).exists():
            continue
        for regimen, desde, hasta, meses, semanas, tope in REGLAS:
            Regla.objects.create(
                parametros=p, regimen=regimen, anios_desde=D(desde), anios_hasta=D(hasta) if hasta else None,
                meses_sueldo=D(meses), semanas_por_anio=D(semanas), tope_meses=D(tope) if tope else None,
            )
        p.estado = "por_verificar"
        p.save()


class Migration(migrations.Migration):
    dependencies = [("parametros", "0007_regla_mesada")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
