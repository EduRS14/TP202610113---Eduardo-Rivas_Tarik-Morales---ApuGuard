"""
preprocessing.py - APU GUARD ML Engine
=======================================
Modulo de preprocesamiento de imagenes satelitales.

Pipeline completo:
  1. Calculo de indices espectrales (NDWI, SAVI)
  2. Normalizacion z-score GLOBAL (imagen completa, no por parche)
  3. Calculo de canales de distancia en [0, 1]
  4. Estiramiento P2-P98 congelado de ch6-8 a [-1, 1] (entrega HRNet final)
  5. Apilamiento en tensor de 9 canales
  6. Tiling con stride=128, descarte de parches con NaN

Orden de canales de salida:
  ch0=Blue, ch1=Green, ch2=Red, ch3=NIR,
  ch4=NDWI, ch5=SAVI,
  ch6=dist_deforest, ch7=dist_mining, ch8=dist_rivers

Contrato de normalizacion (identico al dataset evaluado de la entrega):
  ch0-5 : z-score global por imagen (media/std del composite completo).
  ch6-8 : distancia cruda en [0, 1] estirada con los percentiles P2/P98
          congelados del split de train -> [-1, 1] con clip.
  No se aplica ningun desplazamiento posterior a los logits del modelo.
"""

import logging
import numpy as np
from typing import Iterator, Tuple

import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_bounds
from scipy.ndimage import distance_transform_edt

logger = logging.getLogger(__name__)

# -- Constantes --
PATCH_SIZE = 128
STRIDE     = 128      # Sin solapamiento — reduce parches a ~6,600 por quincena
L_SAVI     = 0.5      # Factor de correccion de suelo para SAVI

# Percentiles P2/P98 de los canales de distancia, congelados a partir del
# split de entrenamiento por dataset_pipeline/src/reprocess_normalization.py
# y guardados en dataset_pipeline/data/processed_acumulativo/
# normalization_stats.json (metodo "minmax_p2_p98_to_neg1_1").
# VALORES EXACTOS DE LA ENTREGA: no recalcularlos en produccion.
P2_P98_CH6_8 = (
    (0.0007610321044921875, 0.09173583984375),   # ch6 dist_deforest
    (0.0291595458984375,    0.5654296875),       # ch7 dist_mining
    (0.0,                   0.1004638671875),    # ch8 dist_rivers
)
EPS_DENOM_P2P98 = 1e-10   # mismo guard que normalize_channel() de la entrega


# ---------------------------------------------------------------------------
# 1. Indices espectrales
# ---------------------------------------------------------------------------

def calcular_indices(blue, green, red, nir):
    """
    Calcula NDWI y SAVI a partir de las 4 bandas espectrales.

    Args:
        blue, green, red, nir: arrays 2D float32, misma shape.
                               Valores 0 o NaN donde no hay datos.

    Returns:
        ndwi, savi: arrays 2D float32, misma shape que la entrada.
    """
    eps = 1e-8

    # NDWI = (NIR - Green) / (NIR + Green)
    # Valores altos = agua/humedad; util para mineria aluvial
    ndwi = (nir - green) / (nir + green + eps)

    # SAVI = ((NIR - Red) / (NIR + Red + L)) * (1 + L)
    # Mas robusto que NDVI en zonas con suelo expuesto
    savi = ((nir - red) / (nir + red + L_SAVI + eps)) * (1 + L_SAVI)

    return ndwi.astype(np.float32), savi.astype(np.float32)


# ---------------------------------------------------------------------------
# 2. Normalizacion z-score global
# ---------------------------------------------------------------------------

def normalizar_zscore_global(bandas):
    """
    Aplica z-score a cada canal usando la media y std de TODA la imagen.
    NaN se excluye del calculo y se mantiene en la salida.

    CRITICO: se debe aplicar sobre la imagen COMPLETA antes de extraer
    parches. Normalizar por parche destruiria la informacion espectral
    relativa entre zonas de bosque y zonas deforestadas.

    Operacion IN-PLACE para evitar duplicar el array en memoria.
    A 10m el array de 6 bandas pesa ~3.8GB — copiar generaria OOM.

    Args:
        bandas: array float32 [6, H, W] con ch0-5 (Blue,Green,Red,NIR,NDWI,SAVI)
                NaN donde no hay datos. Se modifica in-place.

    Returns:
        El mismo array float32 [6, H, W] normalizado (mismo objeto).
    """
    eps = 1e-8
    for i in range(bandas.shape[0]):
        mean = np.nanmean(bandas[i])
        std  = np.nanstd(bandas[i])
        bandas[i] -= mean
        bandas[i] /= (std + eps)
        logger.debug(f"  ch{i}: mean={mean:.4f} std={std:.4f}")
    return bandas


# ---------------------------------------------------------------------------
# 3. Canales de distancia
# ---------------------------------------------------------------------------

def calcular_dist_deforest(casos_historicos_geoms, transform, shape):
    """
    Canal 6: distancia normalizada al pixel de deforestacion mas cercano
    en los casos historicos activos (PERTURBADO o RECUPERANDO).

    Replica el rol de dist_deforest del pipeline de entrenamiento, pero
    usando la memoria del propio sistema en lugar de shapefiles GFW.

    Args:
        casos_historicos_geoms: lista de geometrias GeoJSON (geom_afectada)
                                de CasoAuditoria con estado PERTURBADO o RECUPERANDO.
        transform: rasterio.Affine del raster de referencia.
        shape: (H, W) del raster.

    Returns:
        array float32 [H, W] con la distancia CRUDA en [0, 1].
        Pasar por estirar_canales_distancia() (o apilar_tensor) antes
        de enviar a HRNet.
    """
    H, W = shape

    if not casos_historicos_geoms:
        # Sin historial: distancia maxima = 1.0 en todos los pixeles
        return np.ones((H, W), dtype=np.float32)

    # Rasterizar los poligonos de deforestacion historica
    mascara = rasterize(
        [(geom, 1) for geom in casos_historicos_geoms],
        out_shape=(H, W),
        transform=transform,
        fill=0,
        dtype=np.uint8,
    )

    # Calcular distancia euclidiana al pixel mas cercano con deforestacion
    zona_libre = (mascara == 0).astype(np.uint8)
    del mascara  # 110M px (uint8): liberar antes del EDT (~0.1 GB)
    dist = distance_transform_edt(zona_libre).astype(np.float32)
    del zona_libre  # ~0.1 GB

    # Normalizar a [0, 1]
    max_dist = dist.max()
    if max_dist > 0:
        dist = dist / max_dist

    return dist


def calcular_dist_capa_estatica(raster_s3_path, s3_client, bucket, target_shape=None):
    """
    Carga un raster de distancia pre-calculado desde S3 (mineria.tif o rios.tif).
    Estos rasters ya estan en [0, 1] y se actualizan manualmente cuando
    cambia el catastro minero o la red hidrica.

    El valor devuelto es la distancia CRUDA: exige estiramiento P2-P98
    (estirar_canales_distancia) justo antes de apilar/tilear.

    Args:
        raster_s3_path: clave S3 del raster (ej. "static-layers/mineria.tif")
        s3_client: cliente boto3 S3
        bucket: nombre del bucket S3
        target_shape: tuple (H, W) opcional. Si el raster tiene distinto shape,
                      se hace resize bilineal para que coincida con el composite.

    Returns:
        array float32 [H, W] con la distancia CRUDA en [0, 1] (sin estirar).
    """
    import io
    from scipy.ndimage import zoom as ndimage_zoom

    response = s3_client.get_object(Bucket=bucket, Key=raster_s3_path)
    data     = response["Body"].read()

    with rasterio.open(io.BytesIO(data)) as src:
        dist = src.read(1).astype(np.float32)

    # Garantizar rango [0, 1]
    dist = np.clip(dist, 0.0, 1.0)

    # Resize si el shape no coincide con el composite descargado
    if target_shape is not None and dist.shape != tuple(target_shape):
        zoom_h = target_shape[0] / dist.shape[0]
        zoom_w = target_shape[1] / dist.shape[1]
        dist = ndimage_zoom(dist, (zoom_h, zoom_w), order=1)  # bilineal
        dist = np.clip(dist, 0.0, 1.0).astype(np.float32)

    return dist


# ---------------------------------------------------------------------------
# 3b. Estiramiento P2-P98 de los canales de distancia (-> [-1, 1])
# ---------------------------------------------------------------------------

def estirar_canal_distancia(canal, p2, p98):
    """
    Aplica el estiramiento min-max con percentiles de la entrega:
        x' = clip( 2 * (x - p2) / (p98 - p2) - 1 , -1, 1 )

    Es la transformacion exacta de normalize_channel() de
    dataset_pipeline/src/reprocess_normalization.py (mismo guard de
    denominador, misma aritmetica), aplicada aqui en numpy.

    La operacion es IN-PLACE para no duplicar canales de 110M pixeles
    (~440 MB por canal en float32).

    Args:
        canal: array float32 2D en [0, 1] (distancia cruda).
        p2, p98: percentiles congelados del split de train (P2_P98_CH6_8).

    Returns:
        El mismo array float32, ahora en [-1, 1] (NaN se conservan).
    """
    denom = p98 - p2
    if denom < EPS_DENOM_P2P98:
        denom = EPS_DENOM_P2P98
    np.subtract(canal, p2, out=canal)
    np.multiply(canal, 2.0 / denom, out=canal)
    np.add(canal, -1.0, out=canal)
    np.clip(canal, -1.0, 1.0, out=canal)
    return canal


def estirar_canales_distancia(tensor):
    """
    Estira los canales 6-8 de un tensor [9, H, W] a [-1, 1] usando los
    percentiles congelados de la entrega. Canales 0-5 intactos.

    IN-PLACE: modifica `tensor` y lo devuelve.

    Precondicion: ch6-8 deben estar en [0, 1] (distancia cruda).
    Postcondicion: ch6-8 en [-1, 1], listos para HRNet.
    """
    for canal_idx, (p2, p98) in enumerate(P2_P98_CH6_8, start=6):
        estirar_canal_distancia(tensor[canal_idx], p2, p98)
    return tensor


# ---------------------------------------------------------------------------
# 4. Apilamiento en tensor de 9 canales
# ---------------------------------------------------------------------------

def apilar_tensor(blue, green, red, nir, ndwi, savi,
                  dist_deforest, dist_mining, dist_rivers):
    """
    Construye el tensor de 9 canales en el orden esperado por HRNet.

    Los canales 0-5 deben estar ya normalizados (z-score global).
    Los canales 6-8 DEBEN llegar en [0, 1] (distancia cruda): aqui se les
    aplica el estiramiento P2-P98 congelado y salen en [-1, 1].

    Returns:
        tensor: float32 [9, H, W] con ch6-8 ya en [-1, 1]
    """
    tensor = np.stack([
        blue, green, red, nir,      # ch0-3: espectrales
        ndwi, savi,                 # ch4-5: indices
        dist_deforest,              # ch6: distancia deforestacion historica
        dist_mining,                # ch7: distancia concesiones mineras
        dist_rivers,                # ch8: distancia rios
    ], axis=0).astype(np.float32)  # [9, H, W]

    # ch6-8: [0, 1] -> [-1, 1] con los percentiles de la entrega
    estirar_canales_distancia(tensor)

    return tensor


# ---------------------------------------------------------------------------
# 5. Tiling con stride=128
# ---------------------------------------------------------------------------

def extraer_parches(tensor, transform):
    """
    Extrae parches de 128x128 con stride=128 (sin solapamiento).
    Descarta parches que contengan cualquier pixel NaN.

    Args:
        tensor: float32 [9, H, W] ya normalizado y apilado.
        transform: rasterio.Affine del raster (para calcular footprint geografico).

    Yields:
        (parche, fila_idx, col_idx, bbox_wgs84)
          parche    : float32 [9, 128, 128]
          fila_idx  : int, indice de fila en la grilla
          col_idx   : int, indice de columna en la grilla
          bbox_wgs84: (min_lon, min_lat, max_lon, max_lat) en EPSG:4326
    """
    _, H, W = tensor.shape

    fila_idx = 0
    for row in range(0, H - PATCH_SIZE + 1, STRIDE):
        col_idx = 0
        for col in range(0, W - PATCH_SIZE + 1, STRIDE):
            parche = tensor[:, row:row + PATCH_SIZE, col:col + PATCH_SIZE]

            # Descartar parches con demasiados NaN (>20% de pixels)
            nan_ratio = np.isnan(parche).mean()
            if nan_ratio > 0.20:
                col_idx += 1
                continue

            # Reemplazar NaN residuales con 0 antes de enviar a SageMaker
            parche = np.nan_to_num(parche, nan=0.0)

            # Calcular footprint geografico del parche
            bbox = calcular_bbox_parche(transform, row, col, PATCH_SIZE)

            yield parche, fila_idx, col_idx, bbox
            col_idx += 1
        fila_idx += 1


def calcular_bbox_parche(transform, row, col, size):
    """
    Calcula el bounding box geografico de un parche en EPSG:4326.

    Args:
        transform: rasterio.Affine del raster completo.
        row, col : esquina superior izquierda del parche (en pixeles).
        size     : tamano del parche en pixeles.

    Returns:
        (min_lon, min_lat, max_lon, max_lat) en grados decimales WGS84.
    """
    # Pixel (col, row) -> coordenadas del raster (EPSG:32719)
    x_min, y_max = transform * (col, row)
    x_max, y_min = transform * (col + size, row + size)

    # Reproyectar EPSG:32719 -> EPSG:4326
    from pyproj import Transformer
    transformer = Transformer.from_crs("EPSG:32719", "EPSG:4326", always_xy=True)
    lon_min, lat_min = transformer.transform(x_min, y_min)
    lon_max, lat_max = transformer.transform(x_max, y_max)

    return (lon_min, lat_min, lon_max, lat_max)


def bbox_a_polygon_wkt(bbox):
    """
    Convierte (min_lon, min_lat, max_lon, max_lat) a WKT POLYGON.
    Util para crear geometrias Django/PostGIS.
    """
    lon_min, lat_min, lon_max, lat_max = bbox
    return (
        f"POLYGON(("
        f"{lon_min} {lat_min}, "
        f"{lon_max} {lat_min}, "
        f"{lon_max} {lat_max}, "
        f"{lon_min} {lat_max}, "
        f"{lon_min} {lat_min}"
        f"))"
    )


# ---------------------------------------------------------------------------
# 6. Reconstruccion de mapa completo (Max Pooling en solapamiento)
# ---------------------------------------------------------------------------

def reconstruir_mapa(parches_resultado, shape_original):
    """
    Reconstruye el mapa de probabilidades completo desde los parches,
    usando Max Pooling en zonas de solapamiento (stride=128, parche=128).

    Con el stride actual (= PATCH_SIZE) los parches no se solapan, por lo
    que el Max Pooling es una identidad: se conserva por si se vuelve a
    reducir STRIDE por debajo de PATCH_SIZE.

    Args:
        parches_resultado: lista de (fila_idx, col_idx, prob_array)
                          prob_array: float32 [1, 128, 128]
        shape_original: (H, W) del raster completo

    Returns:
        mapa_prob: float32 [H, W], probabilidades en [0, 1]
        mapa_mask: float32 [H, W], binario {0, 1} con threshold=0.30
    """
    THRESHOLD = 0.30
    H, W = shape_original
    mapa = np.zeros((H, W), dtype=np.float32)

    for fila_idx, col_idx, prob in parches_resultado:
        row = fila_idx * STRIDE
        col = col_idx  * STRIDE
        row_end = min(row + PATCH_SIZE, H)
        col_end = min(col + PATCH_SIZE, W)

        parche_prob = prob[0, :row_end - row, :col_end - col]
        mapa[row:row_end, col:col_end] = np.maximum(
            mapa[row:row_end, col:col_end],
            parche_prob,
        )

    mapa_mask = (mapa > THRESHOLD).astype(np.float32)
    return mapa, mapa_mask
