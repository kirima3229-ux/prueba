# Sistema de Nómina — imagen de producción.
# Debian 13 (trixie): trae el cliente de PostgreSQL 17, que respalda servidores 16 y 17.
FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 nomina \
    && useradd --system --uid 10001 --gid nomina --home-dir /app --shell /usr/sbin/nologin nomina

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY --chown=nomina:nomina . .

# Archivos estáticos con nombres versionados. Las llaves de aquí son de relleno SÓLO para este paso;
# no quedan en la imagen (las reales llegan por variables de entorno al arrancar).
RUN NOMINA_ENTORNO=produccion \
    DJANGO_SECRET_KEY=solo-para-collectstatic \
    NOMINA_LLAVES_CIFRADO=1:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= \
    NOMINA_LLAVE_ACTIVA=1 \
    NOMINA_LLAVE_INDICE=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= \
    python manage.py collectstatic --noinput \
    && mkdir -p /app/respaldos \
    && chown nomina:nomina /app/respaldos \
    && chmod 700 /app/respaldos \
    && chmod +x docker/entrypoint.sh

USER nomina
EXPOSE 8000
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--config", "docker/gunicorn.conf.py"]
