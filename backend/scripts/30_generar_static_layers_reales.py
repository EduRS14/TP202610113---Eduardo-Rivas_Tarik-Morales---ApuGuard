"""
30_generar_static_layers_reales.py
===================================
Genera las capas estaticas REALES (raster de distancia) a partir de los
shapefiles de la entrega y las sube a S3 en static-layers/:

    mineria.tif  <- Catastro_Minero_2024/CatastroMinero_WGS84_19S_220524.shp
    rios.tif     <- Rios/RIOS_MADRE_DE_DIOS_...shp (buffer 50 m)

Contrato de consumidor (ml_engine/preprocessing.calcular_dist_capa_estatica):
  * GeoTIFF float32, valores en [0, 1]
  * valor = distancia euclidiana al pixel mas cercano con el rasgo,
    normalizada por la distancia maxima (mismo criterio que
    calcular_dist_deforest); 0 = sobre el rasgo, 1 = punto mas lejano
  * el CRS/geotransform del raster se IGNORA al consumir (solo se lee la
    banda 1 y se re-escala bilineal al shape del composite), pero se
    genera sobre la rejilla exacta del composite para fidelidad

Rejilla (settings.py TAMBOPATA_BBOX / Tambopata_2024_EPSG32719.tif):
  EPSG:32719, X 380480..529180, Y 8543460..8617720 (14870x7426 px @10 m).
  Se rasteriza a RES m por celda (~6.9 M px a 40 m): el EDT en la rejilla
  de 10 m (110 M px) no cabe en la t3.small, y el consumidor re-escala
  igualmente al shape del composite.

Uso (requiere boto3, rasterio, scipy, geopandas; localmente con perfil default):
    python backend/scripts/30_generar_static_layers_reales.py
    python backend/scripts/30_generar_static_layers_reales.py --sin-subir
    python backend/scripts/30_generar_static_layers_reales.py --res 40

Antes de sobrescribir, copia las capas demo actuales a
    static-layers/mineria-demo.tif  y  static-layers/rios-demo.tif
(una sola vez: si el -demo.tif ya existe no se pisa).
"""
import argparse
import io
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]   # .../apuguard_stac
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _template_python import get_s3, load_env


def cargar_config():
    """settings de Django si el entorno lo permite; si no, el .env directo."""
    try:
        from _template_python import setup
        setup()
        from django.conf import settings
        return settings.AWS_S3_BUCKET_NAME, "Django"
    except Exception as exc:
        load_env()
        bucket = os.environ.get("AWS_S3_BUCKET_NAME") or os.environ.get("AWS_S3_BUCKET", "tu-bucket-datalake")
        return bucket, f"env local (.env, sin Django: {type(exc).__name__})"


BUCKET, ORIGEN_CONFIG = cargar_config()
S3_PREFIX_STATIC_LAYERS = "static-layers/"

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from scipy.ndimage import distance_transform_edt
from shapely.geometry import box

# Rejilla del composite de entrenamiento (ver settings.py, linea ~253)
CRS_TRABAJO = "EPSG:32719"
X_MIN, X_MAX = 380480.0, 529180.0
Y_MIN, Y_MAX = 8543460.0, 8617720.0
RES_DEFAULT = 40                     # metros por celda de trabajo

BUFFER_RIOS_M = 50.0                 # decision: rios con buffer de 50 m

RAW_REL = (RAIZ.parent / "Modelo final" / "entrega_hrnet_final_v1"
           / "entrega_hrnet_final_v1" / "hrnet_training_package"
           / "dataset_pipeline" / "data" / "raw")
CATASTRO_REL = Path("Catastro_Minero") / "Catastro_Minero_2024" / "CatastroMinero_WGS84_19S_220524.shp"
RIOS_REL = Path("Rios") / "RIOS_MADRE_DE_DIOS_geogpsperu_SuyoPomalia_931381206.shp"

OUT_DIR = RAIZ / "static-layers-out"


def cargar_geoms(raw_dir: Path, capa: str) -> gpd.GeoDataFrame:
    """Lee el shapefile, lo reproyecta al CRS de trabajo y lo recorta al AOI."""
    if capa == "mineria":
        shp = raw_dir / CATASTRO_REL
    else:
        shp = raw_dir / RIOS_REL
    if not shp.exists():
        raise SystemExit(f"[ERROR] no existe el shapefile: {shp}")
    print(f"  Leyendo {shp.name} ...")
    gdf = gpd.read_file(shp)
    print(f"    n={len(gdf)} crs={gdf.crs} tipos={sorted(set(gdf.geom_type))}")
    gdf = gdf.to_crs(CRS_TRABAJO)
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()]
    if capa == "rios":
        t0 = time.time()
        gdf = gdf.set_geometry(gdf.geometry.buffer(BUFFER_RIOS_M))
        print(f"    buffer {BUFFER_RIOS_M:.0f} m aplicado ({time.time()-t0:.1f}s)")
    # Recorte al AOI (bbox de la rejilla): evita rasterizar todo el dataset
    aoI = box(X_MIN, Y_MIN, X_MAX, Y_MAX)
    dentro = gdf.intersects(aoI)
    gdf = gdf[dentro]
    print(f"    dentro del AOI: {len(gdf)} / {int(dentro.size)}")
    if gdf.empty:
        raise SystemExit(f"[ERROR] sin geometrias dentro del AOI para {capa}")
    return gdf


def generar_capa(gdf: gpd.GeoDataFrame, H: int, W: int, transform) -> np.ndarray:
    """Rasteriza los rasgos y devuelve la distancia normalizada [0, 1]."""
    mascara = rasterize(
        ((geom, 1) for geom in gdf.geometry),
        out_shape=(H, W),
        transform=transform,
        fill=0,
        all_touched=True,
        dtype=np.uint8,
    )
    cobertura = float(mascara.mean())
    if cobertura <= 0.0:
        raise SystemExit("[ERROR] el rasgo no cae dentro de la rejilla (cobertura 0)")
    t0 = time.time()
    dist = distance_transform_edt(mascara == 0).astype(np.float32)   # celda 0 = sobre rasgo
    del mascara
    max_dist = float(dist.max())
    if max_dist > 0:
        dist /= max_dist
    print(f"    EDT en {time.time()-t0:.1f}s | cobertura={cobertura*100:.3f}% "
          f"| max_dist_celdas={max_dist:.0f}")
    return np.clip(dist, 0.0, 1.0).astype(np.float32)


def escribir_tif(path: Path, data: np.ndarray, transform) -> None:
    with rasterio.open(
        path, "w", driver="GTiff", height=data.shape[0], width=data.shape[1],
        count=1, dtype="float32", crs=CRS_TRABAJO, transform=transform,
        compress="deflate", predictor=3, tiled=True,
    ) as dst:
        dst.write(data, 1)


def respaldar_demo(s3, nombre: str) -> None:
    """Copia static-layers/<n>.tif -> <n>-demo.tif una sola vez."""
    origen, destino = f"{S3_PREFIX_STATIC_LAYERS}{nombre}.tif", f"{S3_PREFIX_STATIC_LAYERS}{nombre}-demo.tif"
    if s3.list_objects_v2(Bucket=BUCKET, Prefix=destino).get("KeyCount", 0):
        print(f"    demo ya respaldada: {destino}")
        return
    s3.copy_object(Bucket=BUCKET, CopySource={"Bucket": BUCKET, "Key": origen},
                   Key=destino, MetadataDirective="COPY")
    print(f"    demo respaldada: s3://{BUCKET}/{destino}")


def verificar_desde_s3(s3, nombre: str, data: np.ndarray) -> None:
    """Relee desde S3 y comprueba el contrato del consumidor."""
    resp = s3.get_object(Bucket=BUCKET, Key=f"{S3_PREFIX_STATIC_LAYERS}{nombre}.tif")
    with rasterio.open(io.BytesIO(resp["Body"].read())) as src:
        leido = src.read(1).astype(np.float32)
    ok_shape = leido.shape == data.shape
    ok_rango = bool(np.isfinite(leido).all() and leido.min() >= 0.0 and leido.max() <= 1.0)
    ok_igual = bool(np.array_equal(leido, data))
    estado = "PASA" if (ok_shape and ok_rango and ok_igual) else "FALLA"
    print(f"    relectura S3 [{estado}]: shape={ok_shape} rango=[0,1]={ok_rango} "
          f"identico={ok_igual} dtype={leido.dtype}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--raw-dir", default=str(RAW_REL), help="directorio data/raw de la entrega")
    ap.add_argument("--res", type=float, default=RES_DEFAULT, help="metros por celda (default 40)")
    ap.add_argument("--sin-subir", action="store_true", help="genera los GeoTIFF pero no sube a S3")
    args = ap.parse_args()

    raw_dir = Path(args.raw_dir)
    res = args.res
    W = int(round((X_MAX - X_MIN) / res))
    H = int(round((Y_MAX - Y_MIN) / res))
    transform = from_bounds(X_MIN, Y_MIN, X_MAX, Y_MAX, W, H)
    print(f"Config: bucket={BUCKET} [{ORIGEN_CONFIG}]")
    print(f"Rejilla: {W}x{H} px @ {res:g} m, {CRS_TRABAJO}")
    print(f"AOI: X {X_MIN:.0f}..{X_MAX:.0f}  Y {Y_MIN:.0f}..{Y_MAX:.0f}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    s3 = None if args.sin_subir else get_s3()

    resultados = {}
    for capa in ("mineria", "rios"):
        print(f"\n[{capa}]")
        gdf = cargar_geoms(Path(raw_dir), capa)
        data = generar_capa(gdf, H, W, transform)
        finitos = bool(np.isfinite(data).all())
        p2, p98 = (float(np.percentile(data, 2)), float(np.percentile(data, 98)))
        print(f"    min={data.min():.6f} max={data.max():.6f} mean={data.mean():.4f} "
              f"p2={p2:.4f} p98={p98:.4f} finitos={finitos}")
        if not finitos or data.min() != 0.0 or data.max() != 1.0:
            print(f"    [FALLA] {capa}: el rango debe ser exactamente [0, 1] con finitos")
            return 1
        path = OUT_DIR / f"{capa}.tif"
        escribir_tif(path, data, transform)
        print(f"    GeoTIFF: {path} ({path.stat().st_size} bytes)")
        resultados[capa] = (path, data)

    if args.sin_subir:
        print("\n[OK] --sin-subir: no se ha tocado S3")
        return 0

    print("\nSubida a S3:")
    for capa in ("mineria", "rios"):
        print(f"  [{capa}] respaldo demo:")
        respaldar_demo(s3, capa)
    for capa in ("mineria", "rios"):
        path, data = resultados[capa]
        key = f"{S3_PREFIX_STATIC_LAYERS}{capa}.tif"
        s3.put_object(Bucket=BUCKET, Key=key, Body=path.read_bytes(),
                      ContentType="image/tiff")
        print(f"  Subido: s3://{BUCKET}/{key}")
        verificar_desde_s3(s3, capa, data)

    print("\n[OK] Static layers reales en s3://{}/{}".format(BUCKET, S3_PREFIX_STATIC_LAYERS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
