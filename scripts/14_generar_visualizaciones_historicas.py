"""
14_generar_visualizaciones_historicas.py
=========================================
Recorre la base de datos y genera los PNGs (RGB + mask) para todos los
ParcheProcesamiento con estado PROCESADO que aun no tengan _rgb.png
en sagemaker-visualizations/.

Util para backfill despues de activar el nuevo flujo de generacion en backend,
o para regenerar PNGs que se hayan borrado manualmente.

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/14_generar_visualizaciones_historicas.py

Opcionales:
    --solo-faltantes  : solo procesa parches sin _rgb.png (default: True)
    --todos           : regenera TODOS los PROCESADO, sobreescribiendo PNGs existentes
    --captura-id N    : solo procesa parches de la captura N
    --dry-run         : no sube a S3, solo muestra que haria
"""
import argparse
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
from PIL import Image
from django.conf import settings

from core.models import ParcheProcesamiento


def _stretch(canal):
    p2, p98 = np.percentile(canal, (2, 98))
    return (np.clip(canal, p2, p98) - p2) / (p98 - p2 + 1e-8) * 255


def existe_png(s3, key):
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        return True
    except Exception:
        return False


def generar_para_parche(s3, parche, dry_run=False):
    """Descarga .npy y .out, genera los 2 PNGs, los sube a S3. Devuelve (ok, mensaje)."""
    captura_id = parche.captura_id
    fila = parche.fila_idx
    col = parche.col_idx
    base = f"sagemaker-visualizations/captura_{captura_id}/parche_{fila}_{col}"

    if not parche.s3_path_tensor:
        return False, "sin s3_path_tensor"
    if not parche.s3_path_resultado:
        return False, "sin s3_path_resultado"

    npy_key  = parche.s3_path_tensor.replace("s3://", "").split("/", 1)[1]
    out_key  = parche.s3_path_resultado.replace("s3://", "").split("/", 1)[1]

    try:
        npy_bytes = s3.get_object(Bucket=BUCKET, Key=npy_key)["Body"].read()
        tensor    = np.load(io.BytesIO(npy_bytes))    # [1, 9, 128, 128]
    except Exception as e:
        return False, f"error descargando .npy: {e}"

    try:
        out_bytes = s3.get_object(Bucket=BUCKET, Key=out_key)["Body"].read()
        datos     = np.load(io.BytesIO(out_bytes))    # [1, 1, 128, 128]
        prob      = datos["probability"][0, 0]       # [128, 128]
    except Exception as e:
        return False, f"error descargando .out: {e}"

    # RGB
    r = _stretch(tensor[0, 2]).astype(np.uint8)
    g = _stretch(tensor[0, 1]).astype(np.uint8)
    b = _stretch(tensor[0, 0]).astype(np.uint8)
    rgb = np.stack((r, g, b), axis=-1)

    # Mask RGBA
    alpha = (prob * 255).astype(np.uint8)
    rgba  = np.stack((
        np.full((128, 128), 255, dtype=np.uint8),
        np.zeros((128, 128), dtype=np.uint8),
        np.zeros((128, 128), dtype=np.uint8),
        alpha,
    ), axis=-1)

    rgb_buf  = io.BytesIO();  Image.fromarray(rgb, "RGB").save(rgb_buf,  format="PNG"); rgb_buf.seek(0)
    mask_buf = io.BytesIO();  Image.fromarray(rgba, "RGBA").save(mask_buf, format="PNG"); mask_buf.seek(0)

    if dry_run:
        return True, "dry-run OK"

    s3.put_object(Bucket=BUCKET, Key=f"{base}_rgb.png",
                  Body=rgb_buf.getvalue(),  ContentType="image/png")
    s3.put_object(Bucket=BUCKET, Key=f"{base}_mask.png",
                  Body=mask_buf.getvalue(), ContentType="image/png")
    return True, "OK"


def main():
    parser = argparse.ArgumentParser(description="Genera PNGs historicos de parches procesados")
    parser.add_argument("--todos", action="store_true",
                        help="Regenera TODOS los PROCESADO (no solo faltantes)")
    parser.add_argument("--captura-id", type=int, default=None,
                        help="Solo procesar parches de esta captura")
    parser.add_argument("--dry-run", action="store_true",
                        help="No sube a S3, solo simula")
    args = parser.parse_args()

    s3 = get_s3()
    qs = ParcheProcesamiento.objects.filter(estado_sagemaker="PROCESADO")
    if args.captura_id is not None:
        qs = qs.filter(captura_id=args.captura_id)

    total = qs.count()
    if total == 0:
        print("[INFO] No hay parches PROCESADO en la BD.")
        return 0

    print(f"[INFO] {total} parches PROCESADO encontrados" +
          (f" (captura {args.captura_id})" if args.captura_id else "") + ".")

    procesados = 0
    saltados   = 0
    errores    = 0

    for parche in qs.iterator():
        base = f"sagemaker-visualizations/captura_{parche.captura_id}/parche_{parche.fila_idx}_{parche.col_idx}_rgb.png"

        if not args.todos and existe_png(s3, base):
            saltados += 1
            continue

        ok, msg = generar_para_parche(s3, parche, dry_run=args.dry_run)
        if ok:
            procesados += 1
            accion = "[DRY]" if args.dry_run else "[OK]"
            print(f"  {accion}  captura={parche.captura_id} parche=[{parche.fila_idx},{parche.col_idx}]")
        else:
            errores += 1
            print(f"  [ERR] captura={parche.captura_id} parche=[{parche.fila_idx},{parche.col_idx}] -> {msg}")

    print("")
    print("=" * 60)
    print(f" Procesados : {procesados}")
    print(f" Saltados   : {saltados}  (ya tenian _rgb.png)")
    print(f" Errores    : {errores}")
    print(f" Modo       : {'dry-run' if args.dry_run else 'escritura real'}")
    print("=" * 60)
    return 0 if errores == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
