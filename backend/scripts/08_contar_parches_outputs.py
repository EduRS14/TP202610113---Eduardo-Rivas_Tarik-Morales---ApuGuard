"""
08_contar_parches_outputs.py
=============================
Cuenta los archivos de output de SageMaker (S3 sagemaker-outputs/) e indica
la fecha del ultimo archivo subido.

SageMaker Async deposita los outputs como .out (UUID). Por compatibilidad,
tambien se cuentan los .npz si existieran.

Uso:
    python 08_contar_parches_outputs.py
"""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _template_python import setup, get_s3, BUCKET, S3_PREFIX_SAGEMAKER_OUT
setup()


def main():
    s3 = get_s3()
    paginator = s3.get_paginator("list_objects_v2")

    total = 0
    ultimo = None

    for page in paginator.paginate(Bucket=BUCKET, Prefix=S3_PREFIX_SAGEMAKER_OUT):
        for obj in page.get("Contents", []):
            # Aceptar tanto .out (formato real) como .npz (legacy)
            if not (obj["Key"].lower().endswith(".out") or obj["Key"].lower().endswith(".npz")):
                continue
            total += 1
            if ultimo is None or obj["LastModified"] > ultimo["LastModified"]:
                ultimo = obj

    print(f"Total outputs en s3://{BUCKET}/{S3_PREFIX_SAGEMAKER_OUT}: {total}")
    if ultimo:
        fecha = ultimo["LastModified"].astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        print(f"Ultimo archivo:     {ultimo['Key']}")
        print(f"Fecha modificacion: {fecha}")
    else:
        print("No hay archivos de output en sagemaker-outputs/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
