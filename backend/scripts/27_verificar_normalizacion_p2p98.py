"""
27_verificar_normalizacion_p2p98.py
====================================
Verifica el contrato de normalizacion de canales ch6-8 (distancias) entre
el backend de produccion y la entrega del modelo HRNet final.

Comprobaciones:
  [1] Constantes P2_P98_CH6_8 de preprocessing.py == normalization_stats.json
      de la entrega (bit a bit).
  [2] estirar_canal_distancia (numpy) == normalize_channel (torch, entrega):
      max diff en parches sinteticos y en el limite del clip.
  [3] Propiedades: p2 -> -1, p98 -> +1, rango [-1,1], monotonía, NaN,
      float32, operacion in-place.
  [4] estirar_canales_distancia toca SOLO los canales 6-8 de un tensor [9,H,W].
  [5] apilar_tensor entrega ch6-8 ya en [-1,1].
  [6] Parches reales de la entrega: ch6-8 dentro de [-1,1] (muestra) y
      round-trip inverso estable.
  [7] ml_engine/tasks.py aplica estirar_canales_distancia antes del tiling.

Uso local (sin Django):
    python backend/scripts/27_verificar_normalizacion_p2p98.py

Uso en el contenedor:
    docker compose exec web python /app/scripts/27_verificar_normalizacion_p2p98.py

Variables opcionales:
    ENTREGA_DIR   ruta al paquete de la entrega (hrnet_training_package)
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent          # backend/
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from _template_python import setup, BACKEND_DIR
    setup()
    ENTORNO = "con Django"
except Exception as exc:                                # pragma: no cover
    from _template_python import BACKEND_DIR
    sys.path.insert(0, str(BACKEND_DIR))
    ENTORNO = f"sin Django ({type(exc).__name__})"

import numpy as np

from ml_engine.preprocessing import (
    P2_P98_CH6_8, apilar_tensor, estirar_canales_distancia,
    estirar_canal_distancia,
)

ENTREGA_DIR = Path(
    os.environ.get(
        "ENTREGA_DIR",
        r"D:\UPC\TP1\Modelo Claude\apuguard_deploy_new\apuguard_deploy"
        r"\Version final\Modelo final\entrega_hrnet_final_v1"
        r"\entrega_hrnet_final_v1\hrnet_training_package",
    )
)
STATS_JSON = ENTREGA_DIR / "dataset_pipeline" / "data" / "processed_acumulativo" / "normalization_stats.json"
REPROCESS_PY = ENTREGA_DIR / "dataset_pipeline" / "src" / "reprocess_normalization.py"

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


def main():
    print("=" * 70)
    print(" APU GUARD - Verificacion de normalizacion P2-P98 (ch6-8)")
    print("=" * 70)
    print(f"Entorno: {ENTORNO}")
    print(f"Entrega: {ENTREGA_DIR} (existe={ENTREGA_DIR.exists()})")
    print()

    # [1] Constantes == normalization_stats.json -----------------------------
    if STATS_JSON.exists():
        stats = json.loads(STATS_JSON.read_text(encoding="utf-8"))
        check("[1] method del JSON es minmax_p2_p98_to_neg1_1",
              stats.get("method") == "minmax_p2_p98_to_neg1_1",
              f"json={stats.get('method')!r}")
        check("[1] total_patches_processed == 12576 (dataset completo)",
              stats.get("total_patches_processed") == 12576,
              f"json={stats.get('total_patches_processed')!r}")
        ok_c = True
        for i, canal in enumerate(("6", "7", "8")):
            p2_json = stats["channels"][canal]["p2"]
            p98_json = stats["channels"][canal]["p98"]
            p2_py, p98_py = P2_P98_CH6_8[i]
            mismo = (p2_json == p2_py) and (p98_json == p98_py)
            ok_c = ok_c and mismo
            if not mismo:
                print(f"    ch{canal}: json=({p2_json!r}, {p98_json!r}) "
                      f"py=({p2_py!r}, {p98_py!r})")
        check("[1] constantes P2_P98_CH6_8 identicas al JSON de la entrega", ok_c)
    else:
        aviso("[1] normalization_stats.json no disponible",
              "define ENTREGA_DIR para comparar constantes")

    # [2] Paridad numpy vs torch de la entrega -------------------------------
    rng = np.random.default_rng(42)
    try:
        import torch
    except Exception:
        torch = None
    if torch is None:
        aviso("[2] paridad numpy vs torch",
              "torch no instalado en este entorno: comprobacion omitida")
    else:
        if REPROCESS_PY.exists():
            spec = importlib.util.spec_from_file_location(
                "reprocess_normalization_entrega", REPROCESS_PY
            )
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            normalize_channel_torch = mod.normalize_channel
        else:
            def normalize_channel_torch(x, p2, p98):    # copia literal de la entrega
                denom = p98 - p2
                if denom < 1e-10:
                    denom = 1e-10
                return torch.clamp(2.0 * (x - p2) / denom - 1.0, -1.0, 1.0)
            aviso("[2] reprocess_normalization.py no disponible",
                  "se usa la copia literal de la formula")

        rng = np.random.default_rng(42)
        casos = [
            rng.random((7, 11), dtype=np.float32),
            np.full((5, 5), 0.5, dtype=np.float32),
            np.array([[0.0, 1.0, 0.3]], dtype=np.float32),
            np.array([[0.04624843, 0.0, 0.0917]], dtype=np.float32),  # dentro del rango p2-p98 ch6
            np.full((3, 3), np.nan, dtype=np.float32),
        ]
        max_dif = 0.0
        for idx, (p2, p98) in enumerate(P2_P98_CH6_8):
            for caso in casos:
                entrada = caso.copy()
                nuestra = estirar_canal_distancia(entrada.copy(), p2, p98)
                with torch.no_grad():
                    suya = normalize_channel_torch(
                        torch.from_numpy(caso.copy()), p2, p98
                    ).numpy()
                iguales = np.allclose(nuestra, suya, rtol=0, atol=1e-6, equal_nan=True)
                max_dif = max(max_dif, (float(np.nanmax(np.abs(nuestra - suya))) if not np.isnan(nuestra - suya).all() else 0.0))
                if not iguales:
                    FALLAS.append(f"[2] paridad ch{idx+6}")
        check("[2] estirar_canal_distancia (numpy) == normalize_channel (torch)",
              not any(f.startswith("[2]") for f in FALLAS),
              f"max_diff={max_dif:.3e}")

    # [3] Propiedades --------------------------------------------------------
    p2, p98 = P2_P98_CH6_8[0]
    base = np.array([[p2, p98, (p2 + p98) / 2, -1.0, 2.0, np.nan]], dtype=np.float32)
    out = estirar_canal_distancia(base.copy(), p2, p98)
    check("[3] p2 -> -1 y p98 -> +1",
          np.isclose(out[0, 0], -1.0) and np.isclose(out[0, 1], 1.0),
          f"{out[0,0]:.4f} / {out[0,1]:.4f}")
    check("[3] valores fuera del rango recortados a [-1, 1]",
          out[0, 3] == -1.0 and out[0, 4] == 1.0)
    check("[3] punto medio -> 0", np.isclose(out[0, 2], 0.0, atol=1e-6),
          f"{out[0,2]:.6f}")
    check("[3] NaN se conservan", np.isnan(out[0, 5]))
    check("[3] salida float32", out.dtype == np.float32, f"{out.dtype}")
    check("[3] operacion in-place (mismo objeto)",
          estirar_canal_distancia(base, p2, p98) is base)
    mono = np.all(np.diff(estirar_canal_distancia(
        np.sort(rng.random((50,), dtype=np.float32)), p2, p98)) >= 0)
    check("[3] transformacion monotonamente creciente", mono)

    # [4] Sólo ch6-8 ---------------------------------------------------------
    tensor = rng.random((9, 32, 32), dtype=np.float32).astype(np.float32)
    antes = tensor.copy()
    estirar_canales_distancia(tensor)
    check("[4] canales 0-5 intactos",
          np.array_equal(tensor[:6], antes[:6]))
    check("[4] canales 6-8 transformados (en [-1, 1])",
          not np.array_equal(tensor[6:], antes[6:])
          and tensor[6:].min() >= -1.0 and tensor[6:].max() <= 1.0,
          f"rango=[{tensor[6:].min():.3f}, {tensor[6:].max():.3f}]")

    # [5] apilar_tensor ------------------------------------------------------
    def _c(v):
        return np.full((32, 32), v, dtype=np.float32)
    apilado = apilar_tensor(_c(0.1), _c(0.2), _c(0.3), _c(0.4), _c(0.5), _c(0.6),
                            _c(0.05), _c(0.30), _c(0.02))
    check("[5] apilar_tensor: shape [9,32,32]", apilado.shape == (9, 32, 32))
    check("[5] apilar_tensor: ch6-8 estirados a [-1, 1]",
          apilado[6:].min() >= -1.0 and apilado[6:].max() <= 1.0
          and not np.allclose(apilado[6], 0.05),
          f"ch6={apilado[6,0,0]:.3f} ch7={apilado[7,0,0]:.3f} ch8={apilado[8,0,0]:.3f}")
    check("[5] apilar_tensor: ch0-5 sin tocar",
          np.allclose(apilado[0], 0.1) and np.allclose(apilado[5], 0.6))

    # [6] Parches reales de la entrega --------------------------------------
    test_dir = ENTREGA_DIR / "dataset_pipeline" / "data" / "processed_acumulativo" / "test"
    if torch is None:
        aviso("[6] parches reales de la entrega",
              "torch no instalado en este entorno: comprobacion omitida")
    elif test_dir.exists():
        import glob as _glob
        ficheros = sorted(_glob.glob(str(test_dir / "patch_*.pt")))[:30]
        dentro, fuera = True, []
        rt_max = 0.0
        for f in ficheros:
            t = torch.load(f, map_location="cpu", weights_only=True).to(torch.float32)
            ch = t[6:9].numpy()
            if ch.min() < -1.0 or ch.max() > 1.0:
                dentro = False
                fuera.append(Path(f).name)
            # round-trip: inversa del estiramiento y volver a estirar
            for i, (p2_, p98_) in enumerate(P2_P98_CH6_8):
                crudo = (ch[i] + 1.0) / 2.0 * (p98_ - p2_) + p2_
                vuelta = estirar_canal_distancia(crudo.astype(np.float32).copy(), p2_, p98_)
                rt_max = max(rt_max, float(np.abs(vuelta - np.clip(ch[i], -1, 1)).max()))
        check("[6] 30 parches entregados con ch6-8 dentro de [-1, 1]",
              dentro, f"{fuera[:3]}")
        check("[6] round-trip inverso estable (<= 2e-3 por fp16)",
              rt_max <= 2e-3, f"max_diff={rt_max:.3e}")
    else:
        aviso("[6] dataset de test no disponible",
              "define ENTREGA_DIR para validar sobre parches reales")

    # [7] tasks.py aplica el estiramiento -----------------------------------
    tasks_py = RAIZ / "ml_engine" / "tasks.py"
    src = tasks_py.read_text(encoding="utf-8")
    check("[7] tasks.py importa estirar_canales_distancia",
          "estirar_canales_distancia" in src)
    pos_str = src.find("tensor[8] = calcular_dist_capa_estatica")
    pos_est = src.find("estirar_canales_distancia(tensor)")
    check("[7] tasks.py estira ch6-8 despues de calcularlos y antes del tiling",
          pos_str != -1 and pos_est != -1 and pos_str < pos_est,
          f"posiciones {pos_str} < {pos_est}")

    print()
    for a in AVISOS:
        print(f"  Aviso registrado: {a}")
    print("-" * 70)
    if FALLAS:
        print(f"RESULTADO: FALLA ({len(FALLAS)} comprobaciones): {FALLAS}")
        return 1
    print("RESULTADO: PASA")
    return 0


if __name__ == "__main__":
    sys.exit(main())
