"""
Valores iniciales de la retención por servicios prestados (Sección 1062.03):
10% sobre el exceso de los primeros $500 pagados en el año a cada proveedor.
Se cargan POR VERIFICAR: un administrador debe confirmarlos en pantalla.
"""

from decimal import Decimal

from django.db import migrations


def cargar(apps, schema_editor):
    Config = apps.get_model("servicios", "ConfigRetencionServicios")
    for anio in (2025, 2026):
        Config.objects.get_or_create(
            anio=anio,
            defaults={
                "tasa_general": Decimal("10.00"),
                "exencion_anual": Decimal("500.00"),
                "estado": "por_verificar",
                "notas": "Valor inicial: 10% sobre el exceso de $500 por proveedor (Sección 1062.03). Confirmar.",
            },
        )


class Migration(migrations.Migration):
    dependencies = [("servicios", "0002_alter_proveedorservicios_relevo_and_more")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
