"""Configuración de gunicorn para el contenedor."""

import os

bind = "0.0.0.0:8000"
workers = int(os.environ.get("NOMINA_WORKERS", "3"))
threads = 2
timeout = 120  # PDF y Excel grandes
graceful_timeout = 30
max_requests = 1000  # recicla procesos periódicamente
max_requests_jitter = 100
accesslog = "-"
errorlog = "-"
# Sólo el proxy (Caddy) de la red interna manda X-Forwarded-*.
forwarded_allow_ips = "*"
# No registra el query string completo (puede traer filtros con nombres).
access_log_format = '%(h)s "%(m)s %(U)s" %(s)s %(b)s %(M)sms'
