"""
Mínimo en efectivo para empleados con propinas: $2.13 por hora (crédito máximo
= salario mínimo − $2.13), según la Opinión del Secretario del DTRH 2024-01 sobre
la Ley 47-2021. Queda POR VERIFICAR.
"""

from datetime import date
from decimal import Decimal

from django.db import migrations


def cargar(apps, schema_editor):
    Minimo = apps.get_model("parametros", "SalarioMinimo")
    for minimo in Minimo.objects.filter(vigente_desde__gte=date(2023, 7, 1), tarifa_propinas__isnull=True):
        minimo.tarifa_propinas = Decimal("2.13")
        minimo.notas = (minimo.notas + " " if minimo.notas else "") + (
            "Propinas: $2.13 en efectivo (Opinión del Secretario DTRH 2024-01)."
        )
        minimo.estado = "por_verificar"
        minimo.save()


class Migration(migrations.Migration):
    dependencies = [("parametros", "0003_salario_minimo_propinas")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
