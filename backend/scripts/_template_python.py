"""
_template_python.py
====================
Plantilla comun para los scripts de la carpeta scripts/.

Provee:
  - Carga automatica de .env desde backend/.env
  - Configuracion de Django (DJANGO_SETTINGS_MODULE=apuguard.settings)
  - Helpers de clientes AWS (s3, sagemaker, sqs)
  - Constantes del proyecto (BUCKET, PREFIXES)

Uso:
    from _template_python import setup, get_s3, BUCKET, S3_PREFIX_SAGEMAKER_IN

    setup()   # carga .env y configura Django
    s3 = get_s3()
    print(BUCKET)
"""
import os
import sys
from pathlib import Path


def _detectar_backend_dir():
    """
    Detecta la ubicacion de backend/ buscando hacia arriba desde este archivo.

    Esta plantilla puede vivir en:
      - <proyecto>/scripts/_template_python.py   -> backend_dir = <proyecto>/backend
      - <proyecto>/backend/scripts/_template_python.py -> backend_dir = <proyecto>/backend
    """
    archivo = Path(__file__).resolve()
    candidatos = [
        archivo.parent.parent / "backend",   # caso raiz /scripts/
        archivo.parent,                       # caso backend/scripts/
    ]
    for candidato in candidatos:
        if (candidato / "manage.py").exists() and (candidato / "apuguard" / "settings.py").exists():
            return candidato
    # Fallback: subir hasta encontrar manage.py
    actual = archivo.parent
    for _ in range(6):
        if (actual / "manage.py").exists():
            return actual
        actual = actual.parent
    return candidatos[0]   # mejor conjetura


BACKEND_DIR = _detectar_backend_dir()
RAIZ_PROYECTO = BACKEND_DIR.parent
ENV_PATH      = BACKEND_DIR / ".env"


def load_env(env_path: Path = ENV_PATH) -> None:
    """Carga variables de .env en os.environ (parser basico, sin dependencias)."""
    if not env_path.exists():
        return
    for linea in env_path.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        clave = clave.strip()
        valor = valor.strip().strip('"').strip("'")
        if clave and clave not in os.environ:
            os.environ[clave] = valor


def setup() -> None:
    """Carga .env, agrega backend/ al sys.path y configura Django."""
    load_env()
    sys.path.insert(0, str(BACKEND_DIR))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "apuguard.settings")
    import django
    django.setup()


def get_s3():
    import boto3
    return boto3.client(
        "s3",
        region_name=os.environ.get("AWS_REGION_NAME", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )


def get_sqs():
    import boto3
    return boto3.client(
        "sqs",
        region_name=os.environ.get("AWS_REGION_NAME", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )


def get_sagemaker_runtime():
    import boto3
    return boto3.client(
        "sagemaker-runtime",
        region_name=os.environ.get("AWS_REGION_NAME", "us-east-1"),
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )


BUCKET = os.environ.get("AWS_S3_BUCKET", "tu-bucket-datalake")
S3_PREFIX_RAW_RASTERS   = "raw-rasters/"
S3_PREFIX_SAGEMAKER_IN  = "sagemaker-inputs/"
S3_PREFIX_SAGEMAKER_OUT = "sagemaker-outputs/"
S3_PREFIX_STATIC_LAYERS = "static-layers/"
