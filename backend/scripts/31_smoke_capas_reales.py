"""
31_smoke_capas_reales.py
=========================
E2E de las capas estaticas REALES (static-layers/mineria.tif y rios.tif)
sobre los parches reales de captura_1 y el endpoint de produccion.

Partes:

  [A] Regenera ch7/ch8 de parches historicos de captura_1 usando EXACTAMENTE
      el camino de la quincena (calcular_dist_capa_estatica(target_shape=H,W)
      + estirar_canal_distancia con P2_P98_CH6_8) pero con las capas
      REALES, y sube los tensores a sagemaker-inputs/prueba_layers/.

  [B] Fidelidad (sanity): el mismo recorte con las capas DEMO debe
      reproducir los ch7/ch8 ya almacenados del parche original
      (max diff <= 1e-4). Si no coincide, el recorte NO replica a
      produccion y el smoke no vale: no se sube nada.

  [C] --comparar <npz-uri> --parche f,c: forward local MCD x20
      (model_source/inference.py + hrnet_final_seed42.pth) contra el .npz
      devuelto por el endpoint. PASA si corr(prob) >= 0.95,
      0.8 <= ratio medias <= 1.25 y la fraccion de pixeles con mascara
      difiere en <= 0.05.

ch6 (dist_deforest) y ch0-5 se conservan del parche original: ch6 depende
de la BD (dinamico) y no es el foco de este smoke.

Uso tipico (local, perfil default):
  python backend/scripts/31_smoke_capas_reales.py
  python backend/scripts/31_smoke_capas_reales.py --comparar s3://.../X.out --parche 0,50

El endpoint debe estar a >= 1 instancia para [C] (ver infra/README.md sec. 7).
"""
import argparse
import gc
import io
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent          # backend/
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(RAIZ))

from _template_python import load_env


def cargar_config():
    """settings de Django si el entorno lo permite; si no, el .env directo."""
    try:
        from _template_python import setup
        setup()
        import django
        django.setup()
        from django.conf import settings
        return (settings.AWS_REGION_NAME, settings.AWS_S3_BUCKET_NAME,
                "Django")
    except Exception as exc:
        load_env()
        import os
        region = os.environ.get("AWS_REGION_NAME", "us-east-1")
        bucket = os.environ.get("AWS_S3_BUCKET_NAME") or os.environ.get("AWS_S3_BUCKET")
        return region, bucket or "apuguard-datalake-prod", f"env local (sin Django: {type(exc).__name__})"


import numpy as np
import boto3

from ml_engine.preprocessing import (
    P2_P98_CH6_8,
    calcular_dist_capa_estatica,
    estirar_canal_distancia,
)

PATCH = 128
STRIDE = 128
STATIC = "static-layers/"
IN_PREFIX = "sagemaker-inputs/"
PRUEBA_PREFIX = f"{IN_PREFIX}prueba_layers/"
COMPOSITE_DEFECTO = "raw-rasters/sentinel2_2026-09-13_2026-09-28_10m.tif"
TOL_FIDELIDAD = 1e-4

MODEL_SOURCE = RAIZ.parent / "model_source"
ENTREGA_CKPTS = Path(
    r"D:\UPC\TP1\Modelo Claude\apuguard_deploy_new\apuguard_deploy"
    r"\Version final\Modelo final\entrega_hrnet_final_v1"
    r"\entrega_hrnet_final_v1\hrnet_training_package\checkpoints"
)

FALLAS = []
AVISOS = []


def check(nombre, cond, extra=""):
    estado = "PASA" if cond else "FALLA"
    if not cond:
        FALLAS.append(nombre)
    print(f"[{estado}] {nombre}" + (f" -> {extra}" if extra else ""))
    return cond


def aviso(nombre, detalle):
    AVISOS.append(nombre)
    print(f"[ADVERTENCIA] {nombre} -> {detalle}")


def _shape_composite(s3, bucket, key_composite):
    """H, W del GeoTIFF del composite leyendo solo el header via /vsis3/."""
    import rasterio
    uri = f"/vsis3/{bucket}/{key_composite}"
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
        with rasterio.open(uri) as src:
            return src.height, src.width


def _ventanas(cap, cortes, H, W):
    """Recorta el canal redimensionado [H,W] en las ventanas (fila,col)."""
    out = {}
    for (f, c) in cortes:
        r0, c0 = f * STRIDE, c * STRIDE
        out[(f, c)] = np.array(
            cap[r0:r0 + PATCH, c0:c0 + PATCH], dtype=np.float32, copy=True
        )
    return out


def _pasada_capa(s3, bucket, clave, cortes, H, W, etiqueta):
    t0 = time.time()
    cap = calcular_dist_capa_estatica(clave, s3, bucket, target_shape=(H, W))
    vts = _ventanas(cap, cortes, H, W)
    rango = (float(cap.min()), float(cap.max()))
    del cap
    gc.collect()
    print(f"  [{etiqueta}] {clave} -> {len(vts)} ventanas "
          f"({time.time() - t0:.1f}s, rango [{rango[0]:.3f}, {rango[1]:.3f}])")
    return vts


def _descargar_npy(s3, bucket, key):
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return np.load(io.BytesIO(obj["Body"].read()))
    except Exception as exc:
        print(f"  [AVISO] sin {key}: {type(exc).__name__}")
        return None


def _estirado(ventana, idx_canal):
    p2, p98 = P2_P98_CH6_8[idx_canal - 6]
    return estirar_canal_distancia(ventana.copy(), p2, p98)


def _tensor_v10(orig, real_m, real_r, crudo):
    """Copia del parche original dejado en contrato v10 (ch6-8 en [-1,1])
    con ch7/ch8 sustituidos por las capas REALES."""
    arr = orig.copy()
    if crudo:
        arr[0, 6] = _estirado(arr[0, 6], 6)
    arr[0, 7] = _estirado(real_m, 7)
    arr[0, 8] = _estirado(real_r, 8)
    return arr


def _ranking_local(tensores, batch=8):
    """Forward MCD local (model_source/inference.py) por lotes.
    Devuelve [(fc, prob_media, fraccion_mask), ...] ordenado por prob desc."""
    sys.path.insert(0, str(MODEL_SOURCE))
    import torch
    import inference as inf
    model = inf.model_fn(str(ENTREGA_CKPTS))
    fcs = sorted(tensores)
    res = []
    for i in range(0, len(fcs), batch):
        lote = np.concatenate([tensores[fc] for fc in fcs[i:i + batch]], axis=0)
        out = inf.predict_fn(torch.from_numpy(lote).float(), model)
        prob = out["probability"].mean(axis=(1, 2, 3))
        mfrac = out["mask"].mean(axis=(1, 2, 3))
        for j, fc in enumerate(fcs[i:i + batch]):
            res.append((fc, float(prob[j]), float(mfrac[j])))
    res.sort(key=lambda x: -x[1])
    return res


def generar(s3, bucket, args):
    print("=" * 70)
    print(" APU GUARD - E2E capas REALES: generacion de parches de prueba")
    print("=" * 70)

    H, W = _shape_composite(s3, bucket, args.composite)
    print(f"Composite: s3://{bucket}/{args.composite} -> {H}x{W}")

    if args.parches:
        cortes = [tuple(p) for p in args.parches]
    else:
        rng = np.random.default_rng(args.semilla)
        grid = [(f, c)
                for f in range((H - PATCH) // STRIDE + 1)
                for c in range((W - PATCH) // STRIDE + 1)]
        idx = rng.choice(len(grid), size=min(args.candidatos, len(grid)),
                         replace=False)
        cortes = sorted(grid[i] for i in idx)
    print(f"Candidatos ({len(cortes)}): {cortes[:6]}{' ...' if len(cortes) > 6 else ''}")

    print("\n[A] Pasadas de capas (zoom bilineal identico a produccion)...")
    demo_min = _pasada_capa(s3, bucket, f"{STATIC}mineria-demo.tif", cortes, H, W, "demo")
    real_min = _pasada_capa(s3, bucket, f"{STATIC}mineria.tif", cortes, H, W, "real")
    demo_ri = _pasada_capa(s3, bucket, f"{STATIC}rios-demo.tif", cortes, H, W, "demo")
    real_ri = _pasada_capa(s3, bucket, f"{STATIC}rios.tif", cortes, H, W, "real")

    print("\n[A] Descargando tensores originales de captura_1...")
    originales = {}
    for fc in cortes:
        arr = _descargar_npy(
            s3, bucket, f"{IN_PREFIX}captura_1/parche_{fc[0]}_{fc[1]}.npy")
        if arr is not None:
            if arr.ndim != 4 or arr.shape[1] != 9:
                aviso(f"forma inesperada en {fc}", str(arr.shape))
                continue
            originales[fc] = arr
    check("[A] tensores originales descargados", len(originales) > 0,
          f"{len(originales)}/{len(cortes)}")
    if not originales:
        return 1
    validos = sorted(originales)

    print("\n[B] Fidelidad: recorte DEMO == ch7/ch8 almacenados del parche...")
    # captura_1 se genero con el contrato v9: ch6-8 CRUDOS en [0,1]. Si el
    # original viene ya estirado ([-1,1], contrato v10) se compara estirado.
    crudo = all(float(originales[fc][0, 6:9].min()) >= 0.0 for fc in validos)
    check("[B] formato de ch6-8 detectado en los originales",
          True, "CRUDO [0,1] (v9): fidelidad en espacio crudo" if crudo
          else "ESTIRADO [-1,1] (v10): fidelidad en espacio estirado")
    dif_min, dif_ri = 0.0, 0.0
    for fc in validos:
        orig = originales[fc][0]
        m7 = demo_min[fc] if crudo else _estirado(demo_min[fc], 7)
        m8 = demo_ri[fc] if crudo else _estirado(demo_ri[fc], 8)
        dif_min = max(dif_min, float(np.max(np.abs(m7 - orig[7]))))
        dif_ri = max(dif_ri, float(np.max(np.abs(m8 - orig[8]))))
    check("[B] ch7 (mineria demo) replica el parche original", dif_min <= TOL_FIDELIDAD,
          f"max_diff={dif_min:.3e} (tol {TOL_FIDELIDAD:g})")
    check("[B] ch8 (rios demo) replica el parche original", dif_ri <= TOL_FIDELIDAD,
          f"max_diff={dif_ri:.3e} (tol {TOL_FIDELIDAD:g})")
    if FALLAS:
        print("\n[FAIL] Fidelidad rota: NO se sube nada (diagnosticar el recorte).")
        return 1

    print("\n[A] Diferencia demo -> real por parche (canal estirado)...")
    diffs = {}
    for fc in validos:
        dm = float(np.mean(np.abs(
            _estirado(real_min[fc], 7) - _estirado(demo_min[fc], 7))))
        dr = float(np.mean(np.abs(
            _estirado(real_ri[fc], 8) - _estirado(demo_ri[fc], 8))))
        diffs[fc] = (dm, dr)
    n_cambian = sum(1 for dm, dr in diffs.values() if max(dm, dr) > 1e-3)
    check("[A] las capas reales alteran canales frente a la demo",
          n_cambian > 0, f"{n_cambian}/{len(diffs)} candidatos con diff>1e-3")
    if n_cambian == 0:
        return 1

    print("\n[A] Construyendo tensores contrato v10 (ch6-8 en [-1,1], "
          "ch7/ch8 = capas REALES)...")
    tensores = {fc: _tensor_v10(originales[fc], real_min[fc], real_ri[fc], crudo)
                for fc in validos}

    if args.seleccion == "modelo":
        print("\n[A] Senal local (MCD x20) para elegir parches no saturados...")
        ranking = _ranking_local(tensores)
        for fc, p, m in ranking[:8]:
            print(f"  {fc}: prob_media={p:.6f} mask_frac={m:.4f}")
        mejor = ranking[0][1]
        check("[A] senal local no saturada (prob media >= 1e-6)",
              mejor >= 1e-6, f"mejor={mejor:.3e}")
        if mejor < 1e-6:
            print("  -> todos saturan a 0: amplia --candidatos y reintenta.")
            return 1
        seleccion = [fc for fc, p, m in ranking[:args.top]]
        print(f"  seleccion (top {args.top} por prob local): {seleccion}")
    else:
        sel7 = max(diffs, key=lambda k: diffs[k][0])
        sel8 = max(diffs, key=lambda k: diffs[k][1])
        if sel8 == sel7 and len(diffs) > 1:
            sel8 = max((k for k in diffs if k != sel7), key=lambda k: diffs[k][1])
        seleccion = sorted({sel7, sel8})
        print(f"  seleccion (diff demo->real): ch7={sel7} (diff {diffs[sel7][0]:.4f})  "
              f"ch8={sel8} (diff {diffs[sel8][1]:.4f})")

    if args.no_subir:
        print("\n(--no-subir: se omite la subida)")
        return 0

    print("\n[A] Subiendo tensores con capas REALES a S3...")
    subidas = []
    for fc in seleccion:
        arr = tensores[fc]
        key = f"{PRUEBA_PREFIX}parche_{fc[0]}_{fc[1]}.npy"
        buf = io.BytesIO()
        np.save(buf, arr)
        buf.seek(0)
        s3.put_object(Bucket=bucket, Key=key, Body=buf.read(),
                      ContentType="application/x-npy")
        resumen = ", ".join(
            f"ch{i}: [{float(arr[0, i].min()):.3f}, {float(arr[0, i].max()):.3f}] "
            f"mean={float(arr[0, i].mean()):.3f}"
            for i in (6, 7, 8)
        )
        print(f"  [OK] s3://{bucket}/{key}\n       {resumen}")
        subidas.append((fc, key))

    print("\nURIs para el smoke (29) desde el contenedor web:")
    for fc, key in subidas:
        print(f"  s3://{bucket}/{key}   (parche {fc[0]},{fc[1]})")
    return 0


def comparar(s3, bucket, args):
    print("=" * 70)
    print(" APU GUARD - E2E capas REALES: endpoint vs forward local")
    print("=" * 70)

    if not args.parche:
        print("[FAIL] --comparar requiere --parche f,c")
        return 1
    f, c = (int(x) for x in args.parche.split(","))

    if not args.comparar.startswith("s3://"):
        print(f"[FAIL] --comparar requiere una URI s3:// (recibido: {args.comparar})")
        return 1
    b_in, k_in = args.comparar[5:].split("/", 1)
    obj = s3.get_object(Bucket=b_in, Key=k_in)
    npz = np.load(io.BytesIO(obj["Body"].read()))
    prob_r = np.asarray(npz["probability"], dtype=np.float64).squeeze()
    mask_r = np.asarray(npz["mask"], dtype=np.float64).squeeze()
    print(f"Endpoint: s3://{b_in}/{k_in} ({obj['ContentLength']} B)")
    print(f"  prob mean={prob_r.mean():.6f}  mask>0={int((mask_r > 0).sum())}/{mask_r.size}")

    key_npy = f"{PRUEBA_PREFIX}parche_{f}_{c}.npy"
    arr = _descargar_npy(s3, bucket, key_npy)
    if arr is None:
        print(f"[FAIL] no se pudo descargar s3://{bucket}/{key_npy}")
        return 1

    print("\nForward local MCD x20 (model_source/inference.py + seed42)...")
    sys.path.insert(0, str(MODEL_SOURCE))
    import torch
    import inference as inf
    model = inf.model_fn(str(ENTREGA_CKPTS))
    out = inf.predict_fn(torch.from_numpy(arr).float(), model)
    prob_l = np.asarray(out["probability"], dtype=np.float64).squeeze()
    mask_l = np.asarray(out["mask"], dtype=np.float64).squeeze()
    print(f"  local: prob mean={prob_l.mean():.6f}  mask>0={int((mask_l > 0).sum())}/{mask_l.size}")

    corr = float(np.corrcoef(prob_l.ravel(), prob_r.ravel())[0, 1])
    ratio = float(prob_r.mean() / max(prob_l.mean(), 1e-12))
    dmasc = abs(float(mask_l.mean()) - float(mask_r.mean()))
    print("\n[COMPARACION]")
    print(f"  corr(prob local, prob endpoint) = {corr:.6f}")
    print(f"  ratio means (endpoint/local)     = {ratio:.6f}")
    print(f"  |diff fraccion mask>0|           = {dmasc:.6f}")

    check("[C] correlacion >= 0.95", corr >= 0.95, f"{corr:.4f}")
    check("[C] ratio de medias en [0.8, 1.25]", 0.8 <= ratio <= 1.25, f"{ratio:.4f}")
    check("[C] fraccion de mascara coincidente (<= 0.05)", dmasc <= 0.05, f"{dmasc:.4f}")

    print()
    for a in AVISOS:
        print(f"  Aviso: {a}")
    print("-" * 70)
    if FALLAS:
        print(f"RESULTADO: FALLA ({len(FALLAS)}): {FALLAS}")
        return 1
    print("RESULTADO: PASA")
    return 0


def main():
    parser = argparse.ArgumentParser(description="E2E capas estaticas reales")
    parser.add_argument("--candidatos", type=int, default=150,
                        help="candidatos de la grilla (def. 150)")
    parser.add_argument("--seleccion", choices=("modelo", "diff"), default="modelo",
                        help="criterio de seleccion: 'modelo' elige por senal "
                             "local no saturada (def); 'diff' por mayor "
                             "cambio demo->real")
    parser.add_argument("--top", type=int, default=2,
                        help="parches a subir con --seleccion modelo (def. 2)")
    parser.add_argument("--parches", nargs="+",
                        help="parches concretos f,c (omite autoseleccion)")
    parser.add_argument("--composite", default=COMPOSITE_DEFECTO,
                        help="key del raw-raster del composite")
    parser.add_argument("--semilla", type=int, default=42)
    parser.add_argument("--no-subir", action="store_true",
                        help="genera y valida sin subir a S3")
    parser.add_argument("--comparar", help="URI s3:// del .npz del endpoint")
    parser.add_argument("--parche", help="f,c del parche (con --comparar)")
    args = parser.parse_args()

    region, bucket, origen = cargar_config()
    print(f"Configuracion: {origen} | region={region} | bucket={bucket}")
    s3 = boto3.client("s3", region_name=region)

    if args.comparar:
        rc = comparar(s3, bucket, args)
    else:
        rc = generar(s3, bucket, args)
        if rc == 0 and not args.no_subir:
            print("\nSiguiente paso: endpoint a >=1 instancia y, en el")
            print("contenedor web: python /app/scripts/29_invocar_endpoint_prueba.py "
                  "s3://.../prueba_layers/parche_X_Y.npy")
    print("=" * 70)
    return rc


if __name__ == "__main__":
    sys.exit(main())
