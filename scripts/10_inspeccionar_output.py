"""
10_inspeccionar_output.py
==========================
Descarga el primer output procesado de S3 y muestra sus metricas:
shape, dtype, min/max/mean de cada tensor (mask, probability, entropy).

SageMaker Async deposita los outputs como .out (UUID). Por compatibilidad,
tambien busca .npz.

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/10_inspeccionar_output.py
"""
import io
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _template_python import setup, get_s3, BUCKET
setup()

import django
django.setup()

import numpy as np
from core.models import ParcheProcesamiento


def main():
    parche = ParcheProcesamiento.objects.filter(
        estado_sagemaker="PROCESADO"
    ).exclude(s3_path_resultado="").exclude(s3_path_resultado__isnull=True).first()

    if not parche:
        print("No hay parches procesados con resultado en BD.")
        print("Ejecuta primero 04_lanzar_quincena.py y 05_lanzar_escucha.py")
        return 1

    print(f"Parche: {parche.pk} | captura: {parche.captura_id}")
    print(f"Tensor: {parche.s3_path_tensor}")
    print(f"Output: {parche.s3_path_resultado}")

    s3 = get_s3()
    path = parche.s3_path_resultado.replace("s3://", "")
    if "/" not in path:
        print(f"[ERROR] Output path invalido: {parche.s3_path_resultado}")
        return 1
    bucket, key = path.split("/", 1)

    try:
        r = s3.get_object(Bucket=bucket, Key=key)
        datos = np.load(io.BytesIO(r["Body"].read()))
    except Exception as e:
        print(f"[ERROR] Descargando {key}: {e}")
        return 1

    print(f"\nClaves en archivo: {list(datos.keys())}")
    for k in datos.keys():
        arr = datos[k]
        print(f"  {k}: shape={arr.shape} dtype={arr.dtype} "
              f"min={arr.min():.4f} max={arr.max():.4f} mean={arr.mean():.4f}")

    if "mask" in datos:
        mask = datos["mask"]
        positivos = (mask > 0).sum()
        print(f"\n  Pixeles deforestacion (mask>0): {positivos} / {mask.size}")
        if mask.size > 0:
            print(f"  Porcentaje deforestado:        {positivos / mask.size * 100:.2f}%")
    if "probability" in datos:
        prob = datos["probability"]
        print(f"  Probabilidad max:  {prob.max():.4f}")
        print(f"  Pixeles prob > 0.5: {(prob > 0.5).sum()}")
        print(f"  Pixeles prob > 0.8: {(prob > 0.8).sum()}")
    if "entropy" in datos:
        ent = datos["entropy"]
        print(f"  Entropia media:    {ent.mean():.4f}")
        print(f"  Entropia max:      {ent.max():.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
