# APU GUARD - Sistema de Deteccion de Deforestacion (Tambopata, Peru)

Pipeline de vision artificial que detecta deforestacion automaticamente usando imagenes Sentinel-2 (descargadas de AWS via STAC), inferencia SageMaker y alertas SMS via Twilio sobre la Reserva Nacional Tambopata (Madre de Dios, Peru).

---

## Ultimas iteraciones

* **Modelo final ya validado**: se incluye la entrega final de HRNet (codigo en
  `model_source/`), auditada y verificada contra el contrato de inferencia
  **v10** (canales 6-8 estirados a `[-1, 1]` con percentiles P2-P98),
  sustituyendo la normalizacion `BIAS_CORRECTION` de las versiones anteriores.
* **Despliegue a produccion**: el pipeline completo (adquisicion STAC ->
  SageMaker -> SQS -> Django -> frontend) esta **desplegado y operativo en
  AWS**; ver [Produccion en AWS](#produccion-en-aws) y
  [`infra/README.md`](infra/README.md).

---

## Tabla de contenidos

1. [Arquitectura](#arquitectura)
2. [Produccion en AWS](#produccion-en-aws)
3. [Prerrequisitos](#prerrequisitos)
4. [Setup inicial en 5 minutos](#setup-inicial-en-5-minutos)
5. [Uso diario](#uso-diario)
6. [Pruebas y diagnostico](#pruebas-y-diagnostico)
7. [Estructura del proyecto](#estructura-del-proyecto)
8. [Troubleshooting](#troubleshooting)

---

## Arquitectura

```
STAC / AWS (Sentinel-2)  ->  S3 (raw rasters)
                       |
                       v
              Celery (preprocessing)
                       |
                       v
              SageMaker Async (inferencia)
                       |
                       v
                  SQS (resultados)
                       |
                       v
        Celery (postprocessing + logica ecologica)
                       |
                       v
            Django REST API (CasoAuditoria)
                       |
                       v
                Twilio SMS a tecnicos
```

**Servicios Docker (definidos en `docker-compose.yml`):**

| Servicio | Descripcion | Puerto |
|----------|-------------|--------|
| `db` | PostgreSQL 16 + PostGIS 3.4 | 5433 (host) → 5432 (interno) |
| `redis` | Broker de Celery | 6379 |
| `web` | Django 4.2 + DRF + JWT | 8000 |
| `celery_worker` | Procesamiento ML en background | - |
| `celery_beat` | Scheduler automatico (cron) | - |
| `frontend` | Angular 18 (con hot-reload) | 4200 |

**Automatizacion (Celery Beat):**
- Dias **1 y 16** de cada mes a las **03:00 Lima** -> `procesar_quincena_tambopata`
- Cada **30 segundos** -> `procesar_resultado_sagemaker` (escucha SQS)
- Dia **1** de cada mes a las **04:00 Lima** -> `generar_reporte_mensual`
- Cada **lunes 02:00 Lima** -> `limpiar_archivos_temporales_s3`

---

## Produccion en AWS

El sistema esta desplegado en `us-east-1` (cuenta AWS propia; credenciales
fuera del repositorio).
Arquitectura, costes, orden de ejecucion y verificacion:
[`infra/README.md`](infra/README.md).

| | |
|---|---|
| URL | <https://<cloudfront-domain>.cloudfront.net> |
| Instancia | `t3.small` + Amazon Linux 2023 + gp3 20 GB + IMDSv2 |
| IP fija | `<ip-publica>` (Elastic IP, se conserva al parar) |
| Region | `us-east-1` |

**Diferencias con el entorno local de las secciones siguientes:**

| | Desarrollo (local) | Produccion |
|---|---|---|
| Frontend | `http://localhost:4200` (hot-reload) | CloudFront -> nginx `:80` |
| Django | `runserver` en `:8000` | `gunicorn`, solo red interna |
| Puertos publicados | 5433 (db), 6379, 8000, 4200 | **ninguno** salvo el `:80` del frontend |
| Credenciales AWS | `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` en `.env` | **vacias**: la instancia usa su instance profile |
| Compose | `docker-compose.yml` (+ `.override.yml`) | **siempre** las dos `-f`: `docker-compose.yml` + `docker-compose.prod.yml` |
| Base de datos | datos de desarrollo | migrada desde local con `deploy_migrar_bd.ps1` |

**Desplegar / actualizar:**

```powershell
.\scripts\deploy_paquetear.ps1                       # compila las 4 imagenes en local
.\scripts\deploy_subir.ps1 -Ip <ip-publica>        # sube fuentes + imagenes y arranca
.\scripts\deploy_migrar_bd.ps1 -Ip <ip-publica>    # BD dev -> prod + copia en S3
```

**Verificar** (dentro del servidor):

```bash
ssh -i ~/.ssh/apuguard-ec2.pem ec2-user@<ip-publica>
cd /opt/apuguard
C="sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml"

$C exec -T web env FRONTEND_BASE=http://frontend:80 HEALTH_PROTO=https \
    python /app/scripts/12_healthcheck.py < /dev/null          # 7/7
$C exec -T web python /app/scripts/25_bootstrap_prod_env.py --verificar < /dev/null
$C exec -T web python /app/scripts/26_smoke_prod_https.py \
    --url https://<cloudfront-domain>.cloudfront.net < /dev/null     # 9/9
```

**Pausar para no gastar**: `aws ec2 stop-instances --instance-ids <i-...>`
deja el compute en 0 (ahorro ~15.7 USD/mes, 75 %); siguen el EBS (~1.6) y
la Elastic IP (~3.6). `aws ec2 start-instances` la reanuda y los 6
contenedores solos vuelven solos (`restart: unless-stopped`).
**No** uses `docker compose stop`: EC2 sigue facturando igual.

---

## Prerrequisitos

Antes de empezar, asegurate de tener:

- **Docker Desktop** instalado y corriendo ([descargar](https://www.docker.com/products/docker-desktop))
- **Credenciales AWS** con acceso a: S3, SageMaker, SQS, SNS
- **Cuenta Twilio** con un numero habilitado para SMS (formato E.164: `+1XXXXXXXXXX`)
- **Bucket S3** con la siguiente estructura creada:

  ```
  s3://tu-bucket/
    raw-rasters/           (se llena en cada quincena)
    sagemaker-inputs/      (se llena en cada quincena)
    sagemaker-outputs/     (lo escribe SageMaker)
    static-layers/         (mineria.tif, rios.tif - 02_generar_static_layers = DEMO;
                            30_generar_static_layers_reales.py = capas reales, deja
                            las demo en static-layers/*-demo.tif)
    sagemaker-visualizations/  (opcional, lo llena la Lambda de visualizacion)
  ```

  En este proyecto el bucket es `s3://apuguard-datalake-prod/` (ademas de las
  carpetas anteriores guarda las copias de la BD en `backups/`).

---

## Setup inicial en 5 minutos

### Paso 1 — Configurar variables de entorno

**Windows (PowerShell o CMD):**
```cmd
copy .env.example backend\.env
copy .env.example .env
notepad backend\.env
```

**Linux / Mac:**
```bash
cp .env.example backend/.env
cp .env.example .env
nano backend/.env
```

Edita `backend/.env` y completa:

| Variable | Ejemplo |
|----------|---------|
| `DJANGO_SECRET_KEY` | (genera una clave aleatoria larga) |
| `AWS_ACCESS_KEY_ID` | `AKIA...` |
| `AWS_SECRET_ACCESS_KEY` | `wxcW...` |
| `AWS_REGION_NAME` | `us-east-1` |
| `AWS_S3_BUCKET` | `apuguard-datalake-prod` |
| `SAGEMAKER_ENDPOINT` | `apuguard-endpoint` |
| `SQS_RESULT_QUEUE_URL` | `https://sqs.us-east-1.amazonaws.com/.../apuguard-inference-queue` |
| `IMAGERY_SOURCE` | `stac` (defecto) o `gee` |
| `IMAGERY_MAX_CLOUD` | `60` (techo opcional de nubosidad, solo STAC) |
| `TWILIO_ACCOUNT_SID` | `AC...` |
| `TWILIO_AUTH_TOKEN` | `0ef2ff96...` |
| `TWILIO_PHONE_NUMBER` | `+17623376420` |

Variables de rendimiento del composite (opcionales, con sus valores por defecto):

| Variable | Defecto | Efecto |
|----------|---------|--------|
| `IMAGERY_WORKERS` | `16` | Hilos de descarga (el cuello de botella es la latencia) |
| `IMAGERY_MEM_MB` | `512` | Memoria maxima por bloque; ajusta `block_rows` automaticamente |
| `IMAGERY_CHUNK_KB` | `1024` | Tamano de chunk de GDAL para `/vsicurl/` |
| `IMAGERY_TMP_DIR` | `/tmp/apuguard` | Carpeta del raster temporal (se borra al terminar) |

### Paso 2 — Origen de las imagenes

Por defecto las imagenes Sentinel-2 se descargan de **Earth Search (AWS)** con
`IMAGERY_SOURCE=stac`: **no requiere credenciales, cuenta ni cuota**, y no usa
Google Earth Engine.

Si quieres volver al flujo historico con GEE:

1. `pip install earthengine-api` dentro de la imagen (o agrega `earthengine-api==0.1.400` a `backend/requirements.txt`).
2. Coloca la clave JSON de tu service account en `backend/gee_key.json`
   (queda en `.gitignore` y lo excluye `.dockerignore`).
3. Activa `GEE_SERVICE_ACCOUNT` y `GEE_KEY_FILE` en `backend/.env`.
4. Pon `IMAGERY_SOURCE=gee`.

### Paso 3 — Levantar y configurar

**Windows:**
```cmd
scripts\setup.bat
```

**Linux / Mac:**
```bash
chmod +x scripts/*.sh
./scripts/setup.sh
```

El script `setup` se encarga de:
1. Levantar `db`, `redis`, `web` con Docker
2. Esperar a que la BD este healthy
3. Crear el usuario administrador (`admin` / `apuguard123`)
4. Cargar los 5 sectores de la Reserva Tambopata
5. (Opcional) Generar `static-layers/mineria.tif` y `static-layers/rios.tif`
   **DEMO** (ruido sintetico). Para produccion usar
   `backend/scripts/30_generar_static_layers_reales.py` (shapefiles reales)
6. Mostrar el estado final del sistema

### Paso 4 — Levantar Celery y Frontend

```bash
docker compose up -d celery_worker celery_beat frontend
```

### Paso 5 — Acceder a la plataforma

| Servicio | URL | Credenciales |
|----------|-----|--------------|
| Frontend Angular | http://localhost:4200 | `admin` / `apuguard123` |
| API REST | http://localhost:8000/api/ | (mismas) |
| Admin Django | http://localhost:8000/admin/ | (mismas) |

---

## Uso diario

### Ver logs en tiempo real

**Windows:**
```cmd
scripts\logs.bat                       REM todos los servicios
scripts\logs.bat celery_worker         REM solo el worker
```

**Linux / Mac:**
```bash
./scripts/logs.sh
./scripts/logs.sh celery_worker
```

### Disparar la IA manualmente (sin esperar al scheduler)

**Windows:**
```cmd
scripts\04_lanzar_quincena.bat
scripts\05_lanzar_escucha.bat
```

**Linux / Mac:**
```bash
./scripts/04_lanzar_quincena.sh
./scripts/05_lanzar_escucha.sh
```

### Crear usuarios adicionales

**Crear otro Administrador** (no es lo habitual, ya existe `admin`):
```bash
./scripts/00_crear_admin.sh --username admin2 --password mipass
```

**Crear un Analista con sectores asignados** (es lo habitual para ampliar el equipo):
```bash
./scripts/00_crear_analista.sh --username juan --password juan123 --sectores SEC-01 SEC-04
```

El Analista solo vera alertas de los sectores SEC-01 y SEC-04 en la plataforma.

---

## Pruebas y diagnostico

### Healthcheck de servicios
```bash
./scripts/12_healthcheck.sh
```
Verifica que los 4 endpoints REST principales, el login por POST, el admin de Django y el frontend respondan correctamente (7 comprobaciones).

### Checklist e2e — adquisicion STAC + pipeline completo

Secuencia para validar el reemplazo de GEE por STAC de punta a punta.

```bash
docker compose up -d --build                       # espera "healthy" en db y redis

# 1. Django carga settings.py y ml_engine.tasks sin errores
docker compose exec web python manage.py check

# 2. Smoke test de descarga (AOI chico, ~40 s) DENTRO del contenedor
#    Verifica tambien el egress del contenedor hacia S3 (us-west-2)
docker compose exec web python /app/scripts/19_descargar_composite_stac.py \
    --bbox "-70.0,-12.9,-69.9,-12.8" --crop 512 -v

# 3. Pipeline completo (descarga -> parches -> SageMaker)
docker compose exec web python /app/scripts/04_lanzar_quincena.py
docker compose logs -f celery_worker
```

Criterios de aceptacion:

- [ ] `manage.py check` -> `System check identified no issues (0 silenced)`
- [ ] Script 19 -> **11/11 `[PASA]`**
- [ ] `CapturaSatelital.s3_path_raw` = `raw-rasters/sentinel2_..._10m.tif` (no un archivo `..._from_gee.tif`)
- [ ] Bandas `B2,B3,B4,B8`, `int16`, `EPSG:32719`, `nodata=0`, 10 m
- [ ] `ParcheProcesamiento` creados con tensores finitos y bbox lon/lat correctos
- [ ] Sin `ERROR` en `docker compose logs celery_worker`
- [ ] `IMAGERY_TMP_DIR` vacio al terminar (el raster temporal se auto-borra)

> La descarga del AOI completo tarda ~38 min (limitado por latencia de red, no por
> CPU). En el contenedor puede ser igual o mayor. Usa `IMAGERY_MAX_CLOUD` para
> recortar escenas si necesitas acortarlo.

### Ver estado de la base de datos
```bash
./scripts/03_verificar_estado.sh
```
Muestra: capturas recientes, parches por estado, casos por tipo y estado ecologico, sectores activos, tecnicos y SMS enviados.

### Contar archivos en S3
```bash
./scripts/07_contar_parches_inputs.sh       REM archivos .npy subidos
./scripts/07_contar_parches_inputs.sh 5     REM solo de captura_5
./scripts/08_contar_parches_outputs.sh      REM archivos .npz generados
```

### Verificar consistencia BD <-> S3
```bash
./scripts/09_parches_procesados.sh
```
Detecta parches marcados como `PROCESADO` en BD pero sin `.npz` en S3 (y viceversa).

### Inspeccionar un resultado individual
```bash
./scripts/10_inspeccionar_output.sh
```
Descarga el primer `.npz` procesado y muestra shapes, min/max/mean de cada tensor, conteo de pixeles deforestados y probabilidades.

### Smoke test (crear alerta manual)
```bash
./scripts/13_smoke_test_alerta.sh
```
Crea un `CasoAuditoria` con geometria sintetica. Sirve para verificar la visualizacion en el frontend sin esperar al pipeline.

### Visualizacion de parches (RGB + capa IA)

El backend Django genera automaticamente los PNGs (`sagemaker-visualizations/captura_X/parche_R_C_{rgb,mask}.png`) cada vez que llega un resultado de SageMaker. El modal de detalle de cada alerta muestra estas imagenes lado a lado.

```bash
# Diagnosticar cuantas visualizaciones faltan
./scripts/15_diagnosticar_visualizaciones.sh

# Backfill: generar las que falten
./scripts/14_generar_visualizaciones_historicas.sh --dry-run    # solo simula
./scripts/14_generar_visualizaciones_historicas.sh             # genera solo faltantes
./scripts/14_generar_visualizaciones_historicas.sh --todos     # regenera todos
./scripts/14_generar_visualizaciones_historicas.sh --captura-id 5   # solo de una captura
```

**Sobre AWS Lambda:** la funcion Lambda (`backend/lambda_function.py`) ya NO es necesaria para la visualizacion. El backend usa `Pillow` directamente. Puedes dejarla en AWS (no molesta) o deshabilitar su trigger S3. La guia original esta en `backend/guia_lambda_aws.txt` por si quieres consultarla.

### Revocar una tarea colgada
```bash
./scripts/11_revocar_tarea.sh 5abd0500-c68b-440e-9995-95b2582e2e58
./scripts/11_revocar_tarea.sh 5abd0500-c68b-440e-9995-95b2582e2e58 --terminar
```

---

## Estructura del proyecto

```
apuguard_stac/
├── README.md                          ← este archivo
├── docker-compose.yml                 ← orquestacion de los 6 servicios
├── docker-compose.override.yml        ← overrides opcionales (debug, solo local)
├── docker-compose.prod.yml            ← capa de PRODUCCION: sin puertos, gunicorn, restart
├── .env.example                       ← plantilla de variables
├── .gitignore
├── build/                             ← artefactos de despliegue (gitignorado)
│
├── infra/                             ← recursos AWS (Fase D)
│   ├── README.md                      ← arquitectura, costes, operacion y DR
│   ├── politica-deploy.json           ← politica IAM del usuario de despliegue
│   ├── politica-instancia.tmpl.json   ← politica inline del rol de la instancia
│   └── 10_red_y_permisos.sh ... 40_instalar_docker.sh
│
├── backend/                           ← Django + DRF + Celery
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── manage.py
│   ├── apuguard/                      ← proyecto Django (settings, urls, celery)
│   ├── core/                          ← modelos PostGIS + API REST
│   │   ├── models.py
│   │   ├── views.py
│   │   ├── serializers.py
│   │   ├── permissions.py
│   │   ├── signals.py
│   │   ├── jwt_serializers.py
│   │   ├── urls.py
│   │   ├── migrations/
│   │   └── management/commands/
│   │       ├── crear_admin.py
│   │       └── crear_analista.py
│   ├── ml_engine/                     ← tareas Celery
│   │   ├── tasks.py                   ← 4 tareas: quincena, escucha, reporte, gc
│   │   └── preprocessing.py
│   └── scripts/                       ← scripts Python (montados en /app/scripts/)
│       ├── 00..15, 17, 18             ← mismos que en ./scripts, wrappers .sh/.bat
│       ├── 19_descargar_composite_stac.py   ← smoke de descarga STAC
│       ├── 20_medir_pico_memoria.py         ← pico de RAM del tramo pesado
│       ├── 21_smoke_dedup_alertas.py        ← deduplicacion entre pasadas (Fase G)
│       ├── 22_smoke_gunicorn_estaticos.py   ← gunicorn + WhiteNoise (Fase B)
│       ├── 23_smoke_nginx_frontend.py       ← nginx + frontend (Fase C)
│       ├── 24_rotar_secretos_dev.py         ← rota secretos (Fase A')
│       ├── 25_bootstrap_prod_env.py         ← genera/verifica .env de prod (Fase D)
│       └── 26_smoke_prod_https.py           ← smoke end-to-end por CloudFront (Fase D)
│
├── frontend/                          ← Angular 18
│   ├── Dockerfile                     ← build de produccion (Fase C)
│   ├── Dockerfile.dev
│   ├── package.json
│   ├── angular.json
│   ├── tailwind.config.js
│   ├── proxy.conf.json
│   ├── proxy.conf.docker.json
│   ├── nginx.conf                     ← proxy a gunicorn + protocolo CloudFront (Fase C/D)
│   └── src/app/                       ← codigo fuente
│       ├── core/                      ← guards, interceptor, services, models
│       ├── features/                  ← componentes por pantalla
│       └── shared/                    ← navbar
│
└── scripts/                           ← scripts operativos
    ├── README.md                      ← indice de scripts
    ├── setup.{sh,bat}                 ← orquestador de setup
    ├── reset.{sh,bat}                 ← reset completo
    ├── logs.{sh,bat}                  ← tail en vivo
    ├── 00_crear_admin.{sh,bat}
    ├── 00_crear_analista.{sh,bat}
    ├── 01_cargar_sectores.{sh,bat}
    ├── 02_generar_static_layers.{sh,bat}
    ├── 03_verificar_estado.{sh,bat}
    ├── 04_lanzar_quincena.{sh,bat}
    ├── 05_lanzar_escucha.{sh,bat}
    ├── 06_lanzar_escucha_bulk.{sh,bat}
    ├── 07_contar_parches_inputs.{sh,bat}
    ├── 08_contar_parches_outputs.{sh,bat}
    ├── 09_parches_procesados.{sh,bat}
    ├── 10_inspeccionar_output.{sh,bat}
    ├── 11_revocar_tarea.{sh,bat}
    ├── 12_healthcheck.{sh,bat}
    ├── 13_smoke_test_alerta.{sh,bat}
    ├── 14_generar_visualizaciones_historicas.{sh,bat}
    ├── 15_diagnosticar_visualizaciones.{sh,bat}
    ├── 17_verificar_sagemaker.{sh,bat}
    ├── 18_redeploy_sagemaker.{sh,bat}
    ├── deploy_paquetear.ps1           ← Fase D: compila imagenes en local
    ├── deploy_subir.ps1               ← Fase D: sube y arranca el stack
    └── deploy_migrar_bd.ps1           ← Fase E: BD dev -> prod + copia en S3
```

---

## Troubleshooting

### "docker compose exec web ... no such file or directory"

El contenedor `web` no esta corriendo. Verifica:
```bash
docker compose ps
docker compose up -d web
```

### "Could not connect to the database"

La BD no esta lista. El healthcheck puede tardar hasta 60s. Espera o reinicia:
```bash
docker compose restart web
```

### "AWS credentials not configured" / "S3 upload failed"

Verifica que `backend/.env` tiene `AWS_ACCESS_KEY_ID` y `AWS_SECRET_ACCESS_KEY`. Despues:
```bash
docker compose restart web celery_worker celery_beat
```

> Solo aplica al **desarrollo local**. En produccion `AWS_*` estan vacios a
> proposito: la instancia usa su instance profile (IMDSv2).
> `scripts/25_bootstrap_prod_env.py --verificar` comprueba exactamente eso.

### "No module named 'GDAL'"

La imagen Docker no se construyo correctamente. Reconstruye sin cache:
```bash
docker compose build --no-cache
```

### "Google Earth Engine authentication failed"

Solo aplica si `IMAGERY_SOURCE=gee`. El archivo `backend/gee_key.json` no existe o el service account no es correcto. Verifica:
```bash
docker compose exec web cat /app/gee_key.json | head -20
```
Si no usas GEE (defecto `IMAGERY_SOURCE=stac`), este error no deberia aparecer nunca.

### La descarga STAC se corta o va muy lenta

El composite se lee de COGs remotos via `/vsicurl/`. Verifica conectividad y variables:
```bash
docker compose exec web python -c "import os; print(os.environ.get('IMAGERY_SOURCE'), os.environ.get('IMAGERY_WORKERS'))"
docker compose exec web python /app/scripts/19_descargar_composite_stac.py --bbox "-70.0,-12.9,-69.9,-12.8" --crop 512 -v
```
Ajusta `IMAGERY_WORKERS` (defecto 16) y `IMAGERY_MEM_MB` (defecto 512) en `backend/.env`.

### "502 Bad Gateway" en el frontend

El frontend no puede alcanzar al backend. Verifica la red Docker:
```bash
docker compose logs frontend
```

### Quiero empezar de cero

```bash
./scripts/reset.sh        # Linux/Mac
scripts\reset.bat         # Windows
```

Esto baja todos los contenedores, borra el volumen `postgres_data` (pierdes la BD) y las imagenes locales. Despues ejecuta `./scripts/setup.sh` de nuevo.

---

## Stack tecnologico

- **Backend:** Django 4.2 + DRF + SimpleJWT + Celery 5.3 + django-celery-beat
- **Base de datos:** PostgreSQL 16 + PostGIS 3.4
- **ML:** rasterio + scipy + boto3 (SageMaker Async)
- **Adquisicion de imagenes:** STAC / AWS Earth Search (defecto) con lector `/vsicurl/` sobre COG; GEE opcional
- **AWS:** S3, SageMaker, SQS, SNS
- **SMS:** Twilio
- **Frontend:** Angular 18 + PrimeNG + Leaflet + Tailwind
- **Infraestructura:** Docker + Docker Compose (desarrollo) / EC2 + CloudFront + Elastic IP (produccion)
- **Despliegue:** `scripts/deploy_paquetear.ps1`, `deploy_subir.ps1`, `deploy_migrar_bd.ps1`

---

## Licencia y contacto

Proyecto academico - Universidad Peruana de Ciencias Aplicadas (UPC)
Curso: Programacion y despliegue de soluciones de IA
Ciclo: 2026-1
