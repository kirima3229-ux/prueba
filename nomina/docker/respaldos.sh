#!/bin/sh
# Respaldo cifrado diario a la hora indicada (NOMINA_HORA_RESPALDO, 0-23, hora de Puerto Rico).
set -u
HORA="${NOMINA_HORA_RESPALDO:-2}"
while true; do
    ahora=$(TZ=America/Puerto_Rico date +%s)
    hoy=$(TZ=America/Puerto_Rico date +%Y-%m-%d)
    objetivo=$(TZ=America/Puerto_Rico date -d "$hoy $HORA:00" +%s)
    if [ "$objetivo" -le "$ahora" ]; then
        objetivo=$((objetivo + 86400))
    fi
    sleep $((objetivo - ahora))
    python manage.py respaldar || echo "ERROR: el respaldo falló" >&2
done
