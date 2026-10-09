"""
29_invocar_endpoint_prueba.py
==============================
Invoca el endpoint SageMaker ASYNC con un parche .npy existente de
`sagemaker-inputs/`, espera el .npz de salida en S3 y muestra sus metricas
(probabilidad, mascara, entropia). Sirve para validar de extremo a extremo
sin pasar por `04_lanzar_quincena`.

NO modifica la BD: el resultado lo consume ademas el worker de escucha
(SQS->S3) si la cola esta activa; usa un parche cuyo caso ya exista para
que el pipeline deduplique en vez de crear registros nuevos.

Uso (dentro del contenedor web, que usa el rol de la instancia):
    python /app/scripts/29_invocar_endpoint_prueba.py
    python /app/scripts/29_invocar_endpoint_prueba.py s3://.../parche_0_50.npy --espera 420
"""
import argparse
import io
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _template_python import load_env


def cargar_config():
    """settings de Django si el entorno lo permite; si no, el .env directo."""
    try:
        from _template_python import setup
        setup()
        import django
        django.setup()
        from django.conf import settings
        return (settings.AWS_REGION_NAME, settings.AWS_SAGEMAKER_ENDPOINT_NAME,
                settings.AWS_S3_BUCKET_NAME, "Django")
    except Exception as exc:
        load_env()
        region = os.environ.get("AWS_REGION_NAME", "us-east-1")
        endpoint = os.environ.get("SAGEMAKER_ENDPOINT")
        bucket = os.environ.get("AWS_S3_BUCKET_NAME") or os.environ.get("AWS_S3_BUCKET")
        return region, endpoint, bucket, f"env local (.env, sin Django: {type(exc).__name__})"


import boto3
import numpy as np

DEFAULT_INPUT = "s3://apuguard-datalake-prod/sagemaker-inputs/captura_1/parche_0_50.npy"


def _encontrar_output(s3, bucket, key_base, t0):
    """Devuelve la key del objeto de salida o None si aun no existe."""
    for sufijo in ("", ".out", ".npz", ".npz.out"):
        try:
            s3.head_object(Bucket=bucket, Key=key_base + sufijo)
            return key_base + sufijo
        except Exception:
            pass
    try:
        resp = s3.list_objects_v2(Bucket=bucket, Prefix=key_base, MaxKeys=20)
    except Exception:
        return None
    for obj in resp.get("Contents", []):
        if obj["LastModified"].timestamp() >= t0 - 5:
            return obj["Key"]
    return None


def _imprimir_metricas(datos):
    print("\nClaves del .npz: " + ", ".join(sorted(datos.keys())))
    for nombre in sorted(datos.keys()):
        arr = datos[nombre]
        print(f"  {nombre}: shape={arr.shape} dtype={arr.dtype} "
              f"min={float(arr.min()):.4f} max={float(arr.max()):.4f} "
              f"mean={float(arr.mean()):.6f}")

    prob = np.asarray(datos["probability"], dtype=np.float64).squeeze()
    mask = np.asarray(datos["mask"], dtype=np.float64).squeeze()
    entr = np.asarray(datos["entropy"], dtype=np.float64).squeeze()

    pos_mask = int((mask > 0).sum())
    pos_prob = int((prob > 0.5).sum())
    total = mask.size
    print("\n[RESUMEN]")
    print(f"  pixeles mask>0          : {pos_mask}/{total} ({100*pos_mask/total:.2f}%)")
    print(f"  pixeles prob>0.5        : {pos_prob}/{total} ({100*pos_prob/total:.2f}%)")
    print(f"  prob media / p99        : {prob.mean():.6f} / {np.percentile(prob,99):.6f}")
    print(f"  entropia media / max    : {entr.mean():.6f} / {entr.max():.6f}")
    print(f"  score_confianza (1-e/ln2): {1 - entr.mean()/np.log(2):.6f}")

    ok = True
    if not (0.0 <= float(prob.min()) and float(prob.max()) <= 1.0):
        print("  [FAIL] probabilidad fuera de [0,1]")
        ok = False
    if float(prob.max()) <= 0.0:
        print("  [FAIL] probabilidad maxima = 0 (modelo no devuelve nada)")
        ok = False
    if float(entr.min()) < -1e-6 or float(entr.max()) > float(np.log(2)) + 1e-6:
        print("  [FAIL] entropia fuera de [0, ln2] (mas alla de ruido float)")
        ok = False
    if total != 128 * 128:
        print(f"  [FAIL] resolucion inesperada: {total} pixeles")
        ok = False
    print("  " + ("[OK] metricas coherentes" if ok else "[FAIL] metricas incoherentes"))
    return ok


def main():
    parser = argparse.ArgumentParser(description="Invoca endpoint async y resume la salida")
    parser.add_argument("input", nargs="?", default=DEFAULT_INPUT,
                        help="URI s3://.../parche_R_C.npy (por defecto captura_1/0_50)")
    parser.add_argument("--espera", type=int, default=420,
                        help="segundos maximos de espera del .npz (def. 420)")
    parser.add_argument("--normalizar", action="store_true",
                        help="aplica estirar_canales_distancia a ch6-8 del .npy "
                             "almacenado y lo reescribe (repara entradas "
                             "generadas con el contrato antiguo [0,1])")
    args = parser.parse_args()

    region, endpoint_name, bucket_cfg, origen = cargar_config()
    if not endpoint_name:
        print("[ERROR] No se pudo determinar el nombre del endpoint (SAGEMAKER_ENDPOINT).")
        return 1

    if not args.input.startswith("s3://") or "/" not in args.input[5:]:
        print(f"[ERROR] Input invalido: {args.input}")
        return 1
    bucket_in, key_in = args.input[5:].split("/", 1)

    sm = boto3.client("sagemaker-runtime", region_name=region)
    s3 = boto3.client("s3", region_name=region)
    print(f"Configuracion cargada desde: {origen}")
    print(f"  region={region}  endpoint={endpoint_name}")
    print(f"  input = {args.input}")

    if args.normalizar:
        from ml_engine.preprocessing import estirar_canales_distancia
        obj = s3.get_object(Bucket=bucket_in, Key=key_in)
        arr = np.load(io.BytesIO(obj["Body"].read()))
        if arr.ndim != 4 or arr.shape[1] != 9:
            print(f"[FAIL] forma inesperada del tensor: {arr.shape}")
            return 1
        print("\n[NORMALIZAR] ch6-8 ANTES (distancia cruda esperada en [0,1]):")
        for i in (6, 7, 8):
            print(f"  ch{i}: min={float(arr[0, i].min()):.5f} "
                  f"max={float(arr[0, i].max()):.5f} "
                  f"mean={float(arr[0, i].mean()):.5f}")
        if float(arr[0, 6:9].min()) < 0.0:
            print("  -> ya estan en [-1,1]: no se vuelve a estirar")
        else:
            estirar_canales_distancia(arr[0])
            buf = io.BytesIO()
            np.save(buf, arr)
            buf.seek(0)
            s3.put_object(Bucket=bucket_in, Key=key_in, Body=buf.read(),
                          ContentType="application/x-npy")
            print("[NORMALIZAR] ch6-8 DESPUES (contrato nuevo, [-1,1]):")
            for i in (6, 7, 8):
                print(f"  ch{i}: min={float(arr[0, i].min()):.5f} "
                      f"max={float(arr[0, i].max()):.5f} "
                      f"mean={float(arr[0, i].mean()):.5f}")
            print(f"  [OK] tensor reescrito en {args.input}")

    t0 = time.time()
    try:
        resp = sm.invoke_endpoint_async(
            EndpointName=endpoint_name,
            InputLocation=args.input,
            ContentType="application/x-npy",
            Accept="application/x-npz",
            InvocationTimeoutSeconds=120,
            InferenceId=f"prueba_{int(t0)}",
        )
    except Exception as exc:
        print(f"[FAIL] invoke_endpoint_async: {type(exc).__name__}: {exc}")
        return 1

    output_loc = resp.get("OutputLocation", "")
    print(f"  [OK] invocado. InferenceId={resp.get('InferenceId','')} "
          f"OutputLocation={output_loc}")

    key_base = output_loc[5:].split("/", 1)[1] if output_loc.startswith("s3://") and "/" in output_loc[5:] else key_in

    print(f"\nEsperando salida (max {args.espera}s)...")
    key_out = None
    while time.time() - t0 < args.espera:
        key_out = _encontrar_output(s3, bucket_in, key_base, t0)
        if key_out:
            break
        time.sleep(10)
    if not key_out:
        print(f"[FAIL] sin salida tras {int(time.time()-t0)}s (prefijo {key_base})")
        return 1

    objeto = s3.get_object(Bucket=bucket_in, Key=key_out)
    datos = np.load(io.BytesIO(objeto["Body"].read()))
    print(f"[OK] salida: s3://{bucket_in}/{key_out} "
          f"({int(time.time()-t0)}s desde la invocacion, "
          f"{objeto['ContentLength']} B)")
    ok = _imprimir_metricas(datos)
    print("\n" + "=" * 70)
    print("RESULTADO: " + ("PASA" if ok else "FALLA"))
    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
