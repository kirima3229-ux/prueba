"""Triggers que impiden modificar o borrar registros de la bitácora a nivel de base de datos."""

from django.db import migrations

TABLA = "auditoria_registroauditoria"

POSTGRES_CREAR = f"""
CREATE OR REPLACE FUNCTION auditoria_inmutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'La bitacora de auditoria es inmutable (operacion % rechazada)', TG_OP;
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER auditoria_sin_cambios BEFORE UPDATE OR DELETE ON {TABLA}
    FOR EACH ROW EXECUTE FUNCTION auditoria_inmutable();
CREATE TRIGGER auditoria_sin_truncate BEFORE TRUNCATE ON {TABLA}
    FOR EACH STATEMENT EXECUTE FUNCTION auditoria_inmutable();
"""
POSTGRES_BORRAR = f"""
DROP TRIGGER IF EXISTS auditoria_sin_cambios ON {TABLA};
DROP TRIGGER IF EXISTS auditoria_sin_truncate ON {TABLA};
DROP FUNCTION IF EXISTS auditoria_inmutable();
"""
SQLITE_CREAR = [
    f"""CREATE TRIGGER auditoria_sin_update BEFORE UPDATE ON {TABLA}
        BEGIN SELECT RAISE(ABORT, 'La bitacora de auditoria es inmutable'); END;""",
    f"""CREATE TRIGGER auditoria_sin_delete BEFORE DELETE ON {TABLA}
        BEGIN SELECT RAISE(ABORT, 'La bitacora de auditoria es inmutable'); END;""",
]
SQLITE_BORRAR = [
    "DROP TRIGGER IF EXISTS auditoria_sin_update;",
    "DROP TRIGGER IF EXISTS auditoria_sin_delete;",
]


def crear(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        schema_editor.execute(POSTGRES_CREAR, params=None)
    elif vendor == "sqlite":
        for sql in SQLITE_CREAR:
            schema_editor.execute(sql)


def borrar(apps, schema_editor):
    vendor = schema_editor.connection.vendor
    if vendor == "postgresql":
        schema_editor.execute(POSTGRES_BORRAR, params=None)
    elif vendor == "sqlite":
        for sql in SQLITE_BORRAR:
            schema_editor.execute(sql)


class Migration(migrations.Migration):
    dependencies = [("auditoria", "0002_initial")]
    operations = [migrations.RunPython(crear, borrar)]
