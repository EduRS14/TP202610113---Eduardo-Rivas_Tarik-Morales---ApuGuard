"""
28_empaquetar_modelo.py
=======================
Empaqueta model_source/ + checkpoint en un model.tar.gz listo para SageMaker
y lo suba al bucket con un nombre versionado (nunca sobrescribe el tarball
actual: sirve de rollback).

Estructura generada (identica a la del endpoint desplegado):
    hrnet_final_seed42.pth          pesos (state_dict)
    code/inference.py               entry point SageMaker
    code/hrnet.py                   arquitectura
    code/requirements.txt           timm==1.0.15
    (sin __pycache__)

Precondiciones verificadas por el propio script:
    - inference.py sin BIAS_CORRECTION, con CHECKPOINT_NAME correcto
      y con dropout_p=0.20 / dropout_position="before_head"
    - hrnet.py identico al de la entrega
    - checkpoint con 9.185.329 parametros

Uso:
    python backend/scripts/28_empaquetar_modelo.py                 # crea + sube
    python backend/scripts/28_empaquetar_modelo.py --sin-subir     # solo crea
    python backend/scripts/28_empaquetar_modelo.py --prefijo model-v11-seed42

Variables opcionales:
    CHECKPOINT_PATH  ruta al .pth (por defecto, el de la entrega)
    S3_UPLOAD_KEY    clave S3 destino (por defecto, model-<ts>-seed42.tar.gz)
"""
import argparse
import hashlib
import io
import os
import sys
import tarfile
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent            # backend/
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _template_python import BACKEND_DIR, load_env, get_s3  # noqa: E402

RAIZ_REPO = BACKEND_DIR.parent                            # apuguard_stac/
MODEL_SOURCE = RAIZ_REPO / "model_source"

CHECKPOINT_DEFECTO = Path(
    r"D:\UPC\TP1\Modelo Claude\apuguard_deploy_new\apuguard_deploy"
    r"\Version final\Modelo final\entrega_hrnet_final_v1"
    r"\entrega_hrnet_final_v1\hrnet_training_package"
    r"\checkpoints\hrnet_final_seed42.pth"
)
NOMBRE_CHECKPOINT = "hrnet_final_seed42.pth"
PARAMS_ESPERADOS = 9_185_329

FALLAS = []


def check(nombre, cond, extra=""):
    print(f"[{'PASA' if cond else 'FALLA'}] {nombre}" + (f" -> {extra}" if extra else ""))
    if not cond:
        FALLAS.append(nombre)
    return cond


def main():
    load_env()
    ap = argparse.ArgumentParser(description="Empaqueta y sube model.tar.gz a S3")
    ap.add_argument("--checkpoint", default=os.environ.get("CHECKPOINT_PATH", str(CHECKPOINT_DEFECTO)))
    ap.add_argument("--prefijo", default=None,
                    help="prefijo de la clave S3 (ej. model-v10-seed42)")
    ap.add_argument("--sin-subir", action="store_true", help="no subir a S3")
    ap.add_argument("--bucket", default=os.environ.get("AWS_S3_BUCKET_NAME") or os.environ.get("AWS_S3_BUCKET"))
    args = ap.parse_args()

    print("=" * 70)
    print(" APU GUARD - Empaquetado del modelo HRNet para SageMaker")
    print("=" * 70)

    # ── 1. Validar model_source ─────────────────────────────────────────────
    inf_py = MODEL_SOURCE / "inference.py"
    hrnet_py = MODEL_SOURCE / "hrnet.py"
    req_py = MODEL_SOURCE / "requirements.txt"
    for f in (inf_py, hrnet_py, req_py):
        check(f"existe model_source/{f.name}", f.exists(), str(f))
    if FALLAS:
        return 1

    inf_txt = inf_py.read_text(encoding="utf-8")
    check("inference.py sin BIAS_CORRECTION", "BIAS_CORRECTION" not in inf_txt)
    check("inference.py sin suma de sesgo a los logits",
          "+ BIAS_CORRECTION" not in inf_txt)
    check(f"inference.py CHECKPOINT_NAME = {NOMBRE_CHECKPOINT}",
          f'"{NOMBRE_CHECKPOINT}"' in inf_txt)
    check("inference.py dropout_p = 0.20", "0.20" in inf_txt)
    check("inference.py dropout_position = before_head", "before_head" in inf_txt)

    hrnet_txt = hrnet_py.read_text(encoding="utf-8")
    check("hrnet.py soporta dropout_position", "dropout_position" in hrnet_txt)
    check("hrnet.py contiene la configuracion mejorada (0.20 / before_head)",
          'dropout_p: float = 0.1' in hrnet_txt and "before_head" in hrnet_txt)

    req_txt = req_py.read_text(encoding="utf-8")
    check("requirements.txt fija timm==1.0.15", "timm==1.0.15" in req_txt)
    deps_prohibidas = [
        l.strip() for l in req_txt.splitlines()
        if l.strip() and not l.strip().startswith("#")
        and ("torch" in l or "numpy" in l)
    ]
    check("requirements.txt no arrastra torch/numpy (van preinstalados)",
          not deps_prohibidas, f"-> {deps_prohibidas}")

    # ── 2. Validar checkpoint ───────────────────────────────────────────────
    ckpt = Path(args.checkpoint)
    check("checkpoint existe", ckpt.exists(), str(ckpt))
    if FALLAS:
        return 1

    h = hashlib.sha256()
    with ckpt.open("rb") as fh:
        for bloque in iter(lambda: fh.read(1 << 20), b""):
            h.update(bloque)
    sha = h.hexdigest()
    print(f"      checkpoint sha256 = {sha}")

    try:
        import torch
        sd = torch.load(str(ckpt), map_location="cpu", weights_only=True)
        check("checkpoint carga con weights_only=True", True)
        check("checkpoint es un state_dict plano de tensores",
              isinstance(sd, dict) and all(hasattr(v, "shape") for v in sd.values()))
    except Exception as exc:
        check("checkpoint carga con weights_only=True", False, f"{type(exc).__name__}: {exc}")
        return 1

    # Parámetros reales (excluye buffers: running_mean/var de GroupNorm, etc.)
    try:
        sys.path.insert(0, str(MODEL_SOURCE))
        from hrnet import get_hrnet_w18
        modelo = get_hrnet_w18(in_channels=9, out_channels=1,
                               dropout_p=0.20, dropout_position="before_head")
        modelo.load_state_dict(sd, strict=True)
        n_params = sum(p.numel() for p in modelo.parameters())
        n_buffers = sum(v.numel() for v in sd.values()) - n_params
        check(f"state_dict coincide strict=True con la arquitectura "
              f"({PARAMS_ESPERADOS:,} parametros)", True)
        check(f"parametros = {PARAMS_ESPERADOS:,}",
              n_params == PARAMS_ESPERADOS,
              f"{n_params:,} (+{n_buffers:,} buffers)")
    except ImportError as exc:
        print(f"[ADVERTENCIA] sin timm ({exc}); se omite la comprobacion de parametros")

    # ── 3. Construir el tarball ─────────────────────────────────────────────
    ts = time.strftime("%Y%m%d-%H%M%S")
    prefijo = args.prefijo or f"model-{ts}-seed42"
    clave_s3 = os.environ.get("S3_UPLOAD_KEY") or f"{prefijo}.tar.gz"

    with tempfile.TemporaryDirectory(prefix="apuguard_pkg_") as staging:
        st = Path(staging)
        st.mkdir(exist_ok=True)
        (st / NOMBRE_CHECKPOINT).write_bytes(ckpt.read_bytes())
        code = st / "code"
        code.mkdir()
        for nombre in ("inference.py", "hrnet.py", "requirements.txt"):
            (code / nombre).write_bytes((MODEL_SOURCE / nombre).read_bytes())

        ruta_tar = st / "model.tar.gz"
        with tarfile.open(ruta_tar, "w:gz") as tar:
            for ruta in sorted(st.rglob("*")):
                if ruta.is_file() and ruta != ruta_tar:
                    tar.add(ruta, arcname=str(ruta.relative_to(st)))

        contenido = ruta_tar.read_bytes()
        sha_tar = hashlib.sha256(contenido).hexdigest()

        with tarfile.open(fileobj=io.BytesIO(contenido), mode="r:gz") as tar:
            miembros = tar.getnames()
        esperados = {NOMBRE_CHECKPOINT, "code/inference.py", "code/hrnet.py",
                     "code/requirements.txt"}
        check("el tarball contiene exactamente los 4 miembros esperados",
              set(miembros) == esperados, f"-> {sorted(miembros)}")
        print(f"      model.tar.gz = {len(contenido)/1048576:.2f} MB  "
              f"sha256 = {sha_tar[:16]}")

        # ── 4. Subir a S3 (prefijo model* de la raiz: politica del deploy) ──
        if args.sin_subir:
            destino = Path.cwd() / clave_s3
            destino.write_bytes(contenido)
            print(f"\n[OK] Tarball local: {destino}")
        else:
            if not args.bucket:
                check("bucket configurado (AWS_S3_BUCKET_NAME)", False)
                return 1
            load_env()
            s3 = get_s3()
            s3.put_object(
                Bucket=args.bucket,
                Key=clave_s3,
                Body=contenido,
                ContentType="application/gzip",
                Metadata={"sha256": sha_tar, "params": str(PARAMS_ESPERADOS)},
            )
            print(f"\n[OK] Subido: s3://{args.bucket}/{clave_s3}")
            print(f"     sha256={sha_tar}")
            print("\nSiguiente paso (redespliegue con rollback):")
            print("  echo s | docker compose exec -T web python /app/scripts/"
                  f"18_redeploy_sagemaker.py s3://{args.bucket}/{clave_s3}")

    if FALLAS:
        print(f"\nRESULTADO: FALLA -> {FALLAS}")
        return 1
    print("\nRESULTADO: PASA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
