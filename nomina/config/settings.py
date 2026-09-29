"""
Configuración del Sistema de Nómina — Quality Group.

Todos los secretos y parámetros de despliegue vienen de variables de entorno
(archivo .env en desarrollo). Nunca poner secretos en este archivo.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env(nombre, defecto=None, requerido=False):
    valor = os.environ.get(nombre, defecto)
    if requerido and not valor:
        raise ImproperlyConfigured(f"Falta la variable de entorno {nombre}.")
    return valor


def env_bool(nombre, defecto=False):
    valor = os.environ.get(nombre)
    if valor is None:
        return defecto
    return valor.strip().lower() in ("1", "true", "si", "sí", "yes", "on")


def env_lista(nombre, defecto=""):
    return [v.strip() for v in env(nombre, defecto).split(",") if v.strip()]


# desarrollo | produccion
ENTORNO = env("NOMINA_ENTORNO", "desarrollo")
PRODUCCION = ENTORNO == "produccion"

SECRET_KEY = env("DJANGO_SECRET_KEY", requerido=True)
DEBUG = env_bool("DJANGO_DEBUG", False) and not PRODUCCION
ALLOWED_HOSTS = env_lista("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_lista("DJANGO_CSRF_TRUSTED_ORIGINS", "")

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "axes",
    "apps.core",
    "apps.auditoria",
    "apps.companias",
    "apps.cuentas",
    "apps.empleados",
    "apps.servicios",
    "apps.parametros",
    "apps.calculo",
    "apps.licencias",
    "apps.nomina",
    "apps.planillas",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    # Ninguna página es accesible sin sesión, salvo las marcadas con
    # @login_not_required (pantalla de entrada y verificación 2FA).
    "django.contrib.auth.middleware.LoginRequiredMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.cuentas.middleware.RequisitosCuentaMiddleware",
    "apps.companias.middleware.CompaniaActivaMiddleware",
    "apps.core.middleware.CabecerasSeguridadMiddleware",
    # Axes debe ir al final para interceptar los bloqueos.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.companias.context_processors.compania_activa",
                "apps.core.context_processors.sistema",
            ],
        },
    },
]

# --- Base de datos -----------------------------------------------------------
# PostgreSQL en producción. SQLite solo para desarrollo rápido.
DB_MOTOR = env("NOMINA_DB_MOTOR", "postgres")
if DB_MOTOR == "sqlite":
    if PRODUCCION:
        raise ImproperlyConfigured("SQLite no está permitido en producción.")
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("POSTGRES_DB", "nomina"),
            "USER": env("POSTGRES_USER", "nomina"),
            "PASSWORD": env("POSTGRES_PASSWORD", ""),
            "HOST": env("POSTGRES_HOST", "localhost"),
            "PORT": env("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": 60,
        }
    }

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Autenticación y contraseñas --------------------------------------------
AUTH_USER_MODEL = "cuentas.Usuario"
LOGIN_URL = "cuentas:entrar"
LOGIN_REDIRECT_URL = "inicio"

AUTHENTICATION_BACKENDS = [
    # Axes primero: rechaza intentos de cuentas bloqueadas.
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Bloqueo tras 5 intentos fallidos (contraseña o código 2FA) por usuario.
AXES_FAILURE_LIMIT = int(env("NOMINA_INTENTOS_MAXIMOS", "5"))
# Solo por usuario: bloquear por IP bloquearía a toda la oficina (misma IP pública).
AXES_LOCKOUT_PARAMETERS = ["username"]
SILENCED_SYSTEM_CHECKS = ["axes.W006"]
AXES_RESET_ON_SUCCESS = True
AXES_ENABLE_ADMIN = False
AXES_LOCKOUT_TEMPLATE = "cuentas/bloqueado.html"
AXES_CLIENT_IP_CALLABLE = "apps.core.red.obtener_ip"
# Minutos de bloqueo. Vacío = el bloqueo dura hasta que un administrador
# desbloquee la cuenta.
_cooloff = env("NOMINA_MINUTOS_BLOQUEO", "")
if _cooloff:
    from datetime import timedelta

    AXES_COOLOFF_TIME = timedelta(minutes=int(_cooloff))
else:
    AXES_COOLOFF_TIME = None

OTP_TOTP_ISSUER = env("NOMINA_NOMBRE_EMISOR_2FA", "Quality Group Nomina")

# --- Sesión: expira tras 15 minutos de inactividad --------------------------
SESSION_COOKIE_AGE = int(env("NOMINA_MINUTOS_SESION", "15")) * 60
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True

# --- Cifrado de campos (AES-256-GCM) ----------------------------------------
# NOMINA_LLAVES_CIFRADO="1:<base64 32 bytes>,2:<base64 32 bytes>"
# NOMINA_LLAVE_ACTIVA="2"  (las anteriores se conservan para descifrar)
# NOMINA_LLAVE_INDICE="<base64 32 bytes>"  (HMAC para buscar SSN sin descifrar)
# Genere llaves con: python manage.py generar_llave
NOMINA_LLAVES_CIFRADO = env("NOMINA_LLAVES_CIFRADO", requerido=True)
NOMINA_LLAVE_ACTIVA = env("NOMINA_LLAVE_ACTIVA", requerido=True)
NOMINA_LLAVE_INDICE = env("NOMINA_LLAVE_INDICE", requerido=True)

# --- Respaldos cifrados -------------------------------------------------------
# Llave distinta de las de los campos. Varias separadas por coma: la primera cifra, todas sirven para restaurar.
NOMINA_LLAVE_RESPALDO = env("NOMINA_LLAVE_RESPALDO", "")
NOMINA_DIR_RESPALDOS = env("NOMINA_DIR_RESPALDOS", "")

# Número de proxies de confianza delante de la aplicación (Caddy/nginx).
# 0 = conexión directa; se usa REMOTE_ADDR.
NOMINA_PROXIES_CONFIABLES = int(env("NOMINA_PROXIES_CONFIABLES", "0"))

# --- Cabeceras de seguridad --------------------------------------------------
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
NOMINA_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'self'; object-src 'none'"
)

if PRODUCCION:
    SECURE_SSL_REDIRECT = env_bool("NOMINA_FORZAR_HTTPS", True)
    # El chequeo de salud de Docker llega por HTTP dentro de la red interna.
    SECURE_REDIRECT_EXEMPT = [r"^salud/$"]
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    # Inscribir el dominio en la lista «preload» de los navegadores es una decisión del dueño del dominio.
    SECURE_HSTS_PRELOAD = env_bool("NOMINA_HSTS_PRELOAD", False)
    if not SECURE_HSTS_PRELOAD:
        SILENCED_SYSTEM_CHECKS.append("security.W021")
    SESSION_COOKIE_NAME = "__Host-sessionid"
    CSRF_COOKIE_NAME = "__Host-csrftoken"

# --- Idioma, zona horaria y formatos ----------------------------------------
LANGUAGE_CODE = "es"
TIME_ZONE = "America/Puerto_Rico"
USE_I18N = True
USE_TZ = True
# Puerto Rico usa el formato numérico de EE. UU. (1,234.56) y fechas MM/DD/AAAA.
FORMAT_MODULE_PATH = ["config.formatos"]

# --- Archivos estáticos ------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if PRODUCCION
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        )
    },
}

# Límite de archivos subidos (importación de empleados).
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"consola": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["consola"], "level": env("NOMINA_NIVEL_LOG", "INFO")},
}
