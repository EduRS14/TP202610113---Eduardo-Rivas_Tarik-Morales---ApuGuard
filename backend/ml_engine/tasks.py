"""
tasks.py - APU GUARD ML Engine
================================
Tareas asincronas Celery para el motor de Machine Learning.

TAREA 1: procesar_quincena_tambopata  (Celery Beat, cada 15 dias)
  - Descarga composite quincenal de Sentinel-2 (STAC/AWS por defecto, GEE opcional)
  - Calcula indices espectrales (NDWI, SAVI)
  - Normaliza z-score sobre imagen completa
  - Calcula canales de distancia (dist_deforest, dist_mining, dist_rivers)
  - Recorta en parches 128x128 con stride=128
  - Envia cada parche a SageMaker (invoke_endpoint_async)

TAREA 2: procesar_resultado_sagemaker  (Escucha SQS continuo)
  - Lee resultados .npz desde S3 (escritos por SageMaker)
  - Vectoriza mascara binaria a poligonos GeoDjango
  - Aplica logica ecologica (memoria de recuperacion)
  - Calcula diferencia espacial con casos historicos
  - Crea CasoAuditoria y despacha SMS via AWS SNS
"""

import csv
import io
import json
import logging
import math
from datetime import datetime, timedelta, timezone as dt_timezone

import boto3
import numpy as np
import rasterio
from celery import shared_task
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon, Polygon
from django.utils import timezone
from rasterio.features import shapes as rasterio_shapes
from rasterio.transform import from_bounds
from shapely.geometry import shape as shapely_shape, mapping

from core.models import (
    CasoAuditoria, CapturaSatelital, ConfiguracionGlobal,
    DocumentoReporte, ParcheProcesamiento, RegistroSMS, SectorReserva,
)
from ml_engine.preprocessing import (
    PATCH_SIZE, STRIDE,
    apilar_tensor, bbox_a_polygon_wkt, calcular_bbox_parche,
    calcular_dist_capa_estatica, calcular_dist_deforest,
    calcular_indices, estirar_canales_distancia, extraer_parches,
    normalizar_zscore_global,
)

logger = logging.getLogger(__name__)

LN2 = math.log(2)

# Area minima (Ha) para considerar que una deteccion es real y no ruido.
# Se aplica DOS veces: (a) sobre la mascara cruda por parche y
# (b) sobre la diferencia neta contra los casos historicos (ver G2).
AREA_MINIMA_HA = 3.0

# SRID de calculo metrico (UTM 19S, zona del Tambopata)
SRID_METRICO = 32719


# ---------------------------------------------------------------------------
# Helpers AWS
# ---------------------------------------------------------------------------

def _get_s3():
    return boto3.client("s3", region_name=settings.AWS_REGION_NAME)

def _get_sagemaker_runtime():
    return boto3.client("sagemaker-runtime", region_name=settings.AWS_REGION_NAME)

def _get_sqs():
    return boto3.client("sqs", region_name=settings.AWS_REGION_NAME)

def _get_twilio():
    from twilio.rest import Client
    return Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)



# ---------------------------------------------------------------------------
# TAREA 1: Despachador quincenal
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def procesar_quincena_tambopata(self, forzar=False):
    """
    Tarea principal quincenal. Ejecutada por Celery Beat cada 15 dias.

    `forzar=False` (lo que envia beat): solo se ejecuta en los dias
    programados (1 y 16). Celery Beat hace *catch-up* al arrancar y reenvia
    todas las tareas crontab atrasadas de una vez — tras un apagon de la
    instancia dispararia la quincena un dia que no toca (incidente
    2026-10-07). Los lanzamientos manuales pasan forzar=True
    (scripts/04_lanzar_quincena.py).

    Flujo:
      1. Descarga composite Sentinel-2 (fuente: IMAGERY_SOURCE, ultimos 15 dias)
      2. Calcula NDWI y SAVI
      3. Normaliza z-score global (imagen completa)
      4. Carga capas estaticas (mineria.tif, rios.tif) desde S3
      5. Calcula dist_deforest dinamico desde CasoAuditoria historicos
      6. Estira ch6-8 con percentiles P2-P98 congelados (-> [-1, 1])
      7. Recorta en parches 128x128 (stride=128), descarta NaN
      8. Guarda .npy en S3, crea ParcheProcesamiento, invoca SageMaker async
    """
    fecha_hoy        = datetime.now().date()

    # -- 0. Guarda anti-disparo fuera de programa (ver docstring) --
    if not forzar and fecha_hoy.day not in (1, 16):
        logger.warning(
            "[QUINCENA] Disparo fuera de programa: dia %d no es 1/16. "
            "Se omite (catch-up de beat tras reinicio). Lanzamiento manual: "
            "scripts/04_lanzar_quincena.py", fecha_hoy.day,
        )
        return {"omitido": True, "motivo": "fuera_de_programa",
                "fecha": fecha_hoy.isoformat()}

    fecha_inicio     = fecha_hoy - timedelta(days=15)
    logger.info(f"[QUINCENA] Iniciando procesamiento: {fecha_inicio} -> {fecha_hoy}")

    # -- 1. Crear registro de captura --
    # Fase G5: get_or_create. fecha_adquisicion es unica, asi que un reintento
    # de Celery o una re-ejecucion manual debe reutilizar la captura existente
    # en lugar de reventar con IntegrityError.
    captura, captura_creada = CapturaSatelital.objects.get_or_create(
        fecha_adquisicion=fecha_inicio,
        defaults={
            "s3_path_raw": "",
            "estado_liberacion": CapturaSatelital.EstadoLiberacion.PROCESANDO,
        },
    )
    if captura_creada:
        logger.info(f"[QUINCENA] Captura creada para {fecha_inicio}")
    else:
        logger.warning(
            f"[QUINCENA] Captura {fecha_inicio} ya existia: re-ejecucion. "
            f"Se reutiliza y solo se completan los parches pendientes."
        )
        captura.estado_liberacion = CapturaSatelital.EstadoLiberacion.PROCESANDO
        captura.save(update_fields=["estado_liberacion"])

    raster_path = None
    try:
        # -- 2. Descargar composite (fuente configurable: stac | gee) --
        raster_path, cobertura_nubes, transform, crs = _descargar_composite(
            fecha_inicio, fecha_hoy, captura
        )
        captura.cobertura_nubes = cobertura_nubes
        captura.save(update_fields=["cobertura_nubes"])

        # -- 3. Cargar bandas del raster --
        with rasterio.open(raster_path) as src:
            blue  = src.read(1).astype(np.float32)
            green = src.read(2).astype(np.float32)
            red   = src.read(3).astype(np.float32)
            nir   = src.read(4).astype(np.float32)
            transform = src.transform
            H, W      = src.height, src.width

        # Reemplazar 0 por NaN (pixeles sin datos / nubes)
        for banda in [blue, green, red, nir]:
            banda[banda == 0] = np.nan

        # -- 4-8. Construir tensor [9, H, W] canal a canal (RAM optimizada) --
        # Se evita tener espectrales (3.8GB) + tensor (5.7GB) simultaneamente.
        # Estrategia: allocar tensor una vez y copiar/calcular cada canal in-situ.
        # Pico de RAM: ~6.4GB (tensor completo + 1 canal temporal).
        # Orden canales: B(0) G(1) R(2) NIR(3) NDWI(4) SAVI(5) dist_deforest(6) mining(7) rivers(8)
        import gc
        logger.info("[QUINCENA] Construyendo tensor 9 canales (memoria optimizada)...")
        eps = 1e-8
        tensor = np.empty((9, H, W), dtype=np.float32)

        # Canales 0-3: copiar bandas espectrales y liberar de inmediato
        tensor[0] = blue;  del blue
        tensor[1] = green; del green
        tensor[2] = red;   del red
        tensor[3] = nir;   del nir
        gc.collect()

        # Canales 4-5: indices calculados directamente desde el tensor (sin arrays extra)
        logger.info("[QUINCENA] Calculando indices NDWI y SAVI...")
        tensor[4] = (tensor[3] - tensor[1]) / (tensor[3] + tensor[1] + eps)               # NDWI
        tensor[5] = ((tensor[3] - tensor[2]) / (tensor[3] + tensor[2] + 0.5 + eps)) * 1.5  # SAVI

        # Normalizar z-score in-place sobre canales 0-5 (sin copiar el array)
        logger.info("[QUINCENA] Normalizando z-score global (imagen completa)...")
        for i in range(6):
            mean = float(np.nanmean(tensor[i]))
            std  = float(np.nanstd(tensor[i]))
            tensor[i] -= mean
            tensor[i] /= (std + eps)

        # Canal 6: dist_deforest dinamico (crea array temporal, se libera tras asignar)
        logger.info("[QUINCENA] Calculando dist_deforest desde casos historicos...")
        geoms_historicos = list(
            CasoAuditoria.objects.filter(
                estado_ecologico__in=[
                    CasoAuditoria.EstadoEcologico.PERTURBADO,
                    CasoAuditoria.EstadoEcologico.RECUPERANDO,
                ]
            ).exclude(geom_afectada__isnull=True)
            .values_list("geom_afectada", flat=True)
        )
        geoms_rasterio = [
            json.loads(g.geojson) for g in geoms_historicos
        ] if geoms_historicos else []
        tensor[6] = calcular_dist_deforest(geoms_rasterio, transform, (H, W))
        gc.collect()

        # Canales 7-8: capas estaticas de S3 (cada una se libera tras asignar)
        logger.info("[QUINCENA] Cargando capas estaticas de S3...")
        s3 = _get_s3()
        tensor[7] = calcular_dist_capa_estatica(
            f"{settings.S3_PREFIX_STATIC_LAYERS}mineria.tif", s3, settings.AWS_S3_BUCKET_NAME,
            target_shape=(H, W),
        )
        tensor[8] = calcular_dist_capa_estatica(
            f"{settings.S3_PREFIX_STATIC_LAYERS}rios.tif", s3, settings.AWS_S3_BUCKET_NAME,
            target_shape=(H, W),
        )
        gc.collect()

        # ch6-8: distancia cruda [0, 1] -> estiramiento P2-P98 congelado -> [-1, 1]
        # (percentiles exactos de la entrega; ver preprocessing.P2_P98_CH6_8)
        logger.info("[QUINCENA] Estirando ch6-8 con percentiles P2-P98 ([-1, 1])...")
        estirar_canales_distancia(tensor)
        gc.collect()

        # -- 9. Tiling y despacho a SageMaker --
        logger.info(f"[QUINCENA] Extrayendo parches (patch={PATCH_SIZE}, stride={STRIDE})...")
        sagemaker_rt = _get_sagemaker_runtime()
        n_parches    = 0
        n_enviados   = 0
        n_omitidos   = 0

        for parche, fila_idx, col_idx, bbox in extraer_parches(tensor, transform):
            n_parches += 1

            # Crear geometria del parche
            geom_wkt = bbox_a_polygon_wkt(bbox)
            geom_poly = GEOSGeometry(geom_wkt, srid=4326)
            s3_key = (
                f"{settings.S3_PREFIX_SAGEMAKER_IN}"
                f"captura_{captura.pk}/"
                f"parche_{fila_idx}_{col_idx}.npy"
            )

            # Fase G5: get_or_create hace el re-run idempotente (unique_together
            # de (captura, fila, col) reventaria con un .create() a secas).
            parche_obj, parche_creado = ParcheProcesamiento.objects.get_or_create(
                captura=captura,
                fila_idx=fila_idx,
                col_idx=col_idx,
                defaults={
                    "s3_path_tensor": f"s3://{settings.AWS_S3_BUCKET_NAME}/{s3_key}",
                    "estado_sagemaker": ParcheProcesamiento.EstadoSageMaker.PENDIENTE,
                    "geom": geom_poly,
                    "fecha_envio": timezone.now(),
                },
            )

            if not parche_creado and (
                parche_obj.estado_sagemaker
                == ParcheProcesamiento.EstadoSageMaker.PROCESADO
            ):
                # Ya tiene resultado de una ejecucion anterior: no volver a
                # subir ni a invocar (evita duplicar casos y mensajes SQS).
                n_omitidos += 1
                continue

            # Guardar parche en S3 como .npy (sobrescritura idempotente)
            buf = io.BytesIO()
            np.save(buf, parche[np.newaxis, ...])   # [1, 9, 128, 128]
            buf.seek(0)
            s3.put_object(
                Bucket=settings.AWS_S3_BUCKET_NAME,
                Key=s3_key,
                Body=buf.read(),
                ContentType="application/x-npy",
            )

            # Invocar SageMaker asincrono
            # Nota: OutputLocation NO es parametro de entrada de invoke_endpoint_async.
            # El destino S3 lo controla el AsyncInferenceConfig del endpoint (creado en AWS).
            # La respuesta devuelve OutputLocation con la ruta S3 real donde quedara el .out
            try:
                inference_id = f"captura_{captura.pk}_parche_{fila_idx}_{col_idx}"
                response = sagemaker_rt.invoke_endpoint_async(
                    EndpointName=settings.AWS_SAGEMAKER_ENDPOINT_NAME,
                    InputLocation=f"s3://{settings.AWS_S3_BUCKET_NAME}/{s3_key}",
                    ContentType="application/x-npy",
                    Accept="application/x-npz",
                    InvocationTimeoutSeconds=120,
                    InferenceId=inference_id,
                )
                request_id = response.get("InferenceId", "")
                output_loc  = response.get("OutputLocation", "")

                parche_obj.sagemaker_request_id = request_id
                parche_obj.s3_path_resultado    = output_loc
                parche_obj.fecha_envio          = timezone.now()
                parche_obj.save(update_fields=[
                    "sagemaker_request_id", "s3_path_resultado", "fecha_envio"
                ])
                n_enviados += 1

            except Exception as e:
                logger.error(f"[QUINCENA] Error invocando SageMaker parche "
                             f"[{fila_idx},{col_idx}]: {e}")
                parche_obj.estado_sagemaker = ParcheProcesamiento.EstadoSageMaker.ERROR
                parche_obj.save(update_fields=["estado_sagemaker"])

        logger.info(
            f"[QUINCENA] Completado: {n_parches} parches extraidos, "
            f"{n_enviados} enviados a SageMaker, {n_omitidos} ya procesados "
            f"(omitidos por re-ejecucion)."
        )

        captura.estado_liberacion = CapturaSatelital.EstadoLiberacion.AUDITORIA
        captura.save(update_fields=["estado_liberacion"])

    except Exception as exc:
        logger.exception(f"[QUINCENA] Error fatal: {exc}")
        captura.estado_liberacion = CapturaSatelital.EstadoLiberacion.PROCESANDO
        captura.save(update_fields=["estado_liberacion"])
        raise self.retry(exc=exc)

    finally:
        # El composite ya esta en S3: el temporal no debe quedarse en /tmp
        # (en contenedor efimero inmediato; en ECS/EC2 si no se limpia llena el volumen).
        if raster_path:
            try:
                import os
                os.unlink(raster_path)
            except OSError:
                pass


def _registrar_raster_raw(path, fecha_inicio, fecha_fin, captura):
    """
    Sube el composite a raw-rasters/ y lo registra en la captura.

    Helper compartido por las dos fuentes (stac y gee) para que la clave S3 y
    el guardado de `s3_path_raw` no se divergan entre rutas de adquisicion.
    """
    s3_key = (
        f"{settings.S3_PREFIX_RAW_RASTERS}"
        f"sentinel2_{fecha_inicio}_{fecha_fin}_10m.tif"
    )
    _get_s3().upload_file(
        path,
        settings.AWS_S3_BUCKET_NAME,
        s3_key,
        ExtraArgs={"ContentType": "image/tiff"},
    )
    captura.s3_path_raw = f"s3://{settings.AWS_S3_BUCKET_NAME}/{s3_key}"
    captura.save(update_fields=["s3_path_raw"])
    logger.info(f"[COMPOSITE] Raster crudo en {captura.s3_path_raw}")
    return s3_key


def _descargar_composite(fecha_inicio, fecha_fin, captura):
    """
    Punto de entrada unico de adquisicion del composite quincenal.

    settings.IMAGERY_SOURCE:
      - "stac" (defecto): Earth Search (AWS). Sin cuenta, sin cuota ni
        servidor de Earth Engine.
      - "gee": Google Earth Engine, comportamiento historico.
    """
    fuente = str(getattr(settings, "IMAGERY_SOURCE", "stac") or "stac").lower()
    if fuente == "gee":
        logger.info("[COMPOSITE] Fuente de imagenes: GEE")
        return _descargar_composite_gee(fecha_inicio, fecha_fin, captura)
    if fuente != "stac":
        logger.warning(
            f"[COMPOSITE] IMAGERY_SOURCE={fuente!r} desconocido; usando STAC"
        )
    logger.info("[COMPOSITE] Fuente de imagenes: STAC (Earth Search/AWS)")
    return _descargar_composite_stac(fecha_inicio, fecha_fin, captura)


def _descargar_composite_stac(fecha_inicio, fecha_fin, captura):
    """
    Composite Sentinel-2 via STAC/COG de AWS.

    Mismo contrato que _descargar_composite_gee:
        (ruta_local_tif, cobertura_nubes_pct, transform, crs)
    """
    from .acquisition import descargar_composite_stac

    bbox = settings.TAMBOPATA_BBOX
    ruta, cobertura, transform, crs = descargar_composite_stac(
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        bbox=(bbox["min_lon"], bbox["min_lat"], bbox["max_lon"], bbox["max_lat"]),
        subir_s3=False,          # la subida la hace _registrar_raster_raw
        max_cloud=getattr(settings, "IMAGERY_MAX_CLOUD", None),
    )
    _registrar_raster_raw(ruta, fecha_inicio, fecha_fin, captura)
    return ruta, float(cobertura), transform, crs


def _descargar_composite_gee(fecha_inicio, fecha_fin, captura):
    """
    Descarga el composite mediano quincenal de Sentinel-2 a 10m usando tiling.

    El AOI de Tambopata (~110x130km) es demasiado grande para getDownloadURL a 10m
    en una sola peticion (~1.1GB). Se divide en tiles de 0.15 grados (~16km x 16km)
    que a 10m pesan ~22MB cada uno, dentro del limite de GEE (~50MB).

    Flujo:
      1. Dividir AOI en tiles de 0.15 grados
      2. Para cada tile: construir composite Sentinel-2 y descargar a 10m via getDownloadURL
      3. Mosaico de todos los tiles con rasterio.merge
      4. Subir mosaico completo a S3
      5. Limpiar archivos temporales

    Returns:
        (ruta_local_tif, cobertura_nubes_pct, transform, crs)
    """
    import ee
    import os
    import tempfile
    import time
    import urllib.request
    from rasterio.merge import merge as rasterio_merge

    # -- Autenticar con Service Account --
    credentials = ee.ServiceAccountCredentials(
        email=settings.GEE_SERVICE_ACCOUNT,
        key_file=settings.GEE_KEY_FILE,
    )
    ee.Initialize(credentials)

    bbox          = settings.TAMBOPATA_BBOX
    fecha_ini_str = str(fecha_inicio)
    fecha_fin_str = str(fecha_fin)

    min_lon = bbox["min_lon"]
    min_lat = bbox["min_lat"]
    max_lon = bbox["max_lon"]
    max_lat = bbox["max_lat"]

    # Cobertura de nubes para el AOI completo (calculo unico)
    aoi_full = ee.Geometry.Rectangle([min_lon, min_lat, max_lon, max_lat])
    col_full = (
        ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
        .filterBounds(aoi_full)
        .filterDate(fecha_ini_str, fecha_fin_str)
        .map(_mascara_nubes_s2)
    )
    cobertura_nubes = col_full.aggregate_mean("CLOUDY_PIXEL_PERCENTAGE").getInfo()
    if cobertura_nubes is None:
        cobertura_nubes = 0.0

    # -- Grid de tiles --
    # 0.08 grados ~ 8.5km x 8.7km -> ~850x870 px a 10m
    # Con .toInt16() cada tile pesa ~6-14MB (limite GEE = 48MB)
    TILE_DEG   = 0.08
    lons       = list(np.arange(min_lon, max_lon, TILE_DEG))
    lats       = list(np.arange(min_lat, max_lat, TILE_DEG))
    n_tiles    = len(lons) * len(lats)
    logger.info(f"[GEE] Descargando {n_tiles} tiles a 10m "
                f"({len(lons)} cols x {len(lats)} filas, TILE={TILE_DEG}deg) ...")

    tile_paths = []

    for i, lon0 in enumerate(lons):
        lon1 = min(lon0 + TILE_DEG, max_lon)
        for j, lat0 in enumerate(lats):
            lat1 = min(lat0 + TILE_DEG, max_lat)

            tile_aoi = ee.Geometry.Rectangle([lon0, lat0, lon1, lat1])

            col_tile = (
                ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                .filterBounds(tile_aoi)
                .filterDate(fecha_ini_str, fecha_fin_str)
                .map(_mascara_nubes_s2)
            )
            # .toInt16() fuerza salida en 2 bytes/pixel en lugar de Float32/Float64
            # Sentinel-2 SR values (0-10000) caben perfectamente en Int16
            composite_tile = col_tile.select(["B2", "B3", "B4", "B8"]).median().toInt16()

            try:
                url = composite_tile.getDownloadURL({
                    "scale": 10,
                    "crs": "EPSG:32719",
                    "region": tile_aoi,
                    "format": "GeoTIFF",
                    "bands": ["B2", "B3", "B4", "B8"],
                })
                tmp_tile = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
                urllib.request.urlretrieve(url, tmp_tile.name)
                tile_paths.append(tmp_tile.name)
                logger.info(
                    f"[GEE] Tile [{i},{j}] OK "
                    f"(lon={lon0:.2f}..{lon1:.2f}, lat={lat0:.2f}..{lat1:.2f})"
                )
            except Exception as e:
                logger.warning(f"[GEE] Tile [{i},{j}] fallido, omitiendo: {e}")

            time.sleep(0.5)   # Rate limiting: evitar throttle de GEE

    if not tile_paths:
        raise RuntimeError(
            "[GEE] No se pudo descargar ningún tile. "
            "Verifica cobertura de nubes o fechas del periodo."
        )

    logger.info(f"[GEE] {len(tile_paths)}/{n_tiles} tiles descargados. Mosaicando ...")

    # -- Mosaico --
    src_files = [rasterio.open(p) for p in tile_paths]
    mosaic, mosaic_transform = rasterio_merge(src_files, nodata=0)

    meta = src_files[0].meta.copy()
    meta.update({
        "driver":    "GTiff",
        "height":    mosaic.shape[1],
        "width":     mosaic.shape[2],
        "transform": mosaic_transform,
        "count":     4,
        "nodata":    0,
    })
    for src in src_files:
        src.close()

    tmp_mosaic = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
    with rasterio.open(tmp_mosaic.name, "w", **meta) as dst:
        dst.write(mosaic)

    # Limpiar tiles temporales
    for p in tile_paths:
        try:
            os.unlink(p)
        except Exception:
            pass

    logger.info(
        f"[GEE] Mosaico generado: {mosaic.shape[2]}x{mosaic.shape[1]}px "
        f"@ 10m -> {tmp_mosaic.name}"
    )

    # -- Subir mosaico a S3 --
    _registrar_raster_raw(tmp_mosaic.name, fecha_inicio, fecha_fin, captura)

    with rasterio.open(tmp_mosaic.name) as src:
        transform = src.transform
        crs       = src.crs

    return tmp_mosaic.name, float(cobertura_nubes), transform, crs


def _mascara_nubes_s2(imagen):
    """Mascara de nubes para Sentinel-2 SR usando la banda SCL."""
    scl = imagen.select("SCL")
    # SCL valores: 4=vegetacion, 5=suelo, 6=agua, 11=nieve
    # Excluir: 1=saturado, 2=oscuro, 3=sombra, 8=media confianza, 9=alta confianza, 10=cirrus
    mascara = scl.remap(
        [4, 5, 6, 11],
        [1, 1, 1,  1],
        defaultValue=0,
    )
    return imagen.updateMask(mascara)


# ---------------------------------------------------------------------------
# TAREA 2: Escucha SQS y logica ecologica
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def procesar_resultado_sagemaker(self):
    """
    Tarea escucha: lee mensajes de la cola SQS que notifica resultados
    de SageMaker, descarga el .npz desde S3 y aplica logica ecologica.

    Esta tarea debe ejecutarse continuamente (cada N segundos via Beat
    o como worker dedicado).

    Flujo por mensaje:
      1. Extraer OutputLocation del mensaje SQS
      2. Descargar .npz desde S3
      3. Cargar mask, probability, entropy
      4. Calcular score_confianza y tipo_caso
      5. Vectorizar mascara a poligonos (EPSG:4326)
      6. Logica ecologica en casos historicos que intersectan
      7. Calcular nueva deforestacion = nueva - historica (PERTURBADO+RECUPERANDO)
      8. Crear CasoAuditoria si hay nueva deforestacion o alta incertidumbre
      9. Enlazar SectorReserva y despachar SMS via SNS
    """
    sqs    = _get_sqs()
    s3     = _get_s3()
    queue  = settings.AWS_SQS_RESULT_QUEUE_URL

    if not queue:
        logger.warning("[ESCUCHA] SQS_RESULT_QUEUE_URL no configurada.")
        return

    response = sqs.receive_message(
        QueueUrl=queue,
        MaxNumberOfMessages=10,
        WaitTimeSeconds=20,     # Long polling
    )

    mensajes = response.get("Messages", [])

    if not mensajes:
        # Cola vacia: Beat se encarga del proximo disparo (30s)
        return

    for mensaje in mensajes:
        receipt_handle = mensaje["ReceiptHandle"]
        try:
            _procesar_mensaje_sqs(mensaje, s3)
            sqs.delete_message(QueueUrl=queue, ReceiptHandle=receipt_handle)
        except Exception as e:
            logger.error(f"[ESCUCHA] Error procesando mensaje SQS: {e}")

    # Cola activa: auto-reagendar en 5s sin esperar el ciclo de Beat (30s)
    procesar_resultado_sagemaker.apply_async(countdown=5)
            # El mensaje volvera a estar disponible tras el visibility timeout


def _procesar_mensaje_sqs(mensaje, s3):
    """Procesa un mensaje individual de la cola SQS."""
    body = json.loads(mensaje["Body"])

    # SageMaker Async notifica via SNS->SQS con este formato
    if "Message" in body:
        body = json.loads(body["Message"])

    # SageMaker async notifica con responseParameters.outputLocation
    output_location = (
        body.get("responseParameters", {}).get("outputLocation")
        or body.get("outputLocation", "")
    )
    if not output_location:
        logger.warning(f"[ESCUCHA] Mensaje sin outputLocation: {body}")
        return

    # Ignorar notificaciones de prueba
    if body.get("eventName") == "TestNotification":
        return

    # Parsear s3://bucket/key del output
    output_location = output_location.replace("s3://", "")
    bucket, key     = output_location.split("/", 1)

    # Buscar el ParcheProcesamiento por inputLocation (más fiable que outputLocation)
    input_location = body.get("requestParameters", {}).get("inputLocation", "")
    parche = None
    if input_location:
        # inputLocation = s3://bucket/sagemaker-inputs/captura_X/parche_R_C.npy
        try:
            parche = ParcheProcesamiento.objects.get(s3_path_tensor=input_location)
        except ParcheProcesamiento.DoesNotExist:
            pass

    if parche is None:
        # Fallback: buscar por s3_path_resultado
        try:
            parche = ParcheProcesamiento.objects.get(
                s3_path_resultado__contains=key.rsplit("/", 1)[-1].split(".")[0]
            )
        except ParcheProcesamiento.DoesNotExist:
            logger.error(f"[ESCUCHA] No se encontro parche para output: {key}")
            return

    # Guardar output location en el parche
    parche.s3_path_resultado = f"s3://{bucket}/{key}"
    parche.save(update_fields=["s3_path_resultado"])

    # -- 1. Descargar y cargar .npz --
    npz_response = s3.get_object(Bucket=bucket, Key=key)
    npz_bytes    = npz_response["Body"].read()
    datos        = np.load(io.BytesIO(npz_bytes))

    mask    = datos["mask"][0, 0]        # [128, 128]
    prob    = datos["probability"][0, 0] # [128, 128]
    entropy = datos["entropy"][0, 0]     # [128, 128]

    # ── MODO TEST: inyectar deteccion sintetica si el modelo devuelve ceros ──
    # Poner en True solo para pruebas de flujo. DESACTIVADO en produccion.
    DEBUG_FORCE_DETECTION = False
    ya_hay_caso = CasoAuditoria.objects.filter(
        tipo_caso=CasoAuditoria.TipoCaso.DETECCION
    ).exclude(pk=1).exists()  # pk=1 es el caso manual de prueba
    if DEBUG_FORCE_DETECTION and mask.max() == 0 and not ya_hay_caso:
        # Simular una zona deforestada de ~20x20px en el centro del parche
        cx, cy = 64, 64
        mask[cy-10:cy+10, cx-10:cx+10] = 1.0
        prob[cy-10:cy+10, cx-10:cx+10] = 0.87
        entropy[:] = 0.05  # baja entropia → alta confianza
        logger.warning("[ESCUCHA][TEST] Deteccion sintetica inyectada en parche %s", parche.pk)
    # ── FIN MODO TEST ─────────────────────────────────────────────────────────

    # -- 2. Calcular score_confianza y tipo_caso --
    mean_entropy   = float(entropy.mean())
    score_confianza = float(1 - (mean_entropy / LN2))
    tipo_caso = (
        CasoAuditoria.TipoCaso.INCERTIDUMBRE
        if mean_entropy > 0.5 * LN2
        else CasoAuditoria.TipoCaso.DETECCION
    )

    # Actualizar estado del parche
    parche.estado_sagemaker = ParcheProcesamiento.EstadoSageMaker.PROCESADO
    parche.fecha_respuesta  = timezone.now()
    parche.save(update_fields=["estado_sagemaker", "fecha_respuesta"])

    # -- 2b. Generar visualizaciones PNG (reemplaza AWS Lambda) --
    # Sube a sagemaker-visualizations/captura_X/parche_R_C_{rgb,mask}.png
    # con la misma convencion de keys que la Lambda intentaba usar.
    # Si falla, se loguea warning pero NO se interrumpe el flujo principal.
    try:
        from PIL import Image as _Image
        npy_key = parche.s3_path_tensor.replace("s3://", "").split("/", 1)[1]
        npy_resp = s3.get_object(Bucket=settings.AWS_S3_BUCKET_NAME, Key=npy_key)
        tensor = np.load(io.BytesIO(npy_resp["Body"].read()))   # [1, 9, 128, 128]

        def _stretch(canal):
            p2, p98 = np.percentile(canal, (2, 98))
            return (np.clip(canal, p2, p98) - p2) / (p98 - p2 + 1e-8) * 255

        r = _stretch(tensor[0, 2]).astype(np.uint8)   # canal Red
        g = _stretch(tensor[0, 1]).astype(np.uint8)   # canal Green
        b = _stretch(tensor[0, 0]).astype(np.uint8)   # canal Blue
        rgb_arr = np.stack((r, g, b), axis=-1)

        # Capa de IA: rojo con alpha = probabilidad
        alpha = (prob * 255).astype(np.uint8)
        rgba_arr = np.stack((
            np.full((128, 128), 255, dtype=np.uint8),
            np.zeros((128, 128), dtype=np.uint8),
            np.zeros((128, 128), dtype=np.uint8),
            alpha,
        ), axis=-1)

        base = f"sagemaker-visualizations/captura_{parche.captura_id}/parche_{parche.fila_idx}_{parche.col_idx}"
        rgb_buf = io.BytesIO()
        _Image.fromarray(rgb_arr, "RGB").save(rgb_buf, format="PNG")
        rgb_buf.seek(0)
        mask_buf = io.BytesIO()
        _Image.fromarray(rgba_arr, "RGBA").save(mask_buf, format="PNG")
        mask_buf.seek(0)

        s3.put_object(
            Bucket=settings.AWS_S3_BUCKET_NAME,
            Key=f"{base}_rgb.png",
            Body=rgb_buf.getvalue(),
            ContentType="image/png",
        )
        s3.put_object(
            Bucket=settings.AWS_S3_BUCKET_NAME,
            Key=f"{base}_mask.png",
            Body=mask_buf.getvalue(),
            ContentType="image/png",
        )
        logger.info(
            f"[VISUAL] PNGs generados para captura={parche.captura_id} "
            f"parche=[{parche.fila_idx},{parche.col_idx}]"
        )
    except Exception as e:
        logger.warning(
            f"[VISUAL] No se pudieron generar PNGs para parche {parche.pk}: {e}"
        )

    # -- 3. Vectorizar mascara a poligonos --
    poligonos_nuevos = _vectorizar_mascara(mask, parche)

    # -- 3b. Descartar detecciones concentradas en bordes (>75% en margen 8px) --
    if poligonos_nuevos:
        MARGIN = 8
        total_px = mask.sum()
        border_mask = np.zeros_like(mask, dtype=bool)
        border_mask[:MARGIN, :] = True
        border_mask[-MARGIN:, :] = True
        border_mask[:, :MARGIN] = True
        border_mask[:, -MARGIN:] = True
        border_px = (mask * border_mask).sum()
        if total_px > 0 and (border_px / total_px) > 0.75:
            poligonos_nuevos = []
            logger.info(
                f"[ESCUCHA] Deteccion descartada por concentracion en bordes "
                f"({border_px:.0f}/{total_px:.0f} px, {border_px/total_px*100:.0f}%% en borde)"
            )

    # -- 3c. Descartar detecciones con area < 3 hectareas (ruido disperso) --
    if poligonos_nuevos:
        area_px = mask.sum()
        area_ha = area_px * 0.01  # 10m x 10m = 100m2 = 0.01 Ha
        if area_ha < AREA_MINIMA_HA:
            poligonos_nuevos = []
            logger.info(
                f"[ESCUCHA] Deteccion descartada por area minima: "
                f"{area_ha:.2f} Ha < {AREA_MINIMA_HA:.1f} Ha"
            )

    # -- 4. Logica ecologica en casos historicos --
    _aplicar_logica_ecologica(parche, poligonos_nuevos)

    # -- 5. Diferencia espacial: nueva - historica (solo DETECCION) --
    geom_nueva_neta = _calcular_diferencia_espacial(poligonos_nuevos)

    # -- 5b. Umbral de area sobre el DELTA neta (G2).
    # El filtro de 3c trabaja sobre la mascara cruda, asi que los slivers de
    # registro entre pasadas la pasan igual. Aqui se mide lo que realmente
    # queda despues de restar la deforestacion historica.
    if geom_nueva_neta is not None:
        area_neta_ha = _area_ha(geom_nueva_neta)
        if area_neta_ha < AREA_MINIMA_HA:
            logger.info(
                f"[ESCUCHA] Delta neto descartado por area minima: "
                f"{area_neta_ha:.4f} Ha < {AREA_MINIMA_HA:.1f} Ha"
            )
            geom_nueva_neta = None

    # -- 6. Crear o deduplicar CasoAuditoria --
    captura = parche.captura

    if geom_nueva_neta is not None and not geom_nueva_neta.empty:
        _crear_o_actualizar_caso(
            parche=parche,
            captura=captura,
            tipo_caso=CasoAuditoria.TipoCaso.DETECCION,
            score_confianza=score_confianza,
            geom_nuevo=geom_nueva_neta,
            alertar=True,
        )
    elif tipo_caso == CasoAuditoria.TipoCaso.INCERTIDUMBRE and poligonos_nuevos:
        # La incertidumbre se deduplica por REGISTRO contra otros
        # INCERTIDUMBRE abiertos que se solapen: una misma zona ambigua no
        # genera un caso nuevo en cada pasada, solo mueve la ultima deteccion.
        _crear_o_actualizar_caso(
            parche=parche,
            captura=captura,
            tipo_caso=CasoAuditoria.TipoCaso.INCERTIDUMBRE,
            score_confianza=score_confianza,
            geom_nuevo=_union_geoms(poligonos_nuevos),
            alertar=False,
        )
    elif tipo_caso == CasoAuditoria.TipoCaso.INCERTIDUMBRE:
        logger.info(
            "[ESCUCHA] Incertidumbre sin poligonos en parche %s: no se crea "
            "caso (sin evidencia espacial deduplicable).",
            parche.pk,
        )


def _vectorizar_mascara(mask, parche):
    """
    Convierte la mascara binaria [128, 128] a una lista de poligonos GeoJSON
    en EPSG:4326, usando el footprint geografico del parche.
    """
    from django.contrib.gis.geos import GEOSGeometry
    import pyproj

    # Obtener bounds del parche en EPSG:4326
    geom_parche = parche.geom  # PolygonField SRID=4326
    bounds      = geom_parche.extent  # (min_lon, min_lat, max_lon, max_lat)

    # Crear transform en EPSG:4326 (para la vectorizacion directa)
    transform_4326 = from_bounds(
        bounds[0], bounds[1], bounds[2], bounds[3],
        128, 128
    )

    mascara_uint8 = mask.astype(np.uint8)
    poligonos = []

    for geom_dict, valor in rasterio_shapes(mascara_uint8, transform=transform_4326):
        if valor == 1:
            poligonos.append(GEOSGeometry(json.dumps(geom_dict), srid=4326))

    return poligonos


def _aplicar_logica_ecologica(parche, poligonos_nuevos):
    """
    Para cada CasoAuditoria historico que intersecta el parche:
      - Si la IA NO detecta deforestacion: +1 ciclo limpio
      - Si la IA SI detecta deforestacion: reinicia ciclos a 0

    Fase G4: el control "una sola vez por captura" se hace con
    CasoAuditoria.captura_ultimo_ciclo en base de datos, no con un set en
    memoria. Asi es correcto aunque el worker se reinicie, aunque lleguen dos
    mensajes de SQS en paralelo, aunque Celery reintente la tarea y aunque se
    reduzca STRIDE por debajo de PATCH_SIZE (parches que se solapan).
    """
    hay_deforestacion = len(poligonos_nuevos) > 0
    captura_actual = parche.captura

    casos_historicos = CasoAuditoria.objects.filter(
        estado_ecologico__in=[
            CasoAuditoria.EstadoEcologico.PERTURBADO,
            CasoAuditoria.EstadoEcologico.RECUPERANDO,
        ],
        parche__geom__intersects=parche.geom,
    ).exclude(geom_afectada__isnull=True).exclude(
        # Los INCERTIDUMBRE no participan en los ciclos de recuperacion
        tipo_caso=CasoAuditoria.TipoCaso.INCERTIDUMBRE,
    )

    for caso in casos_historicos:
        # Ya fue contabilizado en esta misma pasada: no doble-conteo
        if caso.captura_ultimo_ciclo_id == captura_actual.pk:
            continue

        if hay_deforestacion:
            caso.reiniciar_ciclo()
            logger.info(f"[ECOLOGIA] Caso {caso.pk}: ciclo reiniciado (deforestacion detectada)")
        else:
            caso.incrementar_ciclo_limpio()
            logger.info(
                f"[ECOLOGIA] Caso {caso.pk}: ciclo limpio "
                f"({caso.ciclos_limpios_consecutivos}) "
                f"estado={caso.estado_ecologico}"
            )

        caso.captura_ultimo_ciclo = captura_actual
        caso.save(update_fields=["captura_ultimo_ciclo", "fecha_actualizacion"])


def _calcular_diferencia_espacial(poligonos_nuevos):
    """
    Nueva deforestacion neta = poligonos nuevos - casos historicos PERTURBADO/RECUPERANDO.

    Usa PostGIS via Django ORM para calcular la diferencia espacial.
    Retorna MultiPolygon GEOSGeometry con la zona nueva, o None si no hay.
    """
    if not poligonos_nuevos:
        return None

    from django.contrib.gis.geos import MultiPolygon as GEOSMultiPolygon
    from django.contrib.gis.db.models import Union as GEOSUnion

    # Union de todos los poligonos nuevos detectados
    if len(poligonos_nuevos) == 1:
        union_nueva = poligonos_nuevos[0]
    else:
        union_nueva = poligonos_nuevos[0]
        for p in poligonos_nuevos[1:]:
            union_nueva = union_nueva.union(p)

    # Union de la deforestacion historica activa.
    # IMPORTANTE: se excluyen los INCERTIDUMBRE. Desde la Fase G2 esos casos
    # tienen geometria propia; si entraran aqui, su poligono difuso ENMASCARARIA
    # deforestacion real nueva dentro de el y la pasada dejaria de alertar.
    historicos = CasoAuditoria.objects.filter(
        tipo_caso=CasoAuditoria.TipoCaso.DETECCION,
        estado_ecologico__in=[
            CasoAuditoria.EstadoEcologico.PERTURBADO,
            CasoAuditoria.EstadoEcologico.RECUPERANDO,
        ],
        geom_afectada__intersects=union_nueva,
    ).exclude(geom_afectada__isnull=True)

    if not historicos.exists():
        return union_nueva

    union_historica = historicos.aggregate(
        union=GEOSUnion("geom_afectada")
    )["union"]

    if union_historica is None:
        return union_nueva

    # Diferencia espacial: lo que es nuevo y no estaba antes
    diferencia = union_nueva.difference(union_historica)

    if diferencia.empty or diferencia.area == 0:
        return None

    return diferencia


def _a_multipoligono(geom):
    """Normaliza una geometria al MultiPolygon que exige geom_afectada."""
    if geom is None or geom.empty:
        return None
    if geom.geom_type == "MultiPolygon":
        return geom
    if geom.geom_type == "Polygon":
        return GEOSGeometry(
            json.dumps({"type": "MultiPolygon", "coordinates": [geom.coords]}),
            srid=4326,
        )
    if geom.geom_type == "GeometryCollection":
        partes = []
        for parte in geom:
            if parte.geom_type == "Polygon":
                partes.append(parte.coords)
            elif parte.geom_type == "MultiPolygon":
                partes.extend(g.coords for g in parte)
        if not partes:
            return None
        return GEOSGeometry(
            json.dumps({"type": "MultiPolygon", "coordinates": partes}),
            srid=4326,
        )
    return None


def _area_ha(geom):
    """Area de una geometria EPSG:4326 en hectareas (proyecta a UTM 19S)."""
    if geom is None or geom.empty:
        return 0.0
    try:
        return geom.transform(SRID_METRICO, clone=True).area / 10_000.0
    except Exception:
        return 0.0


def _union_geoms(poligonos):
    """Union de una lista de geometrias. Devuelve None si la lista esta vacia."""
    if not poligonos:
        return None
    union = poligonos[0]
    for poligono in poligonos[1:]:
        union = union.union(poligono)
    return union


def _buscar_caso_abierto(tipo_caso, probe_geom):
    """
    Devuelve el caso ABIERTO del mismo tipo cuya geometria se solape con
    probe_geom, o None.

    Busca en TODAS las capturas (dedup entre pasadas). Solo se consideran
    tipos localizables (DETECCION / INCERTIDUMBRE) con geometria: los casos
    sin poligono no tienen donde anclarse y por tanto no son deduplicables.
    """
    if probe_geom is None or probe_geom.empty:
        return None

    abiertos = [
        CasoAuditoria.EstadoCaso.PENDIENTE_REVISION,
        CasoAuditoria.EstadoCaso.MONITOREO_ACTIVO,
        CasoAuditoria.EstadoCaso.VALIDADO_POSITIVO,
    ]
    # estado_ecologico restringe el conjunto al MISMO filtro que usa
    # _calcular_diferencia_espacial. Asi el conjunto del record-check queda
    # contenido en el de la resta geometrica: el delta nunca puede "robarle"
    # area a un caso que la resta no haya eliminado, y los casos RECUPERADOS
    # (ver decision 2 del diseno) siempre abren uno nuevo.
    return (
        CasoAuditoria.objects
        .filter(
            tipo_caso=tipo_caso,
            estado_caso__in=abiertos,
            estado_ecologico__in=[
                CasoAuditoria.EstadoEcologico.PERTURBADO,
                CasoAuditoria.EstadoEcologico.RECUPERANDO,
            ],
            geom_afectada__intersects=probe_geom,
        )
        .exclude(geom_afectada__isnull=True)
        .order_by("fecha_creacion")
        .first()
    )


def _registrar_redeteccion(caso, captura, score_confianza, geom_nuevo):
    """
    Marca un caso existente como re-detectado en la pasada `captura`:
    actualiza ultima deteccion, contador de pasadas, score maximo y
    (opcionalmente) engloba la nueva geometria dentro de la suya.
    """
    caso.captura_ultima_deteccion = captura
    caso.veces_detectado = (caso.veces_detectado or 1) + 1
    caso.score_confianza = max(
        float(caso.score_confianza or 0.0), float(score_confianza)
    )

    campos = [
        "captura_ultima_deteccion", "veces_detectado", "score_confianza",
        "fecha_actualizacion",
    ]

    if geom_nuevo is not None and not geom_nuevo.empty:
        base = caso.geom_afectada
        if base is None:
            nueva = _a_multipoligono(geom_nuevo)
        else:
            nueva = _a_multipoligono(base.union(geom_nuevo))
        if nueva is not None:
            caso.geom_afectada = nueva
            campos.append("geom_afectada")

    caso.save(update_fields=campos)
    return caso


def _crear_o_actualizar_caso(
    parche, captura, tipo_caso, score_confianza, geom_nuevo, alertar,
):
    """
    Crea el CasoAuditoria o, si ya existe uno abierto solapado de ese tipo,
    lo actualiza y devuelve ese (dedup entre pasadas).

    Devuelve (caso, es_nuevo). Sin geometria no hay donde anclarse y no se
    puede deduplicar, asi que no se crea nada.
    """
    if geom_nuevo is None or geom_nuevo.empty:
        return None, False

    existente = _buscar_caso_abierto(tipo_caso, geom_nuevo)
    if existente is not None:
        _registrar_redeteccion(existente, captura, score_confianza, geom_nuevo)
        logger.info(
            f"[CASO] Re-deteccion de CasoAuditoria {existente.pk} "
            f"(tipo={tipo_caso}, veces={existente.veces_detectado}) en "
            f"captura {captura.fecha_adquisicion}: NO se crea duplicado."
        )
        return existente, False

    caso = _crear_caso_auditoria(parche, tipo_caso, score_confianza, geom_nuevo)

    # Fase G1: todo caso nuevo queda vinculado a la captura en la que nace y
    # a la ultima pasada en la que fue visto.
    caso.captura_nacimiento = captura
    caso.captura_ultima_deteccion = captura
    caso.captura_ultimo_ciclo = captura
    caso.veces_detectado = 1
    caso.save(update_fields=[
        "captura_nacimiento", "captura_ultima_deteccion",
        "captura_ultimo_ciclo", "veces_detectado",
    ])

    if alertar:
        _enlazar_sectores_y_alertar(caso)
        # Cambiar a MONITOREO_ACTIVO DESPUES de asignar sectores
        # para que el signal SMS encuentre los sectores ya enlazados
        caso._desde_pipeline = True
        caso.estado_caso = CasoAuditoria.EstadoCaso.MONITOREO_ACTIVO
        caso.save(update_fields=["estado_caso"])

    return caso, True


def _crear_caso_auditoria(parche, tipo_caso, score_confianza, geom_nueva):
    """Crea el registro CasoAuditoria en base de datos."""
    geom_multi = _a_multipoligono(geom_nueva)

    # Estado inicial segun tipo de caso:
    # INCERTIDUMBRE -> requiere validacion humana
    # DETECCION     -> monitoreo automatico activo
    # Siempre crear en PENDIENTE_REVISION; el caller lo sube a MONITOREO_ACTIVO
    # despues de asignar sectores, para que el signal SMS funcione correctamente.
    estado_inicial = CasoAuditoria.EstadoCaso.PENDIENTE_REVISION

    caso = CasoAuditoria(
        parche=parche,
        tipo_caso=tipo_caso,
        estado_caso=estado_inicial,
        score_confianza=score_confianza,
        geom_afectada=geom_multi,
        estado_ecologico=CasoAuditoria.EstadoEcologico.PERTURBADO,
        ciclos_limpios_consecutivos=0,
    )
    caso._desde_pipeline = True  # evitar doble SMS del signal
    caso.save()
    logger.info(
        f"[CASO] Creado CasoAuditoria {caso.pk} "
        f"tipo={tipo_caso} score={score_confianza:.3f}"
    )
    return caso


# ---------------------------------------------------------------------------
# TAREA 2b: Cierre automatico de INCERTIDUMBRE (Fase G3 - Celery Beat diaria)
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def cerrar_incertidumbres_obsoletas(self):
    """
    Fase G3: cierra los casos INCERTIDUMBRE que no se han vuelto a detectar
    en `umbral_cierre_incertidumbre_quincenas` pasadas terminadas.

    Idempotente por diseno: no existe un contador incrementable. El umbral se
    evalua con un count() de capturas posteriores a la ultima deteccion, asi
    que ejecutar la tarea N veces deja exactamente el mismo resultado.

    No toca los VALIDADO_POSITIVO: un tecnico ya confirmo ese punto en campo.
    """
    umbral = ConfiguracionGlobal.get().umbral_cierre_incertidumbre_quincenas
    if umbral <= 0:
        logger.info("[CIERRE] umbral de cierre de INCERTIDUMBRE = 0: deshabilitado")
        return {"cerrados": 0, "umbral": umbral, "habilitado": False}

    abiertos = CasoAuditoria.objects.filter(
        tipo_caso=CasoAuditoria.TipoCaso.INCERTIDUMBRE,
        estado_caso__in=[
            CasoAuditoria.EstadoCaso.PENDIENTE_REVISION,
            CasoAuditoria.EstadoCaso.MONITOREO_ACTIVO,
        ],
    ).select_related("captura_ultima_deteccion")

    terminadas = CapturaSatelital.objects.exclude(
        estado_liberacion=CapturaSatelital.EstadoLiberacion.PROCESANDO
    )
    cerrados = 0
    hoy = timezone.now().date()

    for caso in abiertos:
        if caso.captura_ultima_deteccion_id:
            fecha_ref = caso.captura_ultima_deteccion.fecha_adquisicion
        else:
            fecha_ref = caso.fecha_creacion.date()

        pasadas_desde = terminadas.filter(fecha_adquisicion__gt=fecha_ref).count()
        if pasadas_desde < umbral:
            continue

        caso.estado_caso       = CasoAuditoria.EstadoCaso.RECUPERADO
        caso.estado_ecologico  = CasoAuditoria.EstadoEcologico.RECUPERADO
        caso.fecha_recuperacion = hoy
        caso.save(update_fields=[
            "estado_caso", "estado_ecologico", "fecha_recuperacion",
            "fecha_actualizacion",
        ])
        cerrados += 1
        logger.info(
            f"[CIERRE] Caso INCERTIDUMBRE {caso.pk} cerrado: "
            f"{pasadas_desde} pasadas sin deteccion (umbral {umbral})."
        )

    if not cerrados:
        logger.info(
            "[CIERRE] Ningun INCERTIDUMBRE supera el umbral de %s pasadas.", umbral
        )
    return {"cerrados": cerrados, "umbral": umbral, "habilitado": True}


# ---------------------------------------------------------------------------
# TAREA 3: Reporte mensual (Celery Beat - dia 1 de cada mes a las 04:00)
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=2, default_retry_delay=600)
def generar_reporte_mensual(self):
    """
    Genera un CSV con el resumen del mes anterior y lo sube a S3.
    Crea un registro DocumentoReporte en base de datos.

    Ejecutada el dia 1 de cada mes a las 04:00 Lima.
    """
    hoy   = datetime.now()
    # Mes anterior
    if hoy.month == 1:
        anio_rep = hoy.year - 1
        mes_rep  = 12
    else:
        anio_rep = hoy.year
        mes_rep  = hoy.month - 1

    logger.info(f"[REPORTE] Generando reporte mensual {anio_rep}/{mes_rep:02d}")

    # -- Consulta de casos --
    casos = CasoAuditoria.objects.filter(
        fecha_creacion__year=anio_rep,
        fecha_creacion__month=mes_rep,
        estado_caso__in=[
            CasoAuditoria.EstadoCaso.VALIDADO_POSITIVO,
            CasoAuditoria.EstadoCaso.RECUPERADO,
        ],
    ).select_related("parche", "parche__captura")

    n_validados   = casos.filter(estado_caso=CasoAuditoria.EstadoCaso.VALIDADO_POSITIVO).count()
    n_recuperados = casos.filter(estado_caso=CasoAuditoria.EstadoCaso.RECUPERADO).count()
    n_sms         = RegistroSMS.objects.filter(
        fecha_envio__year=anio_rep,
        fecha_envio__month=mes_rep,
        estado=RegistroSMS.EstadoSMS.ENVIADO,
    ).count()

    # -- Generar CSV en memoria --
    buf = io.StringIO()
    writer = csv.writer(buf)

    # Cabecera resumen
    writer.writerow(["REPORTE MENSUAL APU GUARD"])
    writer.writerow([f"Periodo: {anio_rep}/{mes_rep:02d}"])
    writer.writerow([f"Detecciones confirmadas (VALIDADO_POSITIVO): {n_validados}"])
    writer.writerow([f"Sectores recuperados: {n_recuperados}"])
    writer.writerow([f"SMS enviados: {n_sms}"])
    writer.writerow([])

    # Detalle por caso
    writer.writerow(["ID", "Fecha", "Estado", "Tipo", "Score Confianza"])
    for caso in casos.order_by("fecha_creacion"):
        writer.writerow([
            caso.pk,
            caso.fecha_creacion.strftime("%Y-%m-%d %H:%M"),
            caso.estado_caso,
            caso.tipo_caso,
            f"{caso.score_confianza:.4f}",
        ])

    csv_bytes = buf.getvalue().encode("utf-8")

    # -- Subir a S3 --
    s3_key = f"apuguard-reports/{anio_rep}/{mes_rep:02d}/reporte_mensual.csv"
    s3     = _get_s3()
    try:
        s3.put_object(
            Bucket=settings.AWS_S3_BUCKET_NAME,
            Key=s3_key,
            Body=csv_bytes,
            ContentType="text/csv",
        )
        logger.info(f"[REPORTE] CSV subido a s3://{settings.AWS_S3_BUCKET_NAME}/{s3_key}")
    except Exception as exc:
        logger.error(f"[REPORTE] Error subiendo CSV: {exc}")
        raise self.retry(exc=exc)

    # -- Registro en base de datos --
    DocumentoReporte.objects.update_or_create(
        anio=anio_rep,
        mes=mes_rep,
        defaults={
            "s3_key": s3_key,
            "casos_validados": n_validados,
            "casos_recuperados": n_recuperados,
            "total_sms_enviados": n_sms,
        },
    )
    logger.info(f"[REPORTE] DocumentoReporte {anio_rep}/{mes_rep:02d} guardado en BD.")


# ---------------------------------------------------------------------------
# TAREA 4: Garbage Collection S3 (Celery Beat - semanal, lunes 02:00)
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def limpiar_archivos_temporales_s3(self):
    """
    Elimina de S3 todos los archivos de inferencia con mas de 30 dias de
    antiguedad en los prefijos:
      - sagemaker-inputs/
      - sagemaker-outputs/
      - sagemaker-visualizations/

    Los registros en PostgreSQL se conservan intactos.
    """
    PREFIJOS = [
        settings.S3_PREFIX_SAGEMAKER_IN,
        settings.S3_PREFIX_SAGEMAKER_OUT,
        "sagemaker-visualizations/",
    ]
    LIMITE_DIAS = 30
    bucket      = settings.AWS_S3_BUCKET_NAME
    s3          = _get_s3()
    ahora       = datetime.now(tz=dt_timezone.utc)
    limite      = ahora - timedelta(days=LIMITE_DIAS)

    total_eliminados = 0

    for prefijo in PREFIJOS:
        logger.info(f"[GC] Escaneando prefijo: {prefijo}")
        paginator  = s3.get_paginator("list_objects_v2")
        a_eliminar = []

        for page in paginator.paginate(Bucket=bucket, Prefix=prefijo):
            for obj in page.get("Contents", []):
                if obj["LastModified"] < limite:
                    a_eliminar.append({"Key": obj["Key"]})

                    # Borrar en batch de 1000 (limite de AWS)
                    if len(a_eliminar) == 1000:
                        s3.delete_objects(
                            Bucket=bucket,
                            Delete={"Objects": a_eliminar, "Quiet": True},
                        )
                        total_eliminados += len(a_eliminar)
                        a_eliminar = []

        # Borrar el resto del batch
        if a_eliminar:
            s3.delete_objects(
                Bucket=bucket,
                Delete={"Objects": a_eliminar, "Quiet": True},
            )
            total_eliminados += len(a_eliminar)

    logger.info(f"[GC] Garbage Collection completado: {total_eliminados} archivos eliminados.")


def _enlazar_sectores_y_alertar(caso):
    """
    Para un DETECCION:
      1. Enlaza los SectorReserva que intersectan geometricamente con geom_afectada
      2. Despacha SMS via AWS SNS a todos los TecnicoCampo asignados
    """
    if caso.geom_afectada is None:
        return

    sectores = SectorReserva.objects.filter(
        geom__intersects=caso.geom_afectada,
        activo=True,
    )
    caso.sectores.set(sectores)

    twilio = _get_twilio()

    tecnicos_notificados = set()
    for sector in sectores:
        for tecnico in sector.tecnicos.filter(activo=True):
            if tecnico.pk in tecnicos_notificados:
                continue
            tecnicos_notificados.add(tecnico.pk)

            mensaje_texto = (
                f"ALERTA APU GUARD\n"
                f"Sector: {sector.nombre}\n"
                f"Tipo: Deteccion de deforestacion\n"
                f"Confianza: {caso.score_confianza:.0%}\n"
                f"Fecha: {caso.fecha_creacion.strftime('%d/%m/%Y %H:%M')}\n"
                f"Caso ID: {caso.pk}"
            )

            estado_sms = RegistroSMS.EstadoSMS.PENDIENTE
            sns_id     = ""
            error      = ""

            if not tecnico.telefono:
                logger.warning(f"[SMS] Tecnico {tecnico} sin numero de telefono, omitiendo.")
                continue

            try:
                # Envio via Twilio al numero del tecnico
                # El numero debe estar en formato E.164: +51987654321
                msg = twilio.messages.create(
                    body=mensaje_texto,
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=tecnico.telefono,
                )
                sns_id     = msg.sid
                estado_sms = RegistroSMS.EstadoSMS.ENVIADO
                logger.info(f"[SMS] Enviado a {tecnico} ({tecnico.telefono}): {msg.sid}")

            except Exception as e:
                estado_sms = RegistroSMS.EstadoSMS.FALLIDO
                error      = str(e)
                logger.error(f"[SMS] Error enviando a {tecnico} ({tecnico.telefono}): {e}")

            RegistroSMS.objects.create(
                caso=caso,
                tecnico=tecnico,
                mensaje=mensaje_texto,
                estado=estado_sms,
                sns_message_id=sns_id,
                error_detalle=error,
            )
