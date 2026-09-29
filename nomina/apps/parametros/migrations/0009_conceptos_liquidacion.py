from django.db import migrations

# codigo, nombre, pr, ss, medicare, futa, desempleo, sinot, cfse — tratamiento POR VERIFICAR
CONCEPTOS = [
    ("mesada", "Mesada (indemnización por despido)", 0, 1, 1, 1, 1, 1, 0),
    ("vacaciones_liquidadas", "Vacaciones liquidadas", 1, 1, 1, 1, 1, 1, 1),
    ("enfermedad_liquidada", "Enfermedad liquidada", 1, 1, 1, 1, 1, 1, 1),
]


def cargar(apps, schema_editor):
    Ingreso = apps.get_model("parametros", "ConceptoIngreso")
    for codigo, nombre, pr, ss, med, futa, des, sinot, cfse in CONCEPTOS:
        Ingreso.objects.get_or_create(codigo=codigo, defaults=dict(
            nombre=nombre, tributable_pr=pr, tributable_ss=ss, tributable_medicare=med, tributable_futa=futa,
            tributable_desempleo=des, tributable_sinot=sinot, tributable_cfse=cfse, del_sistema=True,
        ))


class Migration(migrations.Migration):
    dependencies = [("parametros", "0008_reglas_mesada_iniciales")]
    operations = [migrations.RunPython(cargar, migrations.RunPython.noop)]
