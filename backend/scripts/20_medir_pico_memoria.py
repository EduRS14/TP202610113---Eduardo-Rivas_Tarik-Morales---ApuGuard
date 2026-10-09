"""
20_medir_pico_memoria.py
=========================
Mide el PICO REAL de RAM del tramo pesado de procesar_quincena_tambopata()
(sin tocar AWS, sin Django, sin red).

Replica en secuencia el flujo de ml_engine/tasks.py:80-260 usando arrays
sinteticos del shape real (7426 x 14870 @10m, EPSG:32719), llamando a las
funciones REALES de ml_engine.preprocessing (calcular_dist_deforest,
extraer_parches) y a una copia local de calcular_dist_capa_estatica con un
cliente S3 falso que devuelve un GeoTIFF en memoria.

Uso (DENTRO del contenedor celery_worker, que es donde corre la tarea):
    docker compose exec celery_worker python /app/scripts/20_medir_pico_memoria.py

Opciones:
    --shape HxW        shape del composite (default 7426x14870)
    --etapas a,b,c     correr solo esas etapas (separadas por coma)
    --listar           imprime el listado de etapas y sale
    --sin-parches      no itera extraer_parches (aisla el pico del tensor)

Salida:
    tabla por etapa con RSS actual, delta y VmHWM (marca de agua del kernel),
    mas un resumen con el pico absoluto y el veredicto contra los tamanos
    de instancia candidatos.
"""
import argparse
import gc
import io
import json
import os
import sys
import threading
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import numpy as np  # noqa: E402

# Shape real del composite de Tambopata (settings.py:203)
H_DEFAULT, W_DEFAULT = 7426, 14870
# Capas estaticas reales (scripts/02_generar_static_layers.py:31)
STATIC_H, STATIC_W = 256, 256
# Transform UTM del extent de entrenamiento (settings.py:203)
ORIGIN_X, ORIGIN_Y, RES = 380480.0, 8617720.0, 10.0

GB = 1024 ** 3


# ---------------------------------------------------------------------------
# Medicion de memoria
# ---------------------------------------------------------------------------

def _leer_status():
    """Devuelve (VmRSS, VmHWM) en bytes desde /proc/self/status."""
    rss = hwm = 0
    try:
        with open("/proc/self/status", "r") as fh:
            for linea in fh:
                if linea.startswith("VmRSS:"):
                    rss = int(linea.split()[1]) * 1024
                elif linea.startswith("VmHWM:"):
                    hwm = int(linea.split()[1]) * 1024
    except OSError:
        pass
    return rss, hwm


def _meminfo():
    """Devuelve (MemTotal, MemAvailable) en bytes desde /proc/meminfo."""
    tot = avail = 0
    try:
        with open("/proc/meminfo", "r") as fh:
            for linea in fh:
                if linea.startswith("MemTotal:"):
                    tot = int(linea.split()[1]) * 1024
                elif linea.startswith("MemAvailable:"):
                    avail = int(linea.split()[1]) * 1024
    except OSError:
        pass
    return tot, avail


class Muestreador(threading.Thread):
    """Muestrea VmRSS cada `intervalo` s en background y guarda el maximo."""

    def __init__(self, intervalo=0.05):
        super().__init__(daemon=True)
        self.intervalo = intervalo
        self._parar = threading.Event()
        self.rss_max = 0
        self.t_rss_max = 0.0
        self.t0 = time.monotonic()
        self.n_muestras = 0

    def run(self):
        while not self._parar.is_set():
            rss, _ = _leer_status()
            self.n_muestras += 1
            if rss > self.rss_max:
                self.rss_max = rss
                self.t_rss_max = time.monotonic() - self.t0
            time.sleep(self.intervalo)

    def parar(self):
        self._parar.set()
        self.join(timeout=2)


class Etapa:
    """Registro de una etapa del pipeline."""

    def __init__(self, clave, descripcion):
        self.clave = clave
        self.descripcion = descripcion
        self.rss_antes = 0
        self.rss_despues = 0
        self.hwm_despues = 0
        self.segs = 0.0
        self.nota = ""

    @property
    def delta(self):
        return self.rss_despues - self.rss_antes


# ---------------------------------------------------------------------------
# Cliente S3 falso (para calcular_dist_capa_estatica sin red)
# ---------------------------------------------------------------------------

class _Cuerpo:
    def __init__(self, datos):
        self._datos = datos

    def read(self):
        return self._datos


class S3Falso:
    """Expone get_object() y devuelve un GeoTIFF ya construido en memoria."""

    def __init__(self, geo_tiff_bytes):
        self._bytes = geo_tiff_bytes

    def get_object(self, Bucket=None, Key=None):  # noqa: N803
        return {"Body": _Cuerpo(self._bytes)}


def _geo_tiff_en_memoria(valor_base):
    """GeoTIFF float32 256x256 igual al que genera 02_generar_static_layers.py."""
    import rasterio
    from rasterio.transform import from_bounds

    data = np.random.uniform(valor_base, 1.0, (STATIC_H, STATIC_W)).astype(np.float32)
    transform = from_bounds(-70.10, -13.50, -69.00, -12.30, STATIC_W, STATIC_H)
    buf = io.BytesIO()
    with rasterio.open(
        buf, "w", driver="GTiff", height=STATIC_H, width=STATIC_W,
        count=1, dtype="float32", crs="EPSG:4326", transform=transform,
    ) as dst:
        dst.write(data, 1)
    return buf.getvalue()


def _geo_tiff_falso_desde_ruta(raster_s3_path, s3_client, bucket, target_shape=None):
    """
    Copia literal de ml_engine/preprocessing.py:145-180 (calcular_dist_capa_estatica).
    Existe aqui para no requerir Django ni boto3; el cuerpo de la funcion es identico.
    """
    from scipy.ndimage import zoom as ndimage_zoom
    import rasterio

    response = s3_client.get_object(Bucket=bucket, Key=raster_s3_path)
    data = response["Body"].read()

    with rasterio.open(io.BytesIO(data)) as src:
        dist = src.read(1).astype(np.float32)

    dist = np.clip(dist, 0.0, 1.0)

    if target_shape is not None and dist.shape != tuple(target_shape):
        zoom_h = target_shape[0] / dist.shape[0]
        zoom_w = target_shape[1] / dist.shape[1]
        dist = ndimage_zoom(dist, (zoom_h, zoom_w), order=1)
        dist = np.clip(dist, 0.0, 1.0).astype(np.float32)

    return dist


# ---------------------------------------------------------------------------
# Geometrias historicas sinteticas (para calcular_dist_deforest)
# ---------------------------------------------------------------------------

def _geoms_sinteticas(transform, H, W, n=40, semilla=7):
    """n poligonos GeoJSON en el CRS del raster (EPSG:32719) para rasterizar."""
    rng = np.random.default_rng(semilla)
    # Tamaños adaptables: con shapes de prueba (<600 px) se recortan.
    lado_min = max(8, min(200, min(H, W) // 8))
    lado_max = max(lado_min + 1, min(600, min(H, W) // 2))
    geoms = []
    for _ in range(n):
        ancho = int(rng.integers(lado_min, lado_max))
        alto = int(rng.integers(lado_min, lado_max))
        col = int(rng.integers(0, max(1, W - ancho)))
        row = int(rng.integers(0, max(1, H - alto)))
        x0, y0 = transform * (col, row)
        x1, y1 = transform * (col + ancho, row + alto)
        geoms.append({
            "type": "Polygon",
            "coordinates": [[
                [x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0],
            ]],
        })
    return geoms


# ---------------------------------------------------------------------------
# Etapas
# ---------------------------------------------------------------------------

def etapa_00_baseline(ctx):
    ctx["tensor"] = None
    return "proceso limpio"


def etapa_01_bandas(ctx):
    """tasks.py:115-121 — src.read(1..4).astype(np.float32)"""
    H, W = ctx["H"], ctx["W"]
    ctx["blue"] = np.full((H, W), 0.1, dtype=np.float32)
    ctx["green"] = np.full((H, W), 0.1, dtype=np.float32)
    ctx["red"] = np.full((H, W), 0.1, dtype=np.float32)
    ctx["nir"] = np.full((H, W), 0.1, dtype=np.float32)
    # Algo de ceros para que la mascara de la etapa 02 tenga trabajo real
    ctx["blue"][:200, :200] = 0.0
    return "4 bandas float32"


def etapa_02_ceros_nan(ctx):
    """tasks.py:124-125 — banda[banda == 0] = np.nan"""
    for nombre in ("blue", "green", "red", "nir"):
        banda = ctx[nombre]
        banda[banda == 0] = np.nan
    return "4 mascaras bool + asignacion in-place"


def etapa_03_alloc_tensor(ctx):
    """tasks.py:135 — np.empty((9,H,W)): reserva virtual, aun sin commitear"""
    ctx["tensor"] = np.empty((9, ctx["H"], ctx["W"]), dtype=np.float32)
    return "np.empty 9 canales (paginas sin commitear)"


def etapa_04_copiar_espectrales(ctx):
    """tasks.py:138-142 — copia canal a canal y libera cada banda"""
    t = ctx["tensor"]
    t[0] = ctx.pop("blue")
    t[1] = ctx.pop("green")
    t[2] = ctx.pop("red")
    t[3] = ctx.pop("nir")
    gc.collect()
    return "copia ch0-3 y liberacion progresiva de bandas"


def etapa_05_indices(ctx):
    """tasks.py:146-147 — NDWI y SAVI con temporales intermedios"""
    t = ctx["tensor"]
    eps = 1e-8
    t[4] = (t[3] - t[1]) / (t[3] + t[1] + eps)
    t[5] = ((t[3] - t[2]) / (t[3] + t[2] + 0.5 + eps)) * 1.5
    return "3 temporales float32 por formula (num/den/res)"


def etapa_06_zscore(ctx):
    """tasks.py:151-155 — z-score por canal, nanmean/nanstd crean copias"""
    t = ctx["tensor"]
    eps = 1e-8
    for i in range(6):
        mean = float(np.nanmean(t[i]))
        std = float(np.nanstd(t[i]))
        t[i] -= mean
        t[i] /= (std + eps)
    return "np.nanmean + np.nanstd por canal (copia interna)"


def etapa_07_dist_deforest(ctx):
    """tasks.py:157-172 — canal 6: rasterize + distance_transform_edt"""
    from ml_engine.preprocessing import calcular_dist_deforest

    t = ctx["tensor"]
    geoms = ctx["geoms"]
    if not geoms:
        t[6] = np.ones((ctx["H"], ctx["W"]), dtype=np.float32)
        return "sin historial: np.ones (peor caso NO reproducido)"
    t[6] = calcular_dist_deforest(geoms, ctx["transform"], (ctx["H"], ctx["W"]))
    gc.collect()
    return f"{len(geoms)} geoms -> rasterize + EDT (float64 interno)"


def _capa_estatica(ctx, valor_base, etiqueta):
    s3 = S3Falso(ctx[f"tif_{etiqueta}"])
    return _geo_tiff_falso_desde_ruta(
        f"static-layers/{etiqueta}.tif", s3, "falso", target_shape=(ctx["H"], ctx["W"]),
    )


def etapa_08_dist_mining(ctx):
    """tasks.py:177-180 — canal 7 desde S3 (256x256 -> zoom a 7426x14870)"""
    ctx["tensor"][7] = _capa_estatica(ctx, 0.3, "mineria")
    gc.collect()
    return "zoom 256->7426x14870 (x29, x58) + clip + astype"


def etapa_09_dist_rivers(ctx):
    """tasks.py:181-184 — canal 8 desde S3"""
    ctx["tensor"][8] = _capa_estatica(ctx, 0.5, "rios")
    gc.collect()
    return "zoom + clip + astype (tensor ya completo: 9/9 canales)"


def etapa_10_tiling(ctx):
    """tasks.py:193-210 — extraer_parches + np.save a BytesIO (sin S3)"""
    from ml_engine.preprocessing import extraer_parches

    n = 0
    bytes_tot = 0
    for parche, _f, _c, _bbox in extraer_parches(ctx["tensor"], ctx["transform"]):
        buf = io.BytesIO()
        np.save(buf, parche[np.newaxis, ...])   # [1, 9, 128, 128]
        bytes_tot += len(buf.getvalue())
        n += 1
        if ctx.get("limite_parches") and n >= ctx["limite_parches"]:
            break
    ctx["n_parches"] = n
    ctx["bytes_parches"] = bytes_tot
    return f"{n} parches serializados a BytesIO"


# ETAPAS: clave -> (descripcion, funcion)
ETAPAS = [
    ("00_baseline",        "Proceso limpio", etapa_00_baseline),
    ("01_bandas",          "Lectura de 4 bandas float32", etapa_01_bandas),
    ("02_ceros_nan",       "Reemplazo 0 -> NaN", etapa_02_ceros_nan),
    ("03_alloc_tensor",    "np.empty 9 canales", etapa_03_alloc_tensor),
    ("04_copiar_espectrales", "Copia ch0-3 + liberar bandas", etapa_04_copiar_espectrales),
    ("05_indices",         "NDWI + SAVI", etapa_05_indices),
    ("06_zscore",          "z-score global ch0-5", etapa_06_zscore),
    ("07_dist_deforest",   "Canal 6: rasterize + EDT", etapa_07_dist_deforest),
    ("08_dist_mining",     "Canal 7: capa estatica + zoom", etapa_08_dist_mining),
    ("09_dist_rivers",     "Canal 8: capa estatica + zoom", etapa_09_dist_rivers),
    ("10_tiling",          "Tiling + np.save por parche", etapa_10_tiling),
]


def gb(b):
    return b / GB


def main():
    parser = argparse.ArgumentParser(description="Mide el pico de RAM del pipeline quincenal.")
    parser.add_argument("--shape", default=f"{H_DEFAULT}x{W_DEFAULT}",
                        help="HxW del composite (default 7426x14870)")
    parser.add_argument("--etapas", default="", help="claves separadas por coma")
    parser.add_argument("--listar", action="store_true", help="lista etapas y sale")
    parser.add_argument("--sin-parches", action="store_true", help="omite la etapa 10")
    parser.add_argument("--limite-parches", type=int, default=0,
                        help="corta el tiling tras N parches (0 = todos)")
    parser.add_argument("--baseline", type=float, default=1.65,
                        help="GB de servicios en reposo (OS+Postgres+Redis+nginx"
                             "+gunicorn+celery). Default 1.65 = estimacion.")
    args = parser.parse_args()

    etapas = list(ETAPAS)

    if args.listar:
        for clave, desc, _fn in etapas:
            print(f"  {clave:26s} {desc}")
        return 0

    try:
        H, W = (int(v) for v in args.shape.lower().split("x"))
    except ValueError:
        print(f"[ERROR] --shape invalido: {args.shape} (usa HxW)")
        return 2

    seleccion = {c.strip() for c in args.etapas.split(",") if c.strip()}
    desconocidas = seleccion - {c for c, _d, _f in ETAPAS}
    if desconocidas:
        print(f"[ERROR] etapas desconocidas: {sorted(desconocidas)}  (usa --listar)")
        return 2

    import rasterio  # noqa: F401  (se comprueba antes de empezar)
    from rasterio.transform import from_origin
    from ml_engine.preprocessing import calcular_dist_deforest, extraer_parches  # noqa: F401

    mem_tot, mem_disp = _meminfo()
    rss0, hwm0 = _leer_status()

    print("=" * 96)
    print("MEDICION DE PICO DE RAM — tramo pesado de procesar_quincena_tambopata")
    print("=" * 96)
    print(f"  Host            : MemTotal {gb(mem_tot):6.2f} GB | MemAvailable {gb(mem_disp):6.2f} GB")
    print(f"  Proceso         : RSS {gb(rss0):6.2f} GB | VmHWM {gb(hwm0):6.2f} GB | PID {os.getpid()}")
    print(f"  Shape           : {H} x {W} = {H*W:,} px | 1 canal float32 = {gb(H*W*4):.3f} GB")
    print(f"  Tensor 9 canales: {gb(H*W*4*9):.3f} GB")
    print(f"  Etapas          : {', '.join(seleccion) if seleccion else 'TODAS'}")
    print("=" * 96)

    ctx = {
        "H": H, "W": W,
        "transform": from_origin(ORIGIN_X, ORIGIN_Y, RES, RES),
        "limite_parches": args.limite_parches,
    }
    ctx["geoms"] = _geoms_sinteticas(ctx["transform"], H, W, n=40)
    ctx["tif_mineria"] = _geo_tiff_en_memoria(0.3)
    ctx["tif_rios"] = _geo_tiff_en_memoria(0.5)

    if args.sin_parches:
        etapas = [e for e in etapas if e[0] != "10_tiling"]

    registros = []
    muestreador = Muestreador(intervalo=0.05)
    muestreador.start()

    for clave, desc, fn in etapas:
        if seleccion and clave not in seleccion:
            continue
        etapa = Etapa(clave, desc)
        gc.collect()
        etapa.rss_antes, _ = _leer_status()
        t0 = time.monotonic()
        try:
            etapa.nota = fn(ctx) or ""
        except MemoryError:
            etapa.nota = "*** MemoryError ***"
            etapa.rss_despues, etapa.hwm_despues = _leer_status()
            etapa.segs = time.monotonic() - t0
            registros.append(etapa)
            break
        etapa.segs = time.monotonic() - t0
        etapa.rss_despues, etapa.hwm_despues = _leer_status()
        registros.append(etapa)

    muestreador.parar()
    gc.collect()
    rss_final, hwm_final = _leer_status()
    _, mem_disp_final = _meminfo()

    print()
    print("-" * 96)
    print(f"{'ETAPA':26s} {'RSS antes':>10s} {'RSS desp':>10s} {'delta':>10s} "
          f"{'VmHWM':>10s} {'t (s)':>7s}  NOTA")
    print("-" * 96)
    for r in registros:
        print(f"{r.clave:26s} {gb(r.rss_antes):9.2f}G {gb(r.rss_despues):9.2f}G "
              f"{gb(r.delta):+9.2f}G {gb(r.hwm_despues):9.2f}G {r.segs:7.1f}  {r.nota}")
    print("-" * 96)

    etapa_pico = max(registros, key=lambda r: r.rss_despues) if registros else None
    pico = max(hwm_final, muestreador.rss_max)

    print()
    print("=" * 96)
    print("RESUMEN")
    print("=" * 96)
    print(f"  Pico de RAM del proceso (VmHWM) : {gb(hwm_final):6.2f} GB")
    print(f"  Pico por muestreo (50 ms)       : {gb(muestreador.rss_max):6.2f} GB "
          f"(t = {muestreador.t_rss_max:.1f}s, {muestreador.n_muestras} muestras)")
    if etapa_pico:
        print(f"  Etapa con mayor RSS             : {etapa_pico.clave} "
              f"({gb(etapa_pico.rss_despues):.2f} GB) — {etapa_pico.descripcion}")
    print(f"  RSS final tras gc               : {gb(rss_final):6.2f} GB")
    print(f"  MemAvailable final              : {gb(mem_disp_final):6.2f} GB")
    if ctx.get("n_parches"):
        print(f"  Parches iterados                : {ctx['n_parches']:,} "
              f"({gb(ctx['bytes_parches'])*1024:.1f} MB serializados)")

    # -- Veredicto contra los tamanos de instancia candidatos --
    BASE_PROD = args.baseline   # OS + Postgres + Redis + nginx + gunicorn + celery (GB)
    print()
    print("-" * 96)
    print("VEREDICTO contra tamanos de instancia (pico + baseline de servicios)")
    print("-" * 96)
    candidatos = [
        ("t4g.small   2 GB",  2.0),
        ("t4g.medium  4 GB",  4.0),
        ("m7i-flex.large 8 GB (tope Free Plan)", 8.0),
        ("16 GB (fuera de Free Plan)", 16.0),
    ]
    necesidad = gb(pico) + BASE_PROD
    for nombre, ram in candidatos:
        holgura = ram - necesidad
        estado = "PASA" if holgura >= 1.0 else ("ADVERTENCIA" if holgura > 0 else "FALLA")
        print(f"  {estado:12s} {nombre:38s} necesita {necesidad:5.2f} GB "
              f"| holgura {holgura:+5.2f} GB")
    print()
    print(f"  Formula: pico {gb(pico):.2f} GB + baseline {BASE_PROD:.2f} GB = {necesidad:.2f} GB")
    print("=" * 96)
    return 0


if __name__ == "__main__":
    sys.exit(main())
