"""
acquisition.py - APU GUARD ML Engine
=====================================
Adquisicion de imagenes Sentinel-2 SIN Google Earth Engine.

Fuente: STAC publico de Element84 "Earth Search" sobre AWS
        https://earth-search.aws.element84.com/v1
        COG (Cloud Optimized GeoTIFF) publicos por HTTPS, sin credenciales.

Contrato de salida (IDENTICO al de _descargar_composite_gee):
    descargar_composite_stac(...) -> (ruta_tif, cobertura_nubes, transform, crs)

    - 4 bandas: B2 (blue), B3 (green), B4 (red), B8 (nir), en ese orden
    - dtype int16, valores 0..10000 (reflectancia Sentinel-2 L2A, BOA offset
      ya aplicado -> equivalente a COPERNICUS/S2_SR_HARMONIZED)
    - nodata = 0  (el consumidor hace `banda[banda == 0] = np.nan`)
    - CRS EPSG:32719 (UTM 19S), resolucion 10 m
    - mosaico = mediana temporal de todas las escenas que cubren el pixel,
      con mascara de nubes SCL (clases 4,5,6,11) aplicada ANTES de la mediana

Diseno orientado a produccion (el entorno dev puede no notarlo):
    - MEMORIA ACOTADA: se procesa por bloques de filas; nunca se materializa
      el raster completo en RAM ni la pila de fechas completo.
    - SIN TEMPORALES INTERMEDIOS: los tiles nunca se descargan a disco; solo
      se escribe el GeoTIFF de salida (deflate) y el preview opcional.
    - LECTURA WINDOWED (range requests) sobre /vsicurl: solo se transfieren
      los bytes del AOI, no los COG de 110x110 km completos.
    - Los recursos temporales se borran siempre (finally).
"""

import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import numpy as np
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuracion (entorno)
# ---------------------------------------------------------------------------

STAC_URL_DEFAULT       = "https://earth-search.aws.element84.com/v1"
STAC_COLLECTION_DEFAULT = "sentinel-2-l2a"

# EPSG exigido por ml_engine.preprocessing.calcular_bbox_parche (hardcodeado)
CRS_SALIDA  = "EPSG:32719"
RES_SALIDA  = 10.0
BANDAS      = ("blue", "green", "red", "nir")
SCL_ASSET   = "scl"

# Sinonimos de assets: cubre Earth Search (minisculas) y Planetary Computer /
# Copernicus (B02, B03, ...). Permite cambiar de fuente sin tocar el codigo.
ASSET_ALIASES = {
    "blue":  ("blue", "B02", "B2"),
    "green": ("green", "B03", "B3"),
    "red":   ("red", "B04", "B4"),
    "nir":   ("nir", "B08", "B8"),
    "scl":   ("scl", "SCL", "QA60"),
}

# Clases SCL validas: 4=vegetacion, 5=suelo desnudo, 6=agua, 11=nieve.
# Replica exacta de _mascara_nubes_s2 (tasks.py).
SCL_VALIDAS = frozenset((4, 5, 6, 11))


def _env(name, default):
    v = os.environ.get(name)
    return default if v in (None, "") else v


def _env_int(name, default):
    try:
        return int(_env(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        return float(_env(name, default))
    except (TypeError, ValueError):
        return default


def _tuning_gdal():
    """
    Ajusta GDAL para lectura remota windowed y uso predecible de recursos.

    IMPORTANTE (produccion):
      - GDAL_DISABLE_READDIR_ON_OPEN=EMPTY_DIR evita un LIST sobre la URL
        (2-3x mas rapido y sin consumir conexiones).
      - GDAL_CACHEMAX esta limitado: es memoria fija del worker, no crece
        con el tamano del dataset.
      - NO se activa VSI_CACHE (disco): en contenedores con /tmp pequeño
        provocaria llenado de volumen efimero. Se controla via IMAGERY_TMP_DIR.
    """
    defaults = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.TIF,.tiff",
        "GDAL_HTTP_MULTIPLEX": "YES",
        "GDAL_HTTP_VERSION": "2",
        "GDAL_CACHEMAX": str(_env_int("IMAGERY_GDAL_CACHE_MB", 256)),
        # Medido en pruebas: subir el chunk NO ayuda. Un bloque leido mide
        # 1-8 MB, asi que con 1 MB GDAL ya cubre la mayoria en una sola
        # peticion; con 8 MB cada lectura arrastra un buffer de 8 MB y el
        # tiempo de E/A sube linealmente (1 MB -> 239 s, 4 MB -> 312 s,
        # 8 MB -> 390 s en el mismo recorte). Ademas cada manejador retiene
        # el chunk mientras esta abierto: 1 MB x 60 COG = 60 MB residentes.
        "CPL_VSIL_CURL_CHUNK_SIZE": str(_env_int("IMAGERY_CHUNK_KB", 1024) * 1024),
        "CPL_VSIL_CURL_PAGE_SIZE": str(_env_int("IMAGERY_CHUNK_KB", 1024) * 1024),
        "GDAL_NUM_THREADS": "ALL_CPUS",
        "GDAL_HTTP_MAX_RETRY": "2",
        "GDAL_HTTP_TIMEOUT": str(_env_int("IMAGERY_HTTP_TIMEOUT", 60)),
    }
    for k, v in defaults.items():
        os.environ.setdefault(k, v)

    tmp_dir = _env("IMAGERY_TMP_DIR", "")
    if tmp_dir:
        os.makedirs(tmp_dir, exist_ok=True)
        # rasterio/GDAL y python usan estos para temporales
        for var in ("TMPDIR", "TEMP", "TMP", "CPL_TMPDIR"):
            os.environ[var] = tmp_dir


# ---------------------------------------------------------------------------
# Busqueda STAC
# ---------------------------------------------------------------------------

def buscar_items_stac(bbox, fecha_inicio, fecha_fin,
                      url=None, coleccion=None, max_cloud=None,
                      timeout=None):
    """
    Busca items Sentinel-2 L2A que intersectan `bbox` (lon/lat) en el rango.

    Args:
        bbox: (min_lon, min_lat, max_lon, max_lat) en EPSG:4326
        fecha_inicio, fecha_fin: date
        max_cloud: umbral opcional de eo:cloud_cover (%)

    Returns:
        lista de dicts normalizados:
        {"id", "datetime", "cloud", "hrefs": {blue,green,red,nir,scl}, "grid"}
    """
    import requests

    url = url or _env("STAC_URL", STAC_URL_DEFAULT)
    coleccion = coleccion or _env("STAC_COLLECTION", STAC_COLLECTION_DEFAULT)
    timeout = timeout or _env_int("IMAGERY_HTTP_TIMEOUT", 60)

    # Earth Search exige RFC3339 completo con T/Z (si no devuelve 400).
    dt_ini = f"{fecha_inicio.isoformat()}T00:00:00Z"
    dt_fin = f"{fecha_fin.isoformat()}T23:59:59Z"

    payload = {
        "collections": [coleccion],
        "bbox": [float(v) for v in bbox],
        "datetime": f"{dt_ini}/{dt_fin}",
        "limit": 100,
    }

    items, next_url = [], url.rstrip("/") + "/search"
    seen = set()
    while next_url and next_url not in seen:
        seen.add(next_url)
        resp = requests.post(next_url, json=payload, timeout=timeout)
        if resp.status_code != 200:
            raise RuntimeError(
                f"[STAC] {resp.status_code} en {next_url}: {resp.text[:400]}"
            )
        data = resp.json()
        for feat in data.get("features", []):
            items.append(_normalizar_item(feat))
        # paginacion: el siguiente enlace trae el token, se quita el bbox/payload
        next_url = None
        for link in data.get("links", []):
            if link.get("rel") == "next" and link.get("href"):
                next_url = link["href"]
                break

    if max_cloud is not None:
        items = [i for i in items if i["cloud"] is None or i["cloud"] <= max_cloud]

    items.sort(key=lambda i: (i["datetime"] or "", i["id"]))
    return items


def _normalizar_item(feat):
    props = feat.get("properties", {})
    assets = feat.get("assets", {})
    hrefs = {}
    for nombre, alias in ASSET_ALIASES.items():
        for a in alias:
            if a in assets and assets[a].get("href"):
                hrefs[nombre] = assets[a]["href"]
                break
    dt = props.get("datetime") or props.get("start_datetime") or ""
    return {
        "id": feat.get("id", ""),
        "datetime": dt,
        "cloud": props.get("eo:cloud_cover"),
        "grid": props.get("grid:code") or props.get("s2:mgrs_tile"),
        "epsg": props.get("proj:epsg"),
        "bbox": feat.get("bbox"),
        "hrefs": hrefs,
    }


# ---------------------------------------------------------------------------
# Lectura windowed por bloque
# ---------------------------------------------------------------------------

_reg = {}
_reg_lock = threading.Lock()

# Diagnostico: segundos de E/A reales frente a wall time, para medir el
# paralelismo efectivo (cuello de botella de latencia, no de CPU).
_IO = {"abrir": 0.0, "leer": 0.0, "n_abrir": 0, "n_leer": 0}
_IO_LOCK = threading.Lock()


def _io_add(clave, dt):
    with _IO_LOCK:
        _IO[clave] += dt
        _IO["n_" + clave] += 1


def _abrir(href):
    """
    Obtiene la entrada de un COG abierto via /vsicurl, abriendolo UNA sola vez
    aunque lo pidan varios hilos.

    Cada entrada lleva su propio lock: dos hilos jamas leen el mismo
    DatasetReader a la vez (rasterio/GDAL no lo soportan), pero si pueden leer
    COG distintos en paralelo. El paralelismo ataca el cuello de botella real:
    la latencia de cada peticion de rango (~0.5-1.7 s) frente al volumen.
    """
    with _reg_lock:
        entrada = _reg.get(href)
        if entrada is None:
            entrada = {"ds": None, "error": None, "lock": threading.Lock(),
                       "ready": threading.Event()}
            _reg[href] = entrada
            dueno = True
        else:
            dueno = False

    if dueno:
        try:
            _t0 = time.time()
            entrada["ds"] = rasterio.open("/vsicurl/" + href)
            _io_add("abrir", time.time() - _t0)
        except Exception as exc:          # noqa: BLE001
            entrada["error"] = exc
        finally:
            entrada["ready"].set()
    else:
        entrada["ready"].wait()

    if entrada["ds"] is None:
        raise entrada["error"] or RuntimeError(f"No se pudo abrir {href}")
    return entrada


def cerrar_datasets():
    """Cierra TODOS los manejadores (hilo principal + hilos del pool)."""
    with _reg_lock:
        entradas = list(_reg.values())
        _reg.clear()
    for e in entradas:
        e["ready"].wait()
        try:
            if e["ds"] is not None:
                e["ds"].close()
        except Exception:
            pass
        e["ds"] = None


def _retirar(hrefs_activos):
    """
    Cierra los COG abiertos que el bloque actual no usa.

    Cada manejador /vsicurl/ retiene un buffer de CPL_VSIL_CURL_CHUNK_SIZE
    (~8 MB) mientras esta abierto: sin este recorte, un AOI completo con 31
    escenas x 5 assets dejaria 1.5 GB residentes solo en buffers.
    """
    with _reg_lock:
        fuera = [h for h in list(_reg) if h not in hrefs_activos]
        entradas = [_reg.pop(h) for h in fuera]
    for e in entradas:
        e["ready"].wait()
        try:
            if e["ds"] is not None:
                e["ds"].close()
        except Exception:
            pass
        e["ds"] = None
    return len(entradas)


def _leer_en_paralelo(n, worker, max_workers):
    """Ejecuta worker(0..n-1) en paralelo. Las excepciones se propagan."""
    if n <= 0:
        return
    workers = max(1, min(max_workers, n))
    if workers == 1:
        for k in range(n):
            worker(k)
        return
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(worker, k) for k in range(n)]
        for f in futs:
            f.result()


@lru_cache(maxsize=4)
def _transformer_utm_a_wgs84():
    from pyproj import Transformer
    return Transformer.from_crs(CRS_SALIDA, "EPSG:4326", always_xy=True)


def _bounds_lonlat(transform, y_top, bh, bw, res_x, res_y):
    """
    Bounds lon/lat aproximados de un bloque UTM (esquinas + tolerancia por
    curvatura). Se usa SOLO para descartar items cuyo tile no intersecta el
    bloque: el recorte exacto lo resuelve _leer_bloque.
    """
    tr = _transformer_utm_a_wgs84()
    xs = (transform.c, transform.c + bw * res_x)
    ys = (y_top, y_top - bh * res_y)
    lons, lats = [], []
    for x in xs:
        for y in ys:
            lo, la = tr.transform(x, y)
            lons.append(lo)
            lats.append(la)
    return (min(lons), max(lons)), (min(lats), max(lats))


def _mediana_nan(stack):
    """
    Mediana por pixel ignorando NaN, SIN usar np.nanmedian.

    np.nanmedian hace ~3.5 millones de particiones independientes para un
    bloque del AOI completo y llega a costar 6x mas que ordenar el eje 0.
    Al estar ya ordenado (los NaN quedan al final), la mediana es la media
    de los dos elementos centrales entre los `validos` primeros.
    """
    n = stack.shape[0]
    stack.sort(axis=0)                          # in-place, NaN al final
    validos = n - np.isnan(stack).sum(axis=0)   # [bh, bw] int

    i_lo = (validos.astype(np.int32) - 1) // 2
    np.maximum(i_lo, 0, out=i_lo)
    i_hi = validos // 2
    np.minimum(i_hi, n - 1, out=i_hi)

    lo = np.take_along_axis(stack, i_lo[None], axis=0)[0]
    hi = np.take_along_axis(stack, i_hi[None], axis=0)[0]
    med = (lo + hi) * 0.5
    med[validos == 0] = np.nan
    return med.astype(np.float32, copy=False)


def _indices_origen(ds, x0, y0, bw, bh, res_x, res_y):
    """
    Calcula los indices de pixel de origen (1D) para un bloque de la grilla maestra.

    Convencion: el pixel (i, j) del bloque abarca
        X = x0 + j*res_x .. x0 + (j+1)*res_x
        Y = y0 - i*res_y .. y0 - (i+1)*res_y     (y0 = borde superior)
    Se muestrea el CENTRO del pixel destino -> nearest neighbour exacto.
    """
    t = ds.transform
    cols_f = (x0 + res_x * (np.arange(bw, dtype=np.float64) + 0.5) - t.c) / t.a
    rows_f = (y0 - res_y * (np.arange(bh, dtype=np.float64) + 0.5) - t.f) / t.e
    cols = np.floor(cols_f + 1e-6).astype(np.int32)
    rows = np.floor(rows_f + 1e-6).astype(np.int32)
    return rows, cols


def _leer_bloque(entrada, x0, y0, bw, bh, res_x, res_y, fill):
    """
    Lee un bloque de la grilla maestra desde un COG con nearest neighbour.

    `entrada` es la salida de `_abrir()` (dict con lock propio) o bien un
    DatasetReader cualquiera (modo sin paralelismo).

    Returns:
        array float32 [bh, bw] con `fill` donde el origen no tiene cobertura, o
        None si el dataset no intersecta el bloque.
    """
    ds = entrada["ds"] if isinstance(entrada, dict) else entrada
    _t0 = time.time()
    try:
        if isinstance(entrada, dict):
            with entrada["lock"]:
                return _leer_bloque_ds(ds, x0, y0, bw, bh, res_x, res_y, fill)
        return _leer_bloque_ds(ds, x0, y0, bw, bh, res_x, res_y, fill)
    finally:
        _io_add("leer", time.time() - _t0)


def _leer_bloque_ds(ds, x0, y0, bw, bh, res_x, res_y, fill):
    h, w = ds.height, ds.width
    rows, cols = _indices_origen(ds, x0, y0, bw, bh, res_x, res_y)

    valid_rows = (rows >= 0) & (rows < h)
    valid_cols = (cols >= 0) & (cols < w)
    if not valid_rows.any() or not valid_cols.any():
        return None

    rmin = int(rows[valid_rows].min())
    rmax = int(rows[valid_rows].max())
    cmin = int(cols[valid_cols].min())
    cmax = int(cols[valid_cols].max())

    # Fuera de cobertura -> indice seguro (se pisa con `fill` despues)
    rows_c = np.where(valid_rows, rows, rmin)
    cols_c = np.where(valid_cols, cols, cmin)

    win = Window(cmin, rmin, cmax - cmin + 1, rmax - rmin + 1)
    data = ds.read(1, window=win)

    bloque = data[np.ix_(rows_c - rmin, cols_c - cmin)].astype(np.float32, copy=True)

    valido = valid_rows[:, None] & valid_cols[None, :]
    if not valido.all():
        bloque[~valido] = fill
    return bloque


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------

def _grilla_maestra(bbox, res=RES_SALIDA):
    """
    Convierte el bbox lon/lat en una grilla UTM 19S alineada a multiplos de
    `res` metros. Alinearla al multiplo de 10 m garantiza offsets ENTEROS
    respecto del origen de los tiles Sentinel-2 (tambien multiplos de 10 m),
    de modo que la fusion no requiere reproyeccion ni remuestreo.
    """
    from pyproj import Transformer

    min_lon, min_lat, max_lon, max_lat = bbox
    tr = Transformer.from_crs("EPSG:4326", CRS_SALIDA, always_xy=True)

    # densificacion: el rectangulo lon/lat no es un rectangulo en UTM
    lons = np.linspace(min_lon, max_lon, 21)
    lats = np.linspace(min_lat, max_lat, 21)
    lon_g, lat_g = np.meshgrid(lons, lats)
    xs, ys = tr.transform(lon_g, lat_g)

    left   = math.floor(xs.min() / res) * res
    right  = math.ceil (xs.max() / res) * res
    bottom = math.floor(ys.min() / res) * res
    top    = math.ceil (ys.max() / res) * res

    width  = int(round((right - left) / res))
    height = int(round((top - bottom) / res))
    return from_origin(left, top, res, res), width, height


def descargar_composite_stac(fecha_inicio, fecha_fin, bbox,
                            url=None, coleccion=None, max_cloud=None,
                            out_path=None, block_rows=None,
                            subir_s3=False, bucket=None, prefijo="raw-rasters/",
                            preview_path=None):
    """
    Construye el composite quincenal mediano de Sentinel-2 L2A vía STAC.

    Returns:
        (ruta_tif, cobertura_nubes_pct, transform, crs)   <- mismo contrato
                que _descargar_composite_gee.

    El GeoTIFF temporal se escribe comprimido (DEFLATE) en IMAGERY_TMP_DIR
    (o el temp del sistema). EL CALLER ES RESPONSABLE de borrarlo; para
    pruebas sueltas pasa `out_path` a una ruta que controles.
    """
    _tuning_gdal()

    t0 = time.time()
    for k in list(_IO):
        _IO[k] = 0
    transform, width, height = _grilla_maestra(bbox)
    logger.info(
        "[STAC] Grilla maestra: %dx%d px @%.0fm  bounds=(%.1f, %.1f)-(%.1f, %.1f)",
        width, height, RES_SALIDA,
        transform.c, transform.f - height * RES_SALIDA,
        transform.c + width * RES_SALIDA, transform.f,
    )

    items = buscar_items_stac(bbox, fecha_inicio, fecha_fin,
                              url=url, coleccion=coleccion, max_cloud=max_cloud)
    if not items:
        raise RuntimeError(
            "[STAC] Sin items en el rango consultado. "
            "Amplia el periodo o sube IMAGERY_MAX_CLOUD."
        )

    # Solo assets realmente disponibles y en el CRS de trabajo
    seleccion = []
    for it in items:
        if all(a in it["hrefs"] for a in BANDAS):
            seleccion.append(it)
    if not seleccion:
        raise RuntimeError("[STAC] Los items no exponen las bandas requeridas.")

    nubes = [i["cloud"] for i in seleccion if i["cloud"] is not None]
    cobertura_nubes = float(np.mean(nubes)) if nubes else 0.0
    grids = sorted({i["grid"] for i in seleccion if i["grid"]})
    logger.info(
        "[STAC] %d items | %d fechas | tiles=%s | nubes media=%.1f%%",
        len(seleccion),
        len({i["datetime"][:10] for i in seleccion if i["datetime"]}),
        ",".join(grids) or "s/d", cobertura_nubes,
    )

    # Verificacion de CRS: todo debe estar en EPSG:32719 para fusionar sin warp
    epsgs = {i["epsg"] for i in seleccion if i["epsg"]}
    if epsgs and epsgs != {32719}:
        raise RuntimeError(
            f"[STAC] CRS inesperado en los items: {epsgs}. Se esperaba {{32719}}."
        )

    # -- Salida --
    if out_path is None:
        import tempfile
        fd, out_path = tempfile.mkstemp(suffix=".tif", prefix="apuguard_stac_")
        os.close(fd)

    block_rows = block_rows or _env_int("IMAGERY_BLOCK_ROWS", 512)
    res_x = float(transform.a)
    res_y = float(-transform.e)
    x0 = float(transform.c)
    y0 = float(transform.f)
    max_workers = _env_int("IMAGERY_WORKERS", 16)

    # -- Memoria acotada (produccion) --------------------------------------
    # stack float32 [N, bh, W] + masks uint8 [N, bh, W] deben caber en el
    # presupuesto IMAGERY_MEM_MB. Un bloque fijo de 512 filas sobre un AOI de
    # 15.000 px con 30 escenas consumiria >2 GB; aqui se adapta al ancho y al
    # numero de escenas.
    mem_mb     = _env_int("IMAGERY_MEM_MB", 512)
    por_fila   = max(1, len(seleccion) * width * (4 + 1))
    limite     = max(64, (mem_mb * 1024 * 1024) // por_fila)
    solicitado = int(block_rows)
    block_rows = int(min(solicitado, limite))
    if block_rows < solicitado:
        logger.info("[STAC] block_rows %d -> %d (presupuesto %d MB, %d escenas)",
                    solicitado, block_rows, mem_mb, len(seleccion))
    # Alinear al tamanio de tile GTiff. Si cada `write` llena tiles COMPLETOS
    # no hay read-modify-write ni reescrituras de tiles parciales. Medido con
    # GDAL_CACHEMAX=16MB sobre 14779x6000px:
    #   write por banda, blockysize=512 -> 1086 MB / 110 s
    #   write conjunto, blockysize=512 ->  460 MB /  16 s
    #   write conjunto, blockysize=224 ->  222 MB /   4 s
    block_rows = max(16, (min(block_rows, height) // 16) * 16)
    logger.info("[STAC] block_rows=%d | workers=%d | budget=%d MB",
                block_rows, max_workers, mem_mb)

    n_bloques = math.ceil(height / block_rows)
    escritos = 0

    perfil = dict(
        driver="GTiff", height=height, width=width, count=len(BANDAS),
        dtype="int16", crs=CRS_SALIDA, transform=transform, nodata=0,
        # blockysize == block_rows: cada `write` llena tiles enteros
        tiled=True, blockxsize=512, blockysize=block_rows,
        compress="deflate", predictor=2,
        bigtiff="IF_SAFER", num_threads="ALL_CPUS",
    )

    con_scl = any(SCL_ASSET in i["hrefs"] for i in seleccion)
    if not con_scl:
        logger.warning("[STAC] La coleccion no expone SCL: sin mascara de nubes.")

    # 4 bandas int16 del bloque, escritas en UNA sola llamada (ver arriba)
    salida = np.zeros((len(BANDAS), block_rows, width), dtype=np.int16)

    dst = rasterio.open(out_path, "w", **perfil)
    try:
        for b_i in range(0, height, block_rows):
            bh = min(block_rows, height - b_i)
            yb = y0 - b_i * res_y
            n_bloque = b_i // block_rows + 1

            # Solo las escenas cuyo tile intersecta el bloque: el AOI completo
            # cubre ~6 tiles, pero cada banda de filas solo ve 1-3 de ellos.
            (lon0, lon1), (lat0, lat1) = _bounds_lonlat(transform, yb, bh,
                                                        width, res_x, res_y)
            activos = []
            for k, item in enumerate(seleccion):
                bb = item.get("bbox")
                if bb is None:
                    activos.append(k)
                elif not (bb[2] < lon0 - 0.05 or bb[0] > lon1 + 0.05 or
                          bb[3] < lat0 - 0.05 or bb[1] > lat1 + 0.05):
                    activos.append(k)

            permitidos = set()
            for k in activos:
                permitidos.update(seleccion[k]["hrefs"].values())
            _retirar(permitidos)

            if not activos:
                salida[:, :bh] = 0
                dst.write(salida[:, :bh], window=Window(0, b_i, width, bh))
                escritos += len(BANDAS)
                continue

            # Mascara de nubes: se resuelve UNA vez por bloque y se reutiliza
            # en las 4 bandas (SCL viene a 20 m -> nearest a 10 m).
            masks = [None] * len(activos)
            if con_scl:
                def _leer_scl(si):
                    item = seleccion[activos[si]]
                    href = item["hrefs"].get(SCL_ASSET)
                    if not href:
                        return
                    try:
                        scl = _leer_bloque(_abrir(href), x0, yb, width, bh,
                                           res_x, res_y, fill=-1)
                    except Exception as exc:
                        logger.warning("[STAC] %s/SCL: %s", item["id"], exc)
                        return
                    if scl is None:
                        return
                    # 4=vegetacion, 5=suelo, 6=agua, 11=nieve
                    masks[si] = np.isin(scl.astype(np.int16), tuple(SCL_VALIDAS))
                    del scl

                _leer_en_paralelo(len(activos), _leer_scl, max_workers)

            for banda_idx, banda in enumerate(BANDAS):
                stack = np.full((len(activos), bh, width),
                                np.nan, dtype=np.float32)

                def _leer_banda(si, banda=banda):
                    item = seleccion[activos[si]]
                    href = item["hrefs"].get(banda)
                    if not href:
                        return
                    try:
                        bloque = _leer_bloque(_abrir(href), x0, yb, width, bh,
                                              res_x, res_y, fill=np.nan)
                    except Exception as exc:
                        logger.warning("[STAC] %s/%s: %s", item["id"], banda, exc)
                        return
                    if bloque is None:
                        return
                    # nodata del COG (0) y pixeles sin cobertura -> NaN
                    bloque[bloque == 0] = np.nan
                    # nubes / sombra / cirros -> NaN
                    m = masks[si]
                    if m is not None:
                        bloque[~m] = np.nan
                    stack[si] = bloque
                    del bloque

                _leer_en_paralelo(len(activos), _leer_banda, max_workers)

                comp = _mediana_nan(stack)
                del stack

                comp = np.where(np.isfinite(comp), comp, 0.0)
                np.clip(comp, 0, 10000, out=comp)
                salida[banda_idx, :bh] = comp

            del masks

            # UNA sola escritura por bloque: las 4 bandas juntas completan el
            # tile GTiff sin read-modify-write (ver nota sobre block_rows).
            dst.write(salida[:, :bh], window=Window(0, b_i, width, bh))
            escritos += len(BANDAS)

            if n_bloque % 4 == 0 or n_bloque == n_bloques:
                wall = max(time.time() - t0, 1e-9)
                io = _IO["abrir"] + _IO["leer"]
                logger.info(
                    "[STAC] bloque %d/%d (%.0fs) | E/A %.0fs en %d ops "
                    "(abrir %.0fs/%d, leer %.0fs/%d) | efectivo x%.1f",
                    n_bloque, n_bloques, wall, io,
                    _IO["n_abrir"] + _IO["n_leer"],
                    _IO["abrir"], _IO["n_abrir"], _IO["leer"], _IO["n_leer"],
                    io / wall,
                )
    finally:
        try:
            dst.close()
        finally:
            cerrar_datasets()

    if subir_s3 and bucket:
        _subir_s3(out_path, bucket, prefijo, fecha_inicio, fecha_fin)

    if preview_path:
        generar_preview(out_path, preview_path)

    logger.info("[STAC] Composite listo en %.1fs -> %s", time.time() - t0, out_path)
    return out_path, cobertura_nubes, transform, rasterio.crs.CRS.from_string(CRS_SALIDA)


def _subir_s3(path, bucket, prefijo, fecha_inicio, fecha_fin):
    import boto3
    key = f"{prefijo}sentinel2_{fecha_inicio}_{fecha_fin}_10m.tif"
    s3 = boto3.client("s3")
    s3.upload_file(path, bucket, key,
                   ExtraArgs={"ContentType": "image/tiff"})
    logger.info("[STAC] Subido a s3://%s/%s", bucket, key)


# ---------------------------------------------------------------------------
# Validacion + preview
# ---------------------------------------------------------------------------

def validar_composite(path, bbox=None):
    """
    Comprueba que el raster cumple EXACTAMENTE el contrato que espera el resto
    del procesamiento (preprocessing + tasks).

    Returns:
        dict con "ok" y el detalle de cada chequeo.
    """
    chequeos = []

    def chk(nombre, esperado, obtenido, extra=""):
        ok = esperado == obtenido
        chequeos.append({"check": nombre, "esperado": esperado,
                         "obtenido": obtenido, "ok": ok, "detalle": extra})
        return ok

    with rasterio.open(path) as src:
        chk("bandas (B2,B3,B4,B8)", 4, src.count)
        chk("dtype int16", "int16", src.dtypes[0])
        chk("CRS EPSG:32719", "EPSG:32719", src.crs.to_string() if src.crs else None)
        chk("nodata", 0, src.nodata)
        chk("resolucion 10 m", (10.0, 10.0),
            (round(src.transform.a, 3), round(-src.transform.e, 3)))
        chk("alineacion x a multiplo de 10", True,
            abs(src.transform.c % 10) < 1e-6, f"c={src.transform.c}")
        chk("alineacion y a multiplo de 10", True,
            abs(src.transform.f % 10) < 1e-6, f"f={src.transform.f}")

        stats = []
        for b in range(1, src.count + 1):
            # lectura reducida (overview/vista) para no cargar 900 MB
            data = src.read(b, out_shape=(
                min(src.height, 2048),
                min(src.width, 4096)))
            valid = data[data != 0]
            stats.append({
                "banda": b,
                "min": int(data.min()), "max": int(data.max()),
                "media_validos": round(float(valid.mean()), 1) if valid.size else None,
                "pct_nodata": round(float((data == 0).mean() * 100), 2),
            })
        dims = (src.height, src.width)
        bounds = src.bounds

    chk("rango 0..10000 (sin negativos)", True,
        all(s["min"] >= 0 and s["max"] <= 10000 for s in stats), str(stats))
    chk("pixeles validos presentes", True,
        all(s["media_validos"] is not None for s in stats))

    resuelto = all(c["ok"] for c in chequeos)
    return {
        "ok": resuelto,
        "path": path,
        "shape_hw": dims,
        "bounds": tuple(round(v, 1) for v in bounds),
        "bandas": stats,
        "chequeos": chequeos,
    }


def generar_preview(path, out_png, max_side=1600, banda_rgb=(3, 2, 1)):
    """
    Genera un PNG RGB con estiramiento percentil 2-98 (misma logica visual que
    las visualizaciones del pipeline) para corroboracion humana.
    """
    from PIL import Image

    with rasterio.open(path) as src:
        tw = min(src.width, max_side)
        th = max(1, int(round(src.height * (tw / src.width))))
        out_shape = (th, tw)
        r = src.read(banda_rgb[0], out_shape=out_shape).astype(np.float32)
        g = src.read(banda_rgb[1], out_shape=out_shape).astype(np.float32)
        b = src.read(banda_rgb[2], out_shape=out_shape).astype(np.float32)

    def stretch(a):
        v = a[a > 0]
        if v.size == 0:
            return np.zeros(a.shape, np.uint8)
        lo, hi = np.percentile(v, (2, 98))
        if hi <= lo:
            hi = lo + 1
        return np.clip((a - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)

    rgb = np.dstack([stretch(r), stretch(g), stretch(b)])
    rgb[(r == 0) & (g == 0) & (b == 0)] = 0
    Image.fromarray(rgb).save(out_png)
    return out_png
