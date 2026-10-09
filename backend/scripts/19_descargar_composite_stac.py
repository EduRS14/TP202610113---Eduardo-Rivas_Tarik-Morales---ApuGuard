#!/usr/bin/env python
"""
19_descargar_composite_stac.py - APU GUARD
===========================================
Prueba de la NUEVA fuente de adquisicion (STAC / Earth Search en AWS) que
sustituye a Google Earth Engine.

Hace tres cosas:
  1. Descarga el composite mediano del periodo para un bbox (por defecto el
     AOI de Tambopata) y lo escribe como GeoTIFF.
  2. Valida que el raster cumple EXACTAMENTE el contrato que espera el resto
     del pipeline (4 bandas int16, EPSG:32719, 10 m, nodata=0, rango 0..10000).
  3. Ejecuta el preprocesamiento real (z-score + canales + extraer_parches)
     sobre un recorte para demostrar que los parches salen [9,128,128] y que
     las bbox quedan en EPSG:4326 dentro del AOI.
  4. Genera PNG (RGB y falso color NIR) para corroboracion visual.

Uso:
    python scripts/19_descargar_composite_stac.py
    python scripts/19_descargar_composite_stac.py --bbox "-70.0,-12.9,-69.9,-12.8"
    python scripts/19_descargar_composite_stac.py --days 15 --out C:/tmp/apuguard

Dentro de docker:
    docker compose exec web python /app/scripts/19_descargar_composite_stac.py
"""

import argparse
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from ml_engine.acquisition import (
    BANDAS,
    CRS_SALIDA,
    descargar_composite_stac,
    generar_preview,
    validar_composite,
)

# AOI de Tambopata (mismo que settings.TAMBOPATA_BBOX)
BBOX_FULL = (-70.10, -13.18, -68.74, -12.50)


def log(titulo):
    print("\n" + "=" * 78)
    print(titulo)
    print("=" * 78)


def fase_busqueda(fecha_ini, fecha_fin, bbox, max_cloud):
    from ml_engine.acquisition import buscar_items_stac
    t0 = time.time()
    items = buscar_items_stac(bbox, fecha_ini, fecha_fin, max_cloud=max_cloud)
    log("FASE 1 - Busqueda STAC")
    print(f"  endpoint : {os.environ.get('STAC_URL', 'Earth Search (AWS)')}")
    print(f"  periodo  : {fecha_ini} -> {fecha_fin}")
    print(f"  bbox     : {bbox}")
    print(f"  items    : {len(items)}  ({time.time() - t0:.1f}s)")
    if not items:
        print("  [FALLA] sin items")
        return []
    grids = sorted({i["grid"] for i in items if i["grid"]})
    fechas = sorted({i["datetime"][:10] for i in items if i["datetime"]})
    nubes = [i["cloud"] for i in items if i["cloud"] is not None]
    print(f"  tiles   : {', '.join(grids)}")
    print(f"  fechas   : {', '.join(fechas)}")
    if nubes:
        print(f"  nubes    : media={np.mean(nubes):.1f}%  min={min(nubes):.1f}%  max={max(nubes):.1f}%")
    faltan = [a for a in BANDAS + ("scl",) if not any(a in i["hrefs"] for i in items)]
    if faltan:
        print(f"  [ADVERTENCIA] assets ausentes: {faltan}")
    else:
        print("  [PASA] assets blue/green/red/nir/scl disponibles")
    return items


def fase_composite(fecha_ini, fecha_fin, bbox, args, out_path):
    log("FASE 2 - Construccion del composite (bloques, memoria acotada)")
    t0 = time.time()
    path, cobertura, transform, crs = descargar_composite_stac(
        fecha_ini, fecha_fin, bbox,
        max_cloud=args.max_cloud,
        out_path=out_path,
        block_rows=args.block_rows,
        preview_path=None,
    )
    print(f"  tiempo   : {time.time() - t0:.1f}s")
    print(f"  salida   : {path}")
    print(f"  tamano   : {os.path.getsize(path) / 1e6:.1f} MB en disco")
    print(f"  nubes    : {cobertura:.1f}%  (-> CapturaSatelital.cobertura_nubes)")
    print(f"  transform: {tuple(round(v, 1) for v in transform[:6])}")
    print(f"  crs      : {crs}")
    return path, cobertura


def fase_validacion(path, bbox):
    log("FASE 3 - Validacion del contrato de formato")
    rep = validar_composite(path, bbox)
    for c in rep["chequeos"]:
        marca = "PASA" if c["ok"] else "FALLA"
        print(f"  [{marca}] {c['check']}: esperado={c['esperado']} obtenido={c['obtenido']}"
              + (f"  {c['detalle']}" if c["detalle"] else ""))
    print(f"  shape    : {rep['shape_hw'][0]} x {rep['shape_hw'][1]} px")
    print(f"  bounds   : {rep['bounds']}")
    for b in rep["bandas"]:
        print(f"  banda {b['banda']}: min={b['min']} max={b['max']} "
              f"media={b['media_validos']} nodata={b['pct_nodata']}%")
    if not rep["ok"]:
        print("  [FALLA] el raster NO cumple el contrato")
    return rep


def fase_downstream(path, args):
    """
    Reproduce el consumo real de `procesar_quincena_tambopata` sobre un recorte.
    """
    log("FASE 4 - Downstream (z-score -> tensor 9 canales -> extraer_parches)")
    import rasterio
    from rasterio.windows import Window

    from ml_engine import preprocessing as pp

    with rasterio.open(path) as src:
        h = min(src.height, args.crop)
        w = min(src.width, args.crop)
        win = Window(0, 0, w, h)
        datos = src.read(window=win).astype(np.float32)
        transform = src.window_transform(win)
        crs = src.crs
        bounds = src.bounds

    print(f"  recorte   : {datos.shape}  crs={crs}")

    # --- igual que tasks.py:113-123 ---
    blue, green, red, nir = datos[0], datos[1], datos[2], datos[3]
    for banda in (blue, green, red, nir):
        banda[banda == 0] = np.nan

    tensor = np.empty((9,) + blue.shape, dtype=np.float32)
    tensor[0] = blue
    tensor[1] = green
    tensor[2] = red
    tensor[3] = nir

    eps = 1e-8
    tensor[4] = (tensor[3] - tensor[1]) / (tensor[3] + tensor[1] + eps)
    tensor[5] = ((tensor[3] - tensor[2]) / (tensor[3] + tensor[2] + 0.5 + eps)) * 1.5

    for i in range(6):
        mean = float(np.nanmean(tensor[i]))
        std = float(np.nanstd(tensor[i]))
        tensor[i] -= mean
        tensor[i] /= (std + eps)

    # canales 6-8: en produccion salen de PostGIS + S3; aqui se sustituyen
    # por constantes SOLO para validar la geometria del tiling.
    tensor[6] = 1.0
    tensor[7] = 1.0
    tensor[8] = 1.0

    nan_ratio = float(np.isnan(tensor[:6]).mean())
    print(f"  NaN global: {nan_ratio * 100:.2f}%  (parche se descarta si >20%)")

    n = 0
    primer_bbox = None
    fuera = 0
    for parche, fila, col, bbox in pp.extraer_parches(tensor, transform):
        if parche.shape != (9, pp.PATCH_SIZE, pp.PATCH_SIZE):
            print(f"  [FALLA] forma de parche inesperada: {parche.shape}")
            return False
        if not np.isfinite(parche).all():
            print(f"  [FALLA] parche [{fila},{col}] con NaN residuales")
            return False
        if not (-180 <= bbox[0] <= 180 and -90 <= bbox[1] <= 90):
            print(f"  [FALLA] bbox fuera de rango WGS84: {bbox}")
            return False
        if not (BBOX_FULL[0] - 0.3 <= bbox[0] <= BBOX_FULL[2] + 0.3
                and BBOX_FULL[1] - 0.3 <= bbox[1] <= BBOX_FULL[3] + 0.3):
            fuera += 1
        if primer_bbox is None:
            primer_bbox = (fila, col, tuple(round(v, 5) for v in bbox))
        n += 1

    print(f"  parches   : {n} de tamano {pp.PATCH_SIZE}x{pp.PATCH_SIZE}, stride={pp.STRIDE}")
    if primer_bbox:
        print(f"  ejemplo   : fila={primer_bbox[0]} col={primer_bbox[1]} "
              f"lon/lat={primer_bbox[2]}")
    if n == 0:
        print("  [FALLA] no se genero ningun parche")
        return False
    if fuera:
        print(f"  [ADVERTENCIA] {fuera} parches con bbox fuera del AOI (+-0.3 deg)")
    print("  [PASA] parches [9,128,128] finitos y bbox en EPSG:4326")
    return True


def fase_preview(path, out_dir):
    log("FASE 5 - Visual")
    rgb = os.path.join(out_dir, "preview_rgb.png")
    nir = os.path.join(out_dir, "preview_nir.png")
    generar_preview(path, rgb, max_side=1400, banda_rgb=(3, 2, 1))     # R,G,B
    generar_preview(path, nir, max_side=1400, banda_rgb=(4, 3, 1))     # NIR,R,G
    print(f"  RGB        : {rgb}")
    print(f"  NIR/R/G    : {nir}")
    return rgb, nir


def main():
    ap = argparse.ArgumentParser(description="Prueba de adquisicion STAC (reemplazo de GEE)")
    ap.add_argument("--bbox", default="full",
                    help="'full' o 'min_lon,min_lat,max_lon,max_lat'")
    ap.add_argument("--days", type=int, default=15, help="ventana hacia atras (dias)")
    ap.add_argument("--fecha-ini", default=None, help="AAAA-MM-DD")
    ap.add_argument("--fecha-fin", default=None, help="AAAA-MM-DD")
    ap.add_argument("--out", default=None, help="directorio de salida")
    ap.add_argument("--max-cloud", type=float, default=90.0)
    ap.add_argument("--block-rows", type=int, default=512)
    ap.add_argument("--crop", type=int, default=1024,
                    help="lado maximo del recorte para la prueba downstream")
    ap.add_argument("--keep", action="store_true",
                    help="no borrar el GeoTIFF al terminar")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="  %(levelname)-7s %(message)s",
    )

    from datetime import date, timedelta
    if args.fecha_fin:
        fecha_fin = date.fromisoformat(args.fecha_fin)
    else:
        fecha_fin = date.today() - timedelta(days=1)
    if args.fecha_ini:
        fecha_ini = date.fromisoformat(args.fecha_ini)
    else:
        fecha_ini = fecha_fin - timedelta(days=args.days)

    if args.bbox == "full":
        bbox = BBOX_FULL
    else:
        bbox = tuple(float(v) for v in args.bbox.split(","))
        assert len(bbox) == 4, "bbox debe tener 4 valores"

    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "out_stac")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(
        out_dir,
        f"composite_{fecha_ini}_{fecha_fin}_"
        f"{'full' if args.bbox == 'full' else 'chico'}.tif",
    )

    print("APU GUARD - verificacion de adquisicion STAC")
    print(f"  salida -> {out_dir}")

    fase_busqueda(fecha_ini, fecha_fin, bbox, args.max_cloud)
    path, _ = fase_composite(fecha_ini, fecha_fin, bbox, args, out_path)
    rep = fase_validacion(path, bbox)
    ok = rep["ok"] and fase_downstream(path, args)
    fase_preview(path, out_dir)

    log("RESULTADO")
    print("  [PASA] nuevo flujo de obtencion de datos operativo" if ok
          else "  [FALLA] revisa los chequeos anteriores")

    if ok and not args.keep:
        pass
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
