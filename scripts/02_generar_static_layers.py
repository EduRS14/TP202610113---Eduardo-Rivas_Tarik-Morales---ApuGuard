"""
02_generar_static_layers.py
=============================
Genera mineria.tif y rios.tif y los sube a S3 en static-layers/.

NOTA: Esta es una version DEMO que genera rasters sinteticos.
      Para produccion, rasterizar shapefiles reales siguiendo el README.

Uso (requiere Python con boto3, rasterio, numpy):
    pip install boto3 rasterio numpy
    python 02_generar_static_layers.py
"""
import io
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _template_python import setup, get_s3, BUCKET, S3_PREFIX_STATIC_LAYERS
setup()

import numpy as np
import rasterio
from rasterio.transform import from_bounds


MIN_LON, MIN_LAT = -70.10, -13.50
MAX_LON, MAX_LAT = -69.00, -12.30
WIDTH, HEIGHT   = 256, 256


def main():
    s3 = get_s3()
    transform = from_bounds(MIN_LON, MIN_LAT, MAX_LON, MAX_LAT, WIDTH, HEIGHT)

    for nombre, valor_base in [("mineria", 0.3), ("rios", 0.5)]:
        data = np.random.uniform(valor_base, 1.0, (HEIGHT, WIDTH)).astype(np.float32)
        buf = io.BytesIO()
        with rasterio.open(
            buf, "w",
            driver="GTiff", height=HEIGHT, width=WIDTH,
            count=1, dtype="float32", crs="EPSG:4326",
            transform=transform,
        ) as dst:
            dst.write(data, 1)
        buf.seek(0)
        key = f"{S3_PREFIX_STATIC_LAYERS}{nombre}.tif"
        s3.put_object(Bucket=BUCKET, Key=key, Body=buf.read(), ContentType="image/tiff")
        print(f"  Subido: s3://{BUCKET}/{key}")

    print(f"\n[OK] Static layers generados en s3://{BUCKET}/{S3_PREFIX_STATIC_LAYERS}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
