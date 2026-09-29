"""
Reglas iniciales de vacaciones, enfermedad y bono de Navidad (POR VERIFICAR).

Rige la Ley 4-2017: la Ley 41-2022 fue declarada nula por el Tribunal Federal
(3 de marzo de 2023).

Licencias (Ley 180-1998, enmendada por Ley 4-2017):
- Antes de Ley 4: 1.25 días de vacaciones y 1 de enfermedad por mes con 115 h;
  patrono de 12 empleados o menos: ½ día de vacaciones.
- Ley 4 (patrono de más de 12): vacaciones ½ día (1er año), ¾ (1 a 5 años),
  1 (5 a 15), 1.25 (más de 15); patrono de 12 o menos: ½ día. Enfermedad 1
  día. Mínimo 130 h en el mes.

Bono de Navidad (Ley 148-1969), período del 1 de octubre al 30 de septiembre:
- Antes de Ley 4: 700 h; más de 15 empleados 6% hasta $10,000 de salario
  (máx. $600); 15 o menos 3% (máx. $300).
- Ley 4: 1,350 h; más de 20 empleados 2% hasta $600; 20 o menos 2% hasta $300.
"""

from decimal import Decimal as D

from django.db import migrations

LICENCIAS = [
    # tipo, regimen, tamano, desde, hasta, horas, dias
    ("vacaciones", "anterior", "grande", "0", None, "115", "1.25"),
    ("vacaciones", "anterior", "pequeno", "0", None, "115", "0.5"),
    ("enfermedad", "anterior", "grande", "0", None, "115", "1"),
    ("enfermedad", "anterior", "pequeno", "0", None, "115", "1"),
    ("vacaciones", "ley4", "grande", "0", "1", "130", "0.5"),
    ("vacaciones", "ley4", "grande", "1", "5", "130", "0.75"),
    ("vacaciones", "ley4", "grande", "5", "15", "130", "1"),
    ("vacaciones", "ley4", "grande", "15", None, "130", "1.25"),
    ("vacaciones", "ley4", "pequeno", "0", None, "130", "0.5"),
    ("enfermedad", "ley4", "grande", "0", None, "130", "1"),
    ("enfermedad", "ley4", "pequeno", "0", None, "130", "1"),
]
BONO = [
    dict(regimen="anterior", horas_minimas=D("700"), umbral_empleados=15, porcentaje_grande=D("6"),
         tope_grande=D("600"), porcentaje_pequeno=D("3"), tope_pequeno=D("300"), tope_salario=D("10000")),
    dict(regimen="ley4", horas_minimas=D("1350"), umbral_empleados=20, porcentaje_grande=D("2"),
         tope_grande=D("600"), porcentaje_pequeno=D("2"), tope_pequeno=D("300"), tope_salario=None),
]


def cargar(apps, schema_editor):
    Parametros = apps.get_model("parametros", "ParametrosAnuales")
    Licencia = apps.get_model("parametros", "ReglaLicencia")
    Bono = apps.get_model("parametros", "ReglaBonoNavidad")
    for p in Parametros.objects.all():
        if not Licencia.objects.filter(parametros=p).exists():
            for tipo, regimen, tamano, desde, hasta, horas, dias in LICENCIAS:
                Licencia.objects.create(
                    parametros=p, tipo=tipo, regimen=regimen, tamano=tamano, anios_desde=D(desde),
                    anios_hasta=D(hasta) if hasta else None, horas_minimas_mes=D(horas), dias_por_mes=D(dias),
                )
        if not Bono.objects.filter(parametros=p).exists():
            for regla in BONO:
                Bono.objects.create(parametros=p, mes_inicio_periodo=10, **regla)
        p.estado = "por_verificar"
        p.save()


class Migration(migrations.Migration):
    dependencies = [("parametros", "0005_reglas_licencias_bono")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
