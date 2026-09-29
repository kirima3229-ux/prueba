#!/bin/sh
# Espera a la base de datos y, en el servicio web, aplica las migraciones antes de arrancar.
set -eu

python - <<'PY'
import os, sys, time
import psycopg
for intento in range(60):
    try:
        psycopg.connect(
            host=os.environ.get("POSTGRES_HOST", "db"), port=os.environ.get("POSTGRES_PORT", "5432"),
            dbname=os.environ.get("POSTGRES_DB", "nomina"), user=os.environ.get("POSTGRES_USER", "nomina"),
            password=os.environ.get("POSTGRES_PASSWORD", ""), connect_timeout=3,
        ).close()
        break
    except psycopg.OperationalError:
        time.sleep(2)
else:
    sys.exit("La base de datos no responde.")
PY

if [ "${NOMINA_MIGRAR_AL_INICIAR:-0}" = "1" ]; then
    python manage.py migrate --noinput
    python manage.py verificar_auditoria
fi

exec "$@"
