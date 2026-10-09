"""
09_parches_procesados.py
=========================
Cruza la base de datos (ParcheProcesamiento) con S3 para identificar:
  - Parches en BD marcados PROCESADO pero sin archivo de output en S3
  - Archivos de output en S3 (.out o .npz) sin parche PROCESADO en BD
  - Resumen de consistencia

Nota importante sobre los outputs de SageMaker:
  - SageMaker Async deposita los outputs como .out (UUID) directamente
    en sagemaker-outputs/, SIN estructura de subcarpetas.
  - El codigo original asumia .npz con prefijo sagemaker-outputs/captura_X/,
    lo cual no coincide con la realidad.

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/09_parches_procesados.py
"""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _template_python import setup, get_s3, BUCKET, S3_PREFIX_SAGEMAKER_OUT
setup()

import django
django.setup()

from core.models import ParcheProcesamiento


# Extensiones validas para outputs de SageMaker Async.
# .out es el formato real (UUID); .npz se conserva por compatibilidad legacy.
SAGEMAKER_OUTPUT_EXTENSIONS = (".out", ".npz")


def obtener_outputs_en_s3(s3):
    """
    Devuelve set de keys de outputs de SageMaker en todo el prefijo
    sagemaker-outputs/. Detecta tanto .out (formato real) como .npz.

    Los outputs NO se organizan por captura en S3 (SageMaker usa UUIDs planos).
    """
    keys = set()
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=S3_PREFIX_SAGEMAKER_OUT):
        for obj in page.get("Contents", []):
            if obj["Key"].lower().endswith(SAGEMAKER_OUTPUT_EXTENSIONS):
                keys.add(obj["Key"])
    return keys


def key_de_bd(parche):
    """Convierte s3_path_resultado (s3://bucket/key) a key relativa (key/)."""
    if not parche.s3_path_resultado:
        return None
    path = parche.s3_path_resultado.replace("s3://", "")
    prefix = f"{BUCKET}/"
    if path.startswith(prefix):
        return path[len(prefix):]
    return path


def main():
    s3 = get_s3()
    print("=" * 70)
    print(" APU GUARD - Consistencia BD <-> S3 (parches procesados)")
    print("=" * 70)
    print(f"Bucket: {BUCKET}")
    print(f"Prefijo: {S3_PREFIX_SAGEMAKER_OUT}")
    print(f"Extensiones validas: {', '.join(SAGEMAKER_OUTPUT_EXTENSIONS)}")
    print()

    # Total parches en BD
    parches = ParcheProcesamiento.objects.all()
    n_total = parches.count()
    if n_total == 0:
        print("[INFO] No hay parches en la base de datos.")
        print("       Ejecuta primero 04_lanzar_quincena.py para generar parches.")
        return 0

    # Listar todos los outputs de S3 una sola vez
    outputs_s3 = obtener_outputs_en_s3(s3)
    print(f"Outputs en S3 (sagemaker-outputs/): {len(outputs_s3)}")
    print(f"Parches en BD: {n_total}")
    print()

    # Agrupar por captura
    capturas = sorted(set(p.captura_id for p in parches))
    consistentes    = 0
    huerfanos_bd    = []   # en BD PROCESADO pero sin output en S3
    huerfanos_s3    = []   # output en S3 sin parche PROCESADO en BD
    errores         = 0

    for cap in capturas:
        parches_cap = parches.filter(captura_id=cap)

        bd_procesados = {
            key_de_bd(p): p
            for p in parches_cap
            if p.estado_sagemaker == "PROCESADO" and p.s3_path_resultado
        }
        bd_pendientes    = parches_cap.filter(estado_sagemaker="PENDIENTE").count()
        bd_procesados_n  = len(bd_procesados)
        bd_errores       = parches_cap.filter(estado_sagemaker="ERROR").count()

        # Detectar inconsistencias por key directa
        solo_en_bd = []
        for key, parche in bd_procesados.items():
            if key not in outputs_s3:
                solo_en_bd.append((parche.pk, key))

        consistentes += bd_procesados_n - len(solo_en_bd)
        huerfanos_bd.extend([(cap, pk, k) for pk, k in solo_en_bd])

        print(f"  Captura {cap}:")
        print(f"    BD: PENDIENTE={bd_pendientes}  PROCESADO={bd_procesados_n}  ERROR={bd_errores}")
        if solo_en_bd:
            print(f"    [!] En BD PROCESADO pero SIN output en S3: {len(solo_en_bd)}")
            for pk, k in solo_en_bd[:5]:
                print(f"        - parche {pk}: {k}")
            if len(solo_en_bd) > 5:
                print(f"        ... y {len(solo_en_bd) - 5} mas")
        else:
            print(f"    [OK] Todos los PROCESADO tienen su output en S3.")

    # Outputs huerfanos en S3: keys que no estan asociadas a ningun parche PROCESADO
    bd_todas_keys = set()
    for p in parches:
        k = key_de_bd(p)
        if k:
            bd_todas_keys.add(k)

    huerfanos_s3_all = outputs_s3 - bd_todas_keys
    # Filtrar para no reportar archivos muy antiguos (probablemente de otras capturas)
    # Solo reportar los mas recientes si hay muchos
    if len(huerfanos_s3_all) > 50:
        print(f"\n  [i] Outputs en S3 sin parche asociado: {len(huerfanos_s3_all)} (posiblemente de otras capturas o antiguos)")

    print("\n" + "-" * 70)
    print("RESUMEN GLOBAL")
    print("-" * 70)
    print(f"  Parches consistentes (BD PROCESADO == S3): {consistentes}")
    print(f"  Parches PROCESADO en BD sin output S3:    {len(huerfanos_bd)}")
    if huerfanos_s3_all and len(huerfanos_s3_all) <= 50:
        print(f"  Outputs en S3 sin parche PROCESADO:      {len(huerfanos_s3_all)}")
    print("=" * 70)

    if huerfanos_bd:
        print("\nAccion sugerida: ejecuta 14_generar_visualizaciones_historicas.sh")
        print("  para regenerar outputs y PNGs, o revisa si SageMaker Async esta fallando.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
