# APU GUARD - Scripts

Indice de scripts para operacion, mantenimiento y pruebas.

## Convenciones

- **`.sh`** — Linux / Mac (Git Bash, WSL, terminal UNIX)
- **`.bat`** — Windows (CMD, PowerShell)
- **`.py`** — Script Python. Vive en `scripts/` Y en `backend/scripts/` (este ultimo se monta en `/app/scripts/` dentro del contenedor Docker).
- **`.ps1`** — PowerShell, solo para el despliegue a produccion: `deploy_paquetear.ps1`, `deploy_subir.ps1`, `deploy_migrar_bd.ps1` (Fases D y E).

Todos los scripts Python usan `_template_python.py` para cargar `.env` y configurar Django automaticamente. No hace falta activarlos manualmente.

## Indice de scripts

| #  | Script | Proposito | Prerequisito |
|----|--------|-----------|--------------|
| 00 | `00_crear_admin.{sh,bat}` | Crea superusuario `admin` | `web` corriendo |
| 00 | `00_crear_analista.{sh,bat}` | Crea usuario Analista con sectores | `web` corriendo + sectores cargados |
| 01 | `01_cargar_sectores.{sh,bat}` | Carga/actualiza 5 sectores de Tambopata | `web` corriendo |
| 02 | `02_generar_static_layers.{sh,bat}` | Sube mineria.tif y rios.tif **DEMO** (ruido sintetico) a S3 | AWS credenciales en `.env` |
| 03 | `03_verificar_estado.{sh,bat}` | Resumen del estado en BD (capturas, parches, casos, SMS) | `web` corriendo |
| 04 | `04_lanzar_quincena.{sh,bat}` | Lanza manualmente la tarea de descarga Sentinel-2 + SageMaker | `celery_worker` y `celery_beat` corriendo |
| 05 | `05_lanzar_escucha.{sh,bat}` | Lanza 1 vez la escucha SQS para procesar resultados | `celery_worker` corriendo |
| 06 | `06_lanzar_escucha_bulk.{sh,bat}` | Lanza 10 veces seguidas la escucha SQS | `celery_worker` corriendo |
| 07 | `07_contar_parches_inputs.{sh,bat}` [id] | Cuenta archivos `.npy` en `sagemaker-inputs/` | AWS credenciales |
| 08 | `08_contar_parches_outputs.{sh,bat}` | Cuenta archivos `.npz` en `sagemaker-outputs/` | AWS credenciales |
| 09 | `09_parches_procesados.{sh,bat}` | Cruza BD vs S3 (detecta inconsistencias) | `web` corriendo + AWS |
| 10 | `10_inspeccionar_output.{sh,bat}` | Descarga y muestra metricas de un `.npz` | `web` corriendo + AWS |
| 11 | `11_revocar_tarea.{sh,bat} <TASK_ID>` | Revoca una tarea Celery por ID | `web` corriendo |
| 12 | `12_healthcheck.{sh,bat}` | Verifica endpoints REST y servicios | Docker levantado |
| 13 | `13_smoke_test_alerta.{sh,bat}` | Crea un CasoAuditoria manual de prueba | Capturas + sectores en BD |
| 14 | `14_generar_visualizaciones_historicas.{sh,bat} [--todos] [--captura-id N] [--dry-run]` | Backfill: genera PNGs (RGB + mask) para parches PROCESADO sin visualizacion | `web` corriendo + AWS credenciales |
| 15 | `15_diagnosticar_visualizaciones.{sh,bat}` | Reporta cuantos parches PROCESADO tienen (o no) sus PNGs en S3 | `web` corriendo + AWS credenciales |
| 17 | `17_verificar_sagemaker.{sh,bat}` | Muestra la config del endpoint: modelo, ModelDataUrl, tamano del tar.gz | `web` corriendo + AWS credenciales |
| 18 | `18_redeploy_sagemaker.{sh,bat} <s3://.../model.tar.gz>` | Crea nuevo modelo + endpoint config + actualiza endpoint | `web` corriendo + AWS credenciales |
| -  | `setup.{sh,bat}` | **Orquestador:** crea admin + sectores + static layers + verifica | Docker + .env |
| -  | `reset.{sh,bat}` | **Reset:** baja contenedores, borra volumenes e imagenes | Docker |
| -  | `logs.{sh,bat} [servicio]` | **Logs en tiempo real** (sin param = todos) | Docker |

### Scripts Python que solo viven en `backend/scripts/` (19-31)

No tienen `.sh`/`.bat`: se lanzan dentro del contenedor
(`docker compose exec web python /app/scripts/<fichero>`) o, si llevan el
patron con/sin Django (27-31), tambien en local.

| #  | Script | Proposito | Fase |
|----|--------|-----------|------|
| 19 | `19_descargar_composite_stac.py [--bbox "w,s,e,n"] [--crop N] [-v]` | Smoke de la descarga STAC / Earth Search: escribe el GeoTIFF temporal y valida egress del contenedor a S3 | STAC |
| 20 | `20_medir_pico_memoria.py` | Pico real de RAM del tramo pesado de `procesar_quincena_tambopata`, con arrays sinteticos del shape real (sin AWS, sin Django, sin red) | - |
| 21 | `21_smoke_dedup_alertas.py` | Deduplicacion entre pasadas: T1-T10 logica, T11-T12 idempotencia del re-run, T13-T17 API | G |
| 22 | `22_smoke_gunicorn_estaticos.py` | El WSGI real (gunicorn) arranca y sirve API + estaticos | B |
| 23 | `23_smoke_nginx_frontend.py` | nginx sirve el bundle Angular y hace proxy a gunicorn | C |
| 24 | `24_rotar_secretos_dev.py [--aplicar]` | Rota `DJANGO_SECRET_KEY` y password de BD (`ALTER USER`); se ejecuta **dentro** del contenedor | A' |
| 25 | `25_bootstrap_prod_env.py --cloudfront-url <url> [--aplicar\|--verificar]` · `--completar <fichero> [--aplicar]` | Genera/verifica `backend/.env` de produccion (sin `$` en las claves). `--completar` rellena **solo** los cinco placeholders SQS/SNS/Twilio desde otro `.env` | D |
| 26 | `26_smoke_prod_https.py --url <cloudfront>` | Smoke end-to-end por CloudFront: 9 comprobaciones | D |
| 27 | `27_verificar_normalizacion_p2p98.py` | Test dorado del contrato P2-P98 (20 checks; corre en local y en el contenedor: sin `torch` avisa y omite las comprobaciones MCD) | HRNet v10 |
| 28 | `28_empaquetar_modelo.py [--subir]` | Empaqueta `model_source/` (`hrnet_final_seed42.pth` + `inference.py`) en `model-*.tar.gz` y lo sube a S3 (con/sin Django) | HRNet v10 |
| 29 | `29_invocar_endpoint_prueba.py <clave-npy> [--normalizar] [--espera S]` | Invoca el endpoint con un `.npy` de S3 (cliente `sagemaker-runtime`) y muestra mask/prob/entropia. `--normalizar` reescribe ch6-8 con el stretch P2-P98 (inputs historicos en formato antiguo). **Requiere DesiredInstanceCount=1** | HRNet v10 |
| 30 | `30_generar_static_layers_reales.py [--res M] [--sin-subir]` | Genera las capas reales `mineria.tif`/`rios.tif` (catastro 2024 + rios buffer 50 m, `dist/max` sobre la rejilla UTM19S del composite) y respalda las demo en `static-layers/*-demo.tif` (con/sin Django, en local) | HRNet v10 |
| 31 | `31_smoke_capas_reales.py [--seleccion modelo\|diff] [--comparar <npz-uri> --parche f,c]` | E2E de las capas reales: regenera ch7/ch8 de parches de `captura_1` con el camino exacto de la quincena, comprueba fidelidad bit-a-bit contra los almacenados, selecciona parches con senal local (MCD x20) y los sube a `sagemaker-inputs/prueba_layers/`; `--comparar` valida el `.npz` del endpoint frente al forward local. **El endpoint debe estar a 1 instancia** (luego bajar a 0 y borrar `prueba_layers/*` y sus `.out`) | HRNet v10 |

## Despliegue en produccion (Fase D)

| Script | Proposito | Prerequisito |
|--------|-----------|--------------|
| `deploy_paquetear.ps1 [-SoloFuentes\|-SoloImagenes]` | Compila las 4 imagenes **en local** y deja en `build\`: `apuguard-fuentes.tgz` (compose + backend + frontend + scripts, **sin** `.env` ni `node_modules`) e `apuguard-imagenes.tgz` (~520 MB) | Docker + imagenes `apuguard-prod-*` |
| `deploy_subir.ps1 -Ip <ip> [-CloudFrontUrl https://...cloudfront.net]` | Copia los `.tgz` por SSH, instala Docker si falta, hace `docker load`, crea `backend/.env` de produccion y levanta el stack con **las dos** `-f` | `deploy_paquetear.ps1` + `~/.ssh/apuguard-ec2.pem` |

> **Obligatorio** lanzar en el servidor con las dos `-f`
> (`docker-compose.yml` + `docker-compose.prod.yml`): sin `-f` se carga
> `docker-compose.override.yml` y arrancaria `runserver` publicando el 5433.
> Arquitectura, costes y verificacion: [`../infra/README.md`](../infra/README.md).

### Rellenar los placeholders de AWS/Twilio (tras `deploy_subir`)

`deploy_subir.ps1` deja **cinco** claves en placeholder en `backend/.env`:
`SQS_RESULT_QUEUE_URL`, `SNS_ALERT_TOPIC_ARN`, `TWILIO_ACCOUNT_SID`,
`TWILIO_AUTH_TOKEN` y `TWILIO_PHONE_NUMBER`. Rellenalas con `--completar`,
que pisa **solo** esas cinco y no toca nada mas:

```bash
# en el servidor (fichero temporal de 5 lineas, permisos 600)
python3 backend/scripts/25_bootstrap_prod_env.py --completar /tmp/origen.env   # dry-run
python3 backend/scripts/25_bootstrap_prod_env.py --completar /tmp/origen.env --aplicar
python3 backend/scripts/25_bootstrap_prod_env.py --verificar                    # sin [ADVERTENCIA]
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    up -d --force-recreate web celery_worker celery_beat
rm -f /tmp/origen.env
```

> **Nunca** uses `--aplicar --forzar` para esto: regenera `DJANGO_SECRET_KEY`
> y `DB_PASSWORD` (invalida los JWT y deja la BD con un password que no se
> cambia con `ALTER USER`). `--completar` no necesita `--forzar`.
> Tampoco basta `docker compose restart`: no relee `env_file`, hay que
> **recrear** los contenedores. Sin estas claves, `celery_worker` falla cada
> 30 s con `InvalidAddress` en `receive_message`.

## Migracion de BD y copia de seguridad (Fase E)

| Script | Proposito | Prerequisito |
|--------|-----------|--------------|
| `deploy_migrar_bd.ps1 -Ip <ip> [-SoloCopia]` | `pg_dump -Fc` de la BD **local** -> `build\apuguard_bd_<fecha>.dump` -> SSH al servidor -> sube a `s3://apuguard-datalake-prod/backups/` -> para `web`/`celery`, `DROP SCHEMA public`, `pg_restore`, extensiones y arranque. Comprueba los conteos contra los de desarrollo y termina con healthcheck 7/7. `-SoloCopia` deja la copia en S3 **sin** restaurar. | `deploy_subir.ps1` ejecutado + `~/.ssh/apuguard-ec2.pem` |

```powershell
.\scripts\deploy_migrar_bd.ps1 -Ip <ip-publica>
```

> El upload a S3 se hace **desde el servidor** con el perfil de la instancia:
> el usuario `apuguard-deploy` no tiene permisos S3.
> El arranque de `web`/`celery` va en un `trap ... EXIT`, asi que si la
> restauracion falla los servicios no se quedan parados (el dump ya esta en S3).
> Cada copia pesa ~6.9 MB. Verificar al terminar con
> `25_bootstrap_prod_env.py --verificar` y `26_smoke_prod_https.py`.

## Uso rapido (Windows)

```cmd
:: Setup completo
scripts\setup.bat

:: Verificar estado
scripts\03_verificar_estado.bat

:: Disparar la IA
scripts\04_lanzar_quincena.bat
scripts\05_lanzar_escucha.bat

:: Inspeccionar resultados
scripts\07_contar_parches_inputs.bat
scripts\09_parches_procesados.bat
scripts\10_inspeccionar_output.bat

:: Healthcheck
scripts\12_healthcheck.bat

:: Logs en vivo
scripts\logs.bat celery_worker
```

## Uso rapido (Linux/Mac)

```bash
# Setup completo
./scripts/setup.sh

# Verificar estado
./scripts/03_verificar_estado.sh

# Disparar la IA
./scripts/04_lanzar_quincena.sh
./scripts/05_lanzar_escucha.sh

# Inspeccionar resultados
./scripts/07_contar_parches_inputs.sh
./scripts/09_parches_procesados.sh
./scripts/10_inspeccionar_output.sh

# Healthcheck
./scripts/12_healthcheck.sh

# Logs en vivo
./scripts/logs.sh celery_worker
```

## Ejecucion manual dentro del contenedor

Todos los scripts Python funcionan ejecutandolos directamente dentro del contenedor `web`:

```bash
docker compose exec web python /app/scripts/01_cargar_sectores.py
docker compose exec web python /app/scripts/03_verificar_estado.py
```

## Solucion de problemas

**"docker compose exec ... no such file or directory"**
Asegurate de que `docker compose up -d` se ejecuto y el contenedor `web` esta en estado `running`:
```bash
docker compose ps
```

**"AWS credentials not configured"**
Verifica que `backend/.env` tiene `AWS_ACCESS_KEY_ID` y `AWS_SECRET_ACCESS_KEY` correctos.

**"No hay parches en BD"**
Ejecuta primero `04_lanzar_quincena.py` para generar parches (la descarga del composite toma ~40 s en un AOI chico y ~38 min en el AOI completo, limitado por latencia de red).

## Visualizacion de parches (RGB + capa IA)

El backend genera automaticamente los PNGs (`sagemaker-visualizations/captura_X/parche_R_C_{rgb,mask}.png`) cada vez que llega un resultado de SageMaker. Para capturas previas que no tengan visualizacion, usa el script 14.

**Verificar estado de las visualizaciones:**
```bash
./scripts/15_diagnosticar_visualizaciones.sh
```

**Generar visualizaciones faltantes (backfill):**
```bash
./scripts/14_generar_visualizaciones_historicas.sh --dry-run    # solo simula
./scripts/14_generar_visualizaciones_historicas.sh             # genera solo faltantes
./scripts/14_generar_visualizaciones_historicas.sh --todos     # regenera todos
```

**Sobre AWS Lambda:** la funcion Lambda (`backend/lambda_function.py`) ya NO es necesaria. El backend Django genera los PNGs directamente usando `Pillow` (incluido en `requirements.txt`). Puedes dejar la Lambda en AWS (no molesta) o deshabilitar su trigger S3 para ahorrar invocaciones.
