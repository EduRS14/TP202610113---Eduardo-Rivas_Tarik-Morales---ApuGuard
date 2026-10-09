"""
settings.py - APU GUARD Backend
Django + PostGIS + Celery
"""

import os
import environ
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Carga automatica del archivo .env en la raiz del proyecto
env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY")

DEBUG = env.bool("DEBUG", default=False)

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# -- Aplicaciones --
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.gis",          # PostGIS
]

LOCAL_APPS = [
    "core.apps.CoreConfig",
    "ml_engine",
]

THIRD_PARTY_APPS = [
    "corsheaders",
    "rest_framework",
    "rest_framework_gis",
    "rest_framework_simplejwt",
    # Habilita RefreshToken.blacklist() -> POST /api/auth/logout/
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Justo despues de SecurityMiddleware (recomendacion de WhiteNoise).
    # En produccion sirve los estaticos desde STATIC_ROOT; en desarrollo
    # django.contrib.staticfiles (runserver) sigue siendo quien responde.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS", default=["http://localhost:4200"]
)
# Origenes desde los que se aceptan peticiones con cookie de sesion/CSRF.
# En produccion (HTTPS) debe incluir la URL publica: https://<host>.
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS", default=["http://localhost:4200"]
)

ROOT_URLCONF = "apuguard.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "apuguard.wsgi.application"

# -- Base de datos PostGIS --
# DB_PASSWORD no tiene valor por defecto: si falta, Django lanza
# ImproperlyConfigured en el arranque en lugar de conectarse con credenciales
# por defecto. Se exige siempre via .env o variable de entorno.
DATABASES = {
    "default": {
        "ENGINE": "django.contrib.gis.db.backends.postgis",
        "NAME":     env("DB_NAME",     default="apuguard_db"),
        "USER":     env("DB_USER",     default="apuguard"),
        "PASSWORD": env("DB_PASSWORD"),
        "HOST":     env("DB_HOST",     default="localhost"),
        "PORT":     env("DB_PORT",     default="5432"),
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# -- Internacionalizacion --
LANGUAGE_CODE = "es-pe"
TIME_ZONE     = "America/Lima"
USE_I18N      = True
USE_TZ        = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# No hay FileField/ImageField en el modelo: la evidencia vive en S3
# (CasoAuditoria.evidencia_s3_key). El directorio local queda reservado
# por si Django necesita escribir algun archivo en disco.
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# -- Almacenamiento de estaticos (Fase B) --
# En produccion (DEBUG=False) WhiteNoise sirve los estaticos de Admin/DRF
# comprimidos y con fingerprint a partir de STATIC_ROOT, sin nginx ni
# colecta externa. Requiere `manage.py collectstatic` antes de arrancar.
# En desarrollo (DEBUG=True) se conserva el almacenamiento simple.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if not DEBUG
            else "django.contrib.staticfiles.storage.StaticFilesStorage"
        ),
    },
}
# Solo desarrollo: WhiteNoise sirve desde los finders si no se ejecuto
# collectstatic (util al usar gunicorn en local).
WHITENOISE_USE_FINDERS = DEBUG
WHITENOISE_MAX_AGE = 31536000

# -- Django REST Framework --
from datetime import timedelta

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME":  timedelta(hours=8),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "UPDATE_LAST_LOGIN": True,   # actualiza auth_user.last_login en cada login JWT
}

# URL presignada S3: expiracion en segundos
S3_PRESIGNED_URL_EXPIRATION = 900   # 15 minutos

# -- Celery --
CELERY_BROKER_URL              = os.environ.get("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND          = os.environ.get("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_TIMEZONE                = "America/Lima"
CELERY_TASK_SERIALIZER         = "json"
CELERY_RESULT_SERIALIZER       = "json"
CELERY_ACCEPT_CONTENT          = ["json"]
CELERY_TASK_TRACK_STARTED      = True
CELERY_TASK_TIME_LIMIT         = 60 * 60 * 3   # 3 horas max por tarea (descarga del composite)
# Reciclar el hijo del pool cada 100 tareas: acota cualquier fuga de memoria del
# escuchador SQS (corre cada 5-30 s) sin coste apreciable. La memoria de la tarea
# quincenal ya se devuelve al SO al terminar (verificado con 20_medir_pico_memoria).
CELERY_WORKER_MAX_TASKS_PER_CHILD = 100

# Celery Beat - tarea quincenal (cada 15 dias a las 03:00 Lima)
from celery.schedules import crontab
CELERY_BEAT_SCHEDULE = {
    # Procesamiento quincenal Sentinel-2 (dia 1 y 16 a las 03:00 Lima)
    "procesar-quincena-tambopata": {
        "task": "ml_engine.tasks.procesar_quincena_tambopata",
        "schedule": crontab(hour=3, minute=0, day_of_month="1,16"),
    },
    # Reporte mensual (dia 1 de cada mes a las 04:00 Lima)
    "generar-reporte-mensual": {
        "task": "ml_engine.tasks.generar_reporte_mensual",
        "schedule": crontab(hour=4, minute=0, day_of_month="1"),
    },
    # Garbage Collection S3 (cada lunes a las 02:00 Lima)
    "limpiar-archivos-temporales-s3": {
        "task": "ml_engine.tasks.limpiar_archivos_temporales_s3",
        "schedule": crontab(hour=2, minute=0, day_of_week="1"),
    },
    # Fase G3: cierra INCERTIDUMBRE sin deteccion hace N pasadas.
    # Diaria e idempotente; corre a las 05:00 (2h tras la quincena de las 03:00).
    "cerrar-incertidumbres-obsoletas": {
        "task": "ml_engine.tasks.cerrar_incertidumbres_obsoletas",
        "schedule": crontab(hour=5, minute=0),
    },
    # Escucha SQS: empieza en 30s; se auto-ajusta a 5s cuando hay mensajes
    "procesar-resultados-sagemaker": {
        "task": "ml_engine.tasks.procesar_resultado_sagemaker",
        "schedule": 30.0,  # segundos (valor inicial; la tarea lo ajusta dinamicamente)
    },
}

# -- AWS --
AWS_REGION_NAME              = os.environ.get("AWS_REGION_NAME",  "us-east-1")
AWS_S3_BUCKET_NAME           = os.environ.get("AWS_S3_BUCKET",    "apuguard-datalake-prod")
AWS_SAGEMAKER_ENDPOINT_NAME  = os.environ.get("SAGEMAKER_ENDPOINT", "apuguard-endpoint")
AWS_SQS_RESULT_QUEUE_URL     = os.environ.get("SQS_RESULT_QUEUE_URL", "")
AWS_SNS_ALERT_TOPIC_ARN      = os.environ.get("SNS_ALERT_TOPIC_ARN",  "")

# Prefijos S3
S3_PREFIX_RAW_RASTERS   = "raw-rasters/"
S3_PREFIX_SAGEMAKER_IN  = "sagemaker-inputs/"
S3_PREFIX_SAGEMAKER_OUT = "sagemaker-outputs/"
S3_PREFIX_STATIC_LAYERS = "static-layers/"   # mineria.tif, rios.tif

# -- Twilio SMS --
TWILIO_ACCOUNT_SID  = os.environ.get("TWILIO_ACCOUNT_SID",  "")
TWILIO_AUTH_TOKEN   = os.environ.get("TWILIO_AUTH_TOKEN",   "")
TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER", "")

# -- Adquisicion de imagenes (composite quincenal) --
#   stac: Earth Search (AWS). COG publicos, sin cuenta ni cuota de GEE.
#   gee : Google Earth Engine (comportamiento historico, requiere service account).
IMAGERY_SOURCE = os.environ.get("IMAGERY_SOURCE", "stac")
# Techo de eo:cloud_cover (%) para descartar escenas STAC. Vacio = sin tope.
IMAGERY_MAX_CLOUD = (
    float(os.environ["IMAGERY_MAX_CLOUD"])
    if os.environ.get("IMAGERY_MAX_CLOUD") else None
)

# -- Google Earth Engine (solo si IMAGERY_SOURCE=gee) --
GEE_SERVICE_ACCOUNT = os.environ.get("GEE_SERVICE_ACCOUNT", "")
GEE_KEY_FILE        = os.environ.get("GEE_KEY_FILE",        "/secrets/gee_key.json")

# -- Tambopata AOI (Bounding Box EPSG:4326) --
# Derivado del extent exacto de los composites de entrenamiento
# (Tambopata_2024_EPSG32719.tif: 14870x7426px @ 10m, UTM X=380480..529180, Y=8543460..8617720)
TAMBOPATA_BBOX = {
    "min_lon": -70.10,
    "min_lat": -13.18,
    "max_lon": -68.74,
    "max_lat": -12.50,
}

# -- Seguridad (preparados, APAGADOS por defecto) --
# Se activan por variable de entorno en la Fase A', justo antes del despliegue.
# Con HTTP (sin TLS todavia) deben seguir apagados o Django redirige en bucle.
SECURE_SSL_REDIRECT         = env.bool("SECURE_SSL_REDIRECT",  default=False)
SESSION_COOKIE_SECURE       = env.bool("SESSION_COOKIE_SECURE", default=False)
CSRF_COOKIE_SECURE          = env.bool("CSRF_COOKIE_SECURE",    default=False)
SECURE_HSTS_SECONDS         = env.int("SECURE_HSTS_SECONDS",    default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False
)
SECURE_HSTS_PRELOAD         = env.bool("SECURE_HSTS_PRELOAD", default=False)
# Detras de un proxy/load-balancer: solo activar si hay TLS terminado ahi.
if env.bool("SECURE_PROXY_SSL_HEADER", default=False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# -- Logging --
# Silencia el ruido DEBUG de boto3/botocore en celery_worker (firmas AWS, headers, etc.)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "[{asctime}] {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "loggers": {
        "botocore":   {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "boto3":      {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "s3transfer": {"level": "WARNING", "handlers": ["console"], "propagate": False},
        "urllib3":    {"level": "WARNING", "handlers": ["console"], "propagate": False},
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}
