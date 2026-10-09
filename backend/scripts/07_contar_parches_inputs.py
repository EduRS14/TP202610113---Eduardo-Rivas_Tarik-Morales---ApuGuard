"""
07_contar_parches_inputs.py
=============================
Cuenta los archivos .npy en sagemaker-inputs/ de S3.

Uso:
    python 07_contar_parches_inputs.py [captura_id]
    Si se omite captura_id, lista todas las capturas con su conteo.

Variables de entorno requeridas (.env):
    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION_NAME, AWS_S3_BUCKET
"""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _template_python import setup, get_s3, BUCKET, S3_PREFIX_SAGEMAKER_IN
setup()


def listar_conteo_por_captura(s3, prefix):
    """Devuelve dict {captura_id: count}."""
    resultado = {}
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            partes = obj["Key"].split("/")
            if len(partes) >= 2 and partes[1].startswith("captura_"):
                cap = partes[1]
                resultado[cap] = resultado.get(cap, 0) + 1
    return resultado


def main():
    captura_id = sys.argv[1] if len(sys.argv) > 1 else None
    s3 = get_s3()

    if captura_id:
        prefix = f"{S3_PREFIX_SAGEMAKER_IN}captura_{captura_id}/"
        total = sum(
            p["KeyCount"]
            for p in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix)
        )
        print(f"Parches en s3://{BUCKET}/{prefix} : {total}")
    else:
        resultado = listar_conteo_por_captura(s3, S3_PREFIX_SAGEMAKER_IN)
        if not resultado:
            print(f"No hay parches en s3://{BUCKET}/{S3_PREFIX_SAGEMAKER_IN}")
            return 0
        print(f"Conteo de parches en s3://{BUCKET}/{S3_PREFIX_SAGEMAKER_IN}")
        total = 0
        for cap in sorted(resultado.keys()):
            n = resultado[cap]
            total += n
            print(f"  {cap}: {n} archivos .npy")
        print(f"\nTotal: {total} parches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
