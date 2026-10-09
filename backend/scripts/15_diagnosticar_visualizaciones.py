"""
15_diagnosticar_visualizaciones.py
===================================
Reporta cuantos parches PROCESADO en BD tienen (o no tienen) sus
PNGs correspondientes en sagemaker-visualizations/.

Uso (dentro del contenedor web):
    docker compose exec web python /app/scripts/15_diagnosticar_visualizaciones.py
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _template_python import setup, get_s3, BUCKET
setup()

import django
django.setup()

from core.models import ParcheProcesamiento


def existe_png(s3, key):
    try:
        s3.head_object(Bucket=BUCKET, Key=key)
        return True
    except Exception:
        return False


def main():
    s3 = get_s3()
    parches = ParcheProcesamiento.objects.filter(estado_sagemaker="PROCESADO")
    total = parches.count()

    print("=" * 70)
    print(" APU GUARD - Diagnostico de visualizaciones")
    print("=" * 70)
    print(f"Bucket: {BUCKET}")
    print(f"Prefijo: sagemaker-visualizations/")
    print("")

    if total == 0:
        print("[INFO] No hay parches PROCESADO en la BD.")
        print("       Lanza el pipeline (04_lanzar_quincena) y espera resultados.")
        return 0

    con_rgb  = 0
    sin_rgb  = 0
    con_mask = 0
    sin_mask = 0
    listados = []

    for p in parches.iterator():
        base = f"sagemaker-visualizations/captura_{p.captura_id}/parche_{p.fila_idx}_{p.col_idx}"
        key_rgb  = f"{base}_rgb.png"
        key_mask = f"{base}_mask.png"

        rgb_ok  = existe_png(s3, key_rgb)
        mask_ok = existe_png(s3, key_mask)

        if rgb_ok:  con_rgb  += 1
        else:       sin_rgb  += 1
        if mask_ok: con_mask += 1
        else:       sin_mask += 1

        if not rgb_ok or not mask_ok:
            listados.append({
                "captura_id": p.captura_id,
                "fila":       p.fila_idx,
                "col":        p.col_idx,
                "rgb_ok":     rgb_ok,
                "mask_ok":    mask_ok,
            })

    pct_rgb  = (con_rgb  / total) * 100 if total else 0
    pct_mask = (con_mask / total) * 100 if total else 0
    print(f"Total parches PROCESADO:  {total}")
    print(f"")
    print(f"  Con _rgb.png:   {con_rgb:>5} / {total}  ({pct_rgb:5.1f}%)")
    print(f"  Sin _rgb.png:   {sin_rgb:>5} / {total}")
    print(f"  Con _mask.png:  {con_mask:>5} / {total}  ({pct_mask:5.1f}%)")
    print(f"  Sin _mask.png:  {sin_mask:>5} / {total}")
    print("")

    if sin_rgb == 0 and sin_mask == 0:
        print("[OK] Todas las visualizaciones estan generadas.")
    else:
        print(f"[WARN] {max(sin_rgb, sin_mask)} parches sin visualizacion.")
        print("       Ejecuta 14_generar_visualizaciones_historicas.py para backfill.")
        print("")
        if listados:
            print("Primeros 10 parches faltantes:")
            for item in listados[:10]:
                rgb_str  = "RGB OK"  if item["rgb_ok"]  else "rgb NO"
                mask_str = "mask OK" if item["mask_ok"] else "mask NO"
                print(f"  captura={item['captura_id']} parche=[{item['fila']},{item['col']}]  {rgb_str}  {mask_str}")
            if len(listados) > 10:
                print(f"  ... y {len(listados) - 10} mas")

    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
