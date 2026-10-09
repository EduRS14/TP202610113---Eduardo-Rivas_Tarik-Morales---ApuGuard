# Despliegue en produccion — Fases D y E

Arquitectura resultante:

```
navegador --HTTPS--> CloudFront (<cloudfront-domain>.cloudfront.net)
                         |
                         | HTTP :80  (solo desde el prefix list de CloudFront)
                         v
              EC2 t3.small  --> EIP (fija)
              [nginx :80 (frontend)] --proxy--> [gunicorn :8000 (web)]
                                                [celery worker]  [celery beat]
              [PostgreSQL/PostGIS]  [Redis]
              IAM Instance Profile -> S3 / SQS / SNS / SageMaker
```

Sin dominio propio: se usa la URL que reparte CloudFront y su certificado
`*.cloudfront.net` (automatico y gratuito).

---

## 0. Coste esperado (us-east-1)

| Concepto | En ejecucion | Detenida (pausa) |
|---|---|---|
| `t3.small` dias 3-14 + `m7i-flex.large` dias 15-2 | ~19.3 USD/mes | **0** |
| EBS gp3 20 GB | ~1.6 USD/mes | ~1.6 USD/mes |
| Elastic IP (siempre asociada a la instancia) | 0 | ~3.6 USD/mes |
| VPC, subred, IGW, Security Group, IAM | 0 | 0 |
| CloudFront (12 meses de free tier, luego ~0.085 USD/GB) | 0 | 0 |
| CloudFront -> EC2 en la misma region (egress) | 0 | 0 |
| `ml.g4dn.xlarge` del endpoint SageMaker (solo con la quincena activa) | ~0.74 USD/h (**escalar a 0 al terminar**) | **0** |
| **Total** | **~21 USD/mes -> ~4.3 meses con 90 USD** | **~5.2 USD/mes -> ~17 meses** |

**No se crean** (trampas de coste): NAT Gateway (~32 USD/mes), ALB
(~16 USD/mes), CloudWatch Logs (0.50 USD/GB), snapshots de EBS, WAF
(desde 5 USD/mes).

> **Pausa (ahorro)**: `aws ec2 stop-instances --instance-ids <ID>` deja el
> compute en 0 y ahorra ~15.7 USD/mes (**75 %**); sigue facturando el EBS
> (1.6) y la Elastic IP (3.6) = ~5.2 USD/mes. Segun la documentacion de AWS
> *"when the instance is stopped, you are charged for the associated Elastic
> IP addresses"*, asi que la EIP **no** se libera al parar (y por eso no
> cambia la IP, el DNS ni el origen de CloudFront).
>
> **No** pares los contenedores con `docker compose stop`: EC2 sigue
> facturando (ahorro 0) y `restart: unless-stopped` no los volveria a
> arrancar al reiniciar el host. El paron correcto es el de la instancia.
>
> Reanudar (cobra un minimo de 1 min):
> ```bash
> aws ec2 start-instances --instance-ids <ID>
> ssh -i ~/.ssh/apuguard-ec2.pem ec2-user@<ip> 'docker ps --format "{{.Names}} {{.Status}}"'
> # 6 contenedores 'Up' + healthcheck 7/7 + 26_smoke_prod_https.py
> ```
> **ADVERTENCIA**: si mientras estas parada cambia tu IP de red, la regla
> 22/tcp del Security Group (`SSH_CIDR`) te bloquea el SSH: hay que editarla
> (`ec2:AuthorizeSecurityGroupIngress` esta en `politica-deploy.json`).

---

## 1. AWS CLI local (una sola vez)

```powershell
winget install Amazon.AWSCLI
# reinicia la terminal para que aws este en el PATH
aws --version
```

Crear en la consola **IAM -> Users -> Create user** `apuguard-deploy` con
`Access key - Programmatic access` y adjuntar como policy personalizada el
contenido de [`politica-deploy.json`](politica-deploy.json) (EC2, CloudFront,
creacion del rol de instancia, SageMaker, S3 del datalake y
`sts:GetCallerIdentity`).

```powershell
aws configure
#  Access key ID     : la del usuario
#  Secret access key : la del usuario
#  Default region    : us-east-1
#  Default output    : json
aws sts get-caller-identity
```

> ADVERTENCIA: `aws configure` guarda la clave en **texto plano** en
> `C:\Users\<tu-usuario>\.aws\credentials`. Por eso es una IAM user con
> politica acotada y no la cuenta root. Al terminar la Fase D se puede borrar:
> `aws iam delete-access-key --user-name apuguard-deploy --access-key-id <ID>`.
> Si en algun momento prefieres no tener credenciales locales, los mismos
> scripts `.sh` corren en **AWS CloudShell** sin cambios (pero ahi la deteccion
> automatica de IP NO te sirve: pasa `SSH_CIDR=<tu-ip>/32`).

---

## 2. Orden de ejecucion

### Paso 1 — Red y permisos

```bash
cd infra
./10_red_y_permisos.sh                       # detecta tu IP publica
# o, si cambia tu IP:
SSH_CIDR=1.2.3.4/32 ./10_red_y_permisos.sh
```

Crea VPC sin NAT, subred publica, IGW, Security Group (80 solo desde
CloudFront, 22 solo desde tu IP), par de claves `~/.ssh/apuguard-ec2.pem` y
el rol `apuguard-ec2` con permisos minimos (S3/SQS/SNS/SageMaker).

> El prefix list de CloudFront pesa **55 de las 60 reglas** que admite un SG
> por defecto; con la de SSH son 56. Si necesitas mas reglas, pide aumento
> de cuota.

### Paso 2 — Instancia

```bash
./20_instancia.sh
# anota la IP publica y el DNS que imprime
```

`t3.small` + Amazon Linux 2023 + gp3 20 GB + IMDSv2 obligatorio + EIP.
Imprime tambien el comando de SSH.

### Paso 3 — CloudFront

```bash
./30_cloudfront.sh <public-dns-del-paso-2>
# anota la URL https://<cloudfront-domain>.cloudfront.net
```

La distribucion tarda **5-15 min** en estar `Deployed`. Se puede seguir
mientras tanto.

El script crea ademas la politica de origen propia
`apuguard-all-viewer-proto` = todos los headers del espectador **+**
`CloudFront-Forwarded-Proto`. La gestionada `AllViewer` no incluye esa
cabecera, y sin ella nginx ni Django pueden saber que el espectador llego
por HTTPS: `$fwd_proto` cae en `$scheme` (http), Django aplica
`SECURE_SSL_REDIRECT` sobre un origen sin TLS y se monta un bucle de 301
en `/api/*` y `/admin/`, ademas de no enviar nunca
`Strict-Transport-Security`.

`30_cloudfront.sh` es **idempotente**: si la distribucion ya existe no crea
otra (la URL cambiaria y habria que regenerar `backend/.env`), sino que
parchea la politica de origen de la existente en el sitio:

```bash
./30_cloudfront.sh                                 # reaplica (no cambia la URL)
aws cloudfront get-distribution --id <ID> \
    --query 'Distribution.Status'                   # hasta decir 'Deployed'
```

> **ADVERTENCIA — TLS de espectador**: con el certificado por defecto de
> CloudFront (`CloudFrontDefaultCertificate: true`, o sea sin dominio propio)
> la política `MinimumProtocolVersion` **se ignora** y la distribución queda
> en `TLSv1` aunque se pida `TLSv1.2_2021` (el API la acepta y la revierte
> sin avisar). Sólo se puede fijar `TLSv1.2_2021` adjuntando un certificado
> ACM de un dominio propio. Coste: dominio (~10-15 USD/año) + zona alojada
> de Route 53 (0.50 USD/mes); el certificado ACM es gratuito.

### Paso 4 — Codigo e imagenes

```powershell
.\scripts\deploy_paquetear.ps1
```

Compila las 4 imagenes **en local** (el build de GDAL en un `t3.small` de
2 GB se queda sin memoria) y deja en `build\`:

* `apuguard-fuentes.tgz` (~0.3 MB): compose, backend, frontend, scripts.
  Verificado que **no** lleva `.env`, `node_modules`, `staticfiles` ni `.tif`.
* `apuguard-imagenes.tgz` (~520 MB): `apuguard-prod-{web,celery_worker,celery_beat,frontend}`.

### Paso 5 — Subir y arrancar

```powershell
.\scripts\deploy_subir.ps1 -Ip <ip-publica> `
    -CloudFrontUrl https://<cloudfront-domain>.cloudfront.net
```

En el servidor: instala Docker si falta, descomprime, `docker load`, crea
`backend/.env` de produccion (solo si no existe) y levanta el stack con
`docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.

**Obligatorio usar las dos `-f`**: si se lanza `docker compose up` sin `-f`,
se carga `docker-compose.override.yml`, que arrancaria `runserver` y
publicaria el 5433.

### Paso 6 — Base de datos (Fase E)

La BD de produccion arranca **vacia** (solo las migraciones de Django).
Se rellena migrando la de desarrollo local:

```powershell
.\scripts\deploy_migrar_bd.ps1 -Ip <ip-publica>
```

`pg_dump -Fc` en local -> SSH -> copia en
`s3://apuguard-datalake-prod/backups/` -> `DROP SCHEMA public` ->
`pg_restore` -> conteos comparados con desarrollo -> healthcheck 7/7.
Para dejar copia **sin** restaurar: `-SoloCopia`.
Detalle y script: [`../scripts/README.md`](../scripts/README.md).

---

## 3. Verificacion

```bash
ssh -i ~/.ssh/apuguard-ec2.pem ec2-user@<ip>
cd /opt/apuguard
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml ps

# Todo DENTRO del contenedor web: en el host no esta publicado ni el 8000
# ni el 4200 (prod solo publica el 80 del frontend).
#   FRONTEND_BASE  -> en prod no existe el 4200 de desarrollo.
#   HEALTH_PROTO   -> SECURE_SSL_REDIRECT=True; pegando directo a gunicorn
#                     no hay X-Forwarded-Proto y Django devolveria 301, que
#                     urllib perseguiria intentando TLS contra el 8000.
#   < /dev/null    -> si no, el `exec` se traga el stdin del resto del script.
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web \
    env FRONTEND_BASE=http://frontend:80 HEALTH_PROTO=https \
    python /app/scripts/12_healthcheck.py < /dev/null                  # 7/7

sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web \
    python /app/scripts/25_bootstrap_prod_env.py --verificar < /dev/null
#      -> VEREDICTO: PASA y SIN [ADVERTENCIA]. Si sale
#         "[ADVERTENCIA] claves aun con placeholder: ..." faltan
#         SQS/SNS/Twilio: ver "Rellenar los placeholders" en
#         scripts/README.md (--completar, no --forzar).

sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web \
    python /app/scripts/26_smoke_prod_https.py \
    --url https://<cloudfront-domain>.cloudfront.net < /dev/null
```

`26_smoke_prod_https.py` comprueba desde dentro del servidor:

* `GET /api/sectores/` -> **401** con **0 saltos** de redirect (si redirige,
  `SECURE_SSL_REDIRECT` le esta llegando en claro y el `map` de nginx no
  esta traduciendo `CloudFront-Forwarded-Proto`).
* `POST /api/auth/token/` -> **400** (el POST atraviesa CloudFront).
* `GET /admin/` -> **200** (WhiteNoise).
* `index.html` sale con `Cache-Control: no-cache`.
* un asset `*.js` sale con `Cache-Control: immutable` y `x-cache: Hit` en la
  segunda peticion.
* `Strict-Transport-Security` presente.
* ir directo a `http://<ip-publica>/` **no contesta** (el SG bloquea 80 fuera
  de CloudFront).

---

## 4. Operacion

### Despues de tocar codigo

```powershell
.\scripts\deploy_paquetear.ps1 -SoloFuentes
.\scripts\deploy_subir.ps1 -Ip <ip>
```

El backend va con *bind mount* (`./backend:/app`), asi que basta con subir
el codigo y reiniciar. El frontend va dentro de la imagen: si cambia Angular,
haz `deploy_paquetear.ps1` completo (recompila y sube las imagenes).

### Reiniciar contenedores (y el *catch-up* de beat)

Para código nuevo basta `docker compose restart web celery_worker`
(`beat` no hace falta: manda tareas por nombre).

**Antes de reiniciar `celery_beat`, mirar sus logs**: al arrancar, el
`PersistentScheduler` reenvía de golpe todas las tareas crontab
**atrasadas** (`generar-reporte-mensual`, `limpiar-archivos-temporales-s3`,
y `procesar-quincena-tambopata` si el día 1/16 anterior se perdió porque la
instancia estaba parada). Incidente 2026-10-07: un reinicio a las 16:57
disparó la quincena fuera de programa y murió 39 s después por OOM.

Protección ya aplicada: `procesar_quincena_tambopata` sólo corre sin
`forzar` los días **1 y 16**; los lanzamientos manuales
(`scripts/04_lanzar_quincena.py` y `POST /api/pipeline/trigger/`) pasan
`forzar=True`. Si beat dispara igualmente otra tarea atrasada no hay que
limpiar nada: todas son idempotentes.

### La quincena completa necesita mas RAM que la t3.small (y aun mas que 8 GB)

El tramo pesado (tensor `[9, 7426, 14870]` float32 ~4 GB + temporales)
supera los 2 GB de la `t3.small`. En el intento del 2026-10-07 el hijo de
Celery murio con **SIGKILL del OOM-killer** (`dmesg`: `Out of memory: Killed
process ... (celery)`, 1,3 GB RSS) a los 39 s, sin llegar a subir compuesto
ni parches. Vigilar siempre `sudo dmesg -T | grep -i oom`.

La `m7i-flex.large` (8 GB) **tampoco alcanza sola**: en la quincena real
2026-09-22 -> 2026-10-07 (lanzada 2026-10-07 22:17) el proceso alcanzo
`anon-rss: 7131864 kB` y el OOM-killer lo mato 19 s despues de empezar el
tensor (`dmesg`: `Killed process 3501 (celery) total-vm:10220304kB`), con el
composite ya subido. La solucion permanente es **swap de 4 GB en EBS con
`fstab`** (ya instalado el 2026-10-08; sobrevive reinicios y resizes porque
vive en el disco, no en la instancia):

```bash
# setup unico (no repetir si ya existe; verificar con: swapon --show)
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
# prueba de persistencia sin reiniciar:
sudo swapoff /swapfile && sudo swapon -a && swapon --show
```

4 GB bastan (pico medido de swap: 1.4 GiB) y dejan ~11 GB de disco libres;
con 8 GB solo quedarian ~6 GB. **El swap no salva a la `t3.small`**: 2 GB
RAM + 4 GB swap = 6 GB < 7.13 GB que necesita el tensor; la regla sigue
siendo ejecutar la quincena en `m7i-flex.large` (calendario de la seccion
de abajo), el swap unicamente cubre su deficit de 8 GB.

Con swap la re-ejecucion (task `99eb81e9`) completo todo el pipeline
cero OOM nuevos: pico 5.8 GB RAM + 1.4 GB swap durante el z-score global,
`[QUINCENA] Completado: 6663 parches extraidos, 6663 enviados`, 6663/6663
`PROCESADO` en BD y 6663 outputs S3 (inferencia 1:1). Las lecturas COG
puntuales fallidas (`[STAC] .../SCL: ZIPDecode...`) **no son fatales**:
`acquisition.py` avisa y esa escena queda sin mascara de nubes (fallback
previsto); en una re-ejecucion posterior se releen sin problema (verificado
2026-10-07).

### Resize a `m7i-flex.large` (dia 15, mantener hasta el dia 2)

```bash
aws ec2 stop-instances    --instance-ids <i-...>
aws ec2 modify-instance-attribute --instance-id <i-...> --instance-type m7i-flex.large
aws ec2 start-instances   --instance-ids <i-...>
```

La parada debe ser breve: mientras la instancia esta detenida, la EIP sigue
cobrandose (~0.005 USD/h).

Calendario (beat lanza la quincena automatica los dias **1 y 16** a las
03:00, fuera de horario laboral): **subir el dia 15**, mantener
`m7i-flex.large` durante los dias 16-31 y el **dia 1 y 2** del mes
siguiente, y **bajar a `t3.small` el dia 3**. No usar "dia 30" como fecha
de subida: en febrero no existe y la quincena del dia 1 quedaria en
`t3.small` (OOM garantizado). Si se pierde un resize (dia 15 o dia 3), la
quincena del dia 16 o del dia 1 falla con el OOM clasico; se detecta con
`sudo dmesg -T | grep -i oom` y se recupera con un re-lanzamiento manual
desde `m7i-flex.large`.

### Rotar secretos en produccion

```bash
# dentro del servidor
ssh -i ~/.ssh/apuguard-ec2.pem ec2-user@<ip>
cd /opt/apuguard
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml stop web
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web \
    python /app/scripts/24_rotar_secretos_dev.py --aplicar < /dev/null
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml start web
```

> Tiene que correr **dentro del contenedor `web`**: `psycopg2` no esta en el
> host y `DB_HOST=db` solo resuelve en la red de compose. Rota
> `DJANGO_SECRET_KEY` (invalida todos los JWT: hay que volver a entrar) y el
> password de BD (`ALTER USER` incluido).

### Copias de seguridad de la BD

```powershell
# dump local -> servidor -> s3://apuguard-datalake-prod/backups/ (sin restaurar)
.\scripts\deploy_migrar_bd.ps1 -Ip <ip> -SoloCopia

# lo mismo pero restaurando encima de produccion (dev -> prod)
.\scripts\deploy_migrar_bd.ps1 -Ip <ip>
```

Hacer una copia **antes** de cualquier operacion destructiva. Las copias
pesan ~6.9 MB y se listan con `aws s3 ls s3://apuguard-datalake-prod/backups/`
(desde la instancia: el usuario `apuguard-deploy` no tiene permisos S3).

### Ver costes

AWS Console -> **Billing -> Cost Explorer**. Tambien se puede crear un
presupuesto (AWS Budgets permite 2 gratuitos) que avise por SNS al superar
un umbral.

---

## 5. Que NO se ha creado y por que

| Recurso | Motivo |
|---|---|
| Route 53 / dominio propio | ~12 USD/ano + hosted zone; se usa la URL de CloudFront |
| ALB | ~16 USD/mes; CloudFront apunta directo al EC2 |
| NAT Gateway | ~32 USD/mes; no hay subredes privadas |
| CloudWatch Logs | 0.50 USD/GB; los logs giran en el propio motor (10 MB x 3) |
| Snapshots de EBS | 0.094 USD/GB-mes; el backup de BD es un `pg_dump -Fc` (~6.9 MB) que `scripts/deploy_migrar_bd.ps1` sube a `s3://apuguard-datalake-prod/backups/` |
| WAF | desde 5 USD/mes |
| SSM Session Manager | ~10 USD/mes en VPC endpoints; sin NAT no funciona, por eso el 22 queda abierto desde tu IP |

---

## 6. Recuperacion ante desastres minimos

* **Se cambio tu IP de casa** y no puedes entrar:
  consola AWS -> EC2 -> Security Groups -> reglas de entrada -> editar la 22.
* **La instancia murio**: `./20_instancia.sh` la vuelve a levantar (EIP fija,
  los datos de la BD viven en el volumen `postgres_data`).
* **Se borro todo**: `10` -> `20` -> `30` -> `deploy`. El `.env` se regenera
  con secretos nuevos; la BD se rellena con `scripts/deploy_migrar_bd.ps1`
  (Fase E) a partir de un dump de `s3://apuguard-datalake-prod/backups/`.

---

## 7. Ciclo de vida del endpoint SageMaker (modelo HRNet v10)

Estado verificado el 2026-10-07:

| Elemento | Valor |
|---|---|
| Endpoint | `apuguard-endpoint` (inferencia **asincrona**: `S3OutputPath=s3://apuguard-datalake-prod/sagemaker-outputs/`, SNS `apuguard-topic-success` / `apuguard-topic-error`) |
| Config activa | `apuguard-endpoint-config-v10` (`ml.g4dn.xlarge`, `InitialInstanceCount=1`, `MaxConcurrentInvocationsPerInstance=1`) |
| Modelo | `apuguard-hrnet-v10` -> `s3://apuguard-datalake-prod/model-20261007-165542-seed42.tar.gz` (32,8 MB: `hrnet_final_seed42.pth` + `code/{hrnet.py,inference.py,requirements.txt}`) |
| Rollback | endpoint config `apuguard-endpoint-config-v9` (y `model.tar.gz` para reempaquetar) |
| Instancias | **`DesiredInstanceCount=0` en reposo** (0 USD/h). A 1 solo mientras corre la quincena |

### Antes de cada quincena y al terminar

```bash
# ENCENDER (a 1) antes de la quincena
aws sagemaker update-endpoint-weights-and-capacities \
    --endpoint-name apuguard-endpoint --region us-east-1 \
    --desired-weights-and-capacities VariantName=variant-name-1,DesiredInstanceCount=1

# APAGAR (a 0) cuando termine
aws sagemaker update-endpoint-weights-and-capacities \
    --endpoint-name apuguard-endpoint --region us-east-1 \
    --desired-weights-and-capacities VariantName=variant-name-1,DesiredInstanceCount=0

aws sagemaker describe-endpoint --endpoint-name apuguard-endpoint \
    --query "ProductionVariants[0].{Current:CurrentInstanceCount,Desired:DesiredInstanceCount}"
```

> La accion `sagemaker:UpdateEndpointWeightsAndCapacities` esta concedida a
> `apuguard-deploy` (restringida al endpoint `apuguard-endpoint`). Ojo: la
> API **no admite** cambiar `DesiredInstanceCount` y `DesiredWeight` en la
> misma llamada (da `ValidationException`); envia solo una de las dos.
> Si no se quiere CLI, se puede hacer igualmente desde la consola:
> SageMaker > Endpoints > `apuguard-endpoint` >
> `Update endpoint weights and capacities`.

> `18_redeploy_sagemaker.py` crea la config nueva con
> `InitialInstanceCount=1`, asi que **tras un redespliegue el endpoint queda
> facturando** hasta que lo bajes a 0 (el script lo recuerda al terminar).

### Redespliegue de modelo

```powershell
python backend\scripts\28_empaquetar_modelo.py --subir      # 1. empaqueta + sube tar.gz
echo s | python backend\scripts\18_redeploy_sagemaker.py s3://apuguard-datalake-prod/model-<fecha>-seed42.tar.gz
python backend\scripts\17_verificar_sagemaker.py            # 2-3. crea modelo/config + verifica
python backend\scripts\29_invocar_endpoint_prueba.py captura_1/parche_0_50.npy --normalizar   # smoke (endpoint a 1)
```

Smoke end-to-end ejecutado en la validacion v10:

* parche dorado (`prueba_oro`): mascara 41 px (0,2502 %), `prob mean=2,397e-3`,
  correlacion 0,9967 con la ejecucion local (banda de 5 semillas) -> **PASA**.
* `12_healthcheck.py` -> **7/7** y `26_smoke_prod_https.py` -> **9/9**.
* Worker sin errores de proceso; **1 ERROR esperado** si se invoca un input
  sintetico sin `ParcheProcesamiento` en la BD
  (`[ESCUCHA] No se encontro parche para output: ...`): es el control de
  consistencia de `procesar_resultado_sagemaker`, no una falla del modelo.
* Inputs historicos en `sagemaker-inputs/` estan en el formato ANTIGUO
  (ch6-8 en [0,1] crudo): con el modelo v10 responden ~0 salvo que se pasen
  por `29 --normalizar`.

Smoke E2E de las **capas reales** (`31_smoke_capas_reales.py`, 2026-10-07):

* fidelidad: recortar las capas `*-demo.tif` con el camino de la quincena
  reproduce bit-a-bit los ch7/ch8 de los 150 parches de `captura_1`
  muestreados (`max_diff=0.000e+00`) -> el E2E mide solo el efecto de las
  capas nuevas, no del recorte.
* con endpoint a 1: dos parches regenerados con capas reales pasan
  `29` (metricas coherentes) y `31 --comparar` contra forward local
  -> **PASA** con `corr=0.985` y `corr=0.994` (ratio 1,12 / 1,03).
* limpieza: `sagemaker-inputs/prueba_layers/*` y sus `.out` borrados,
  endpoint de vuelta a **0/0**, BD sin casos nuevos (los `inference_id`
  `prueba_*` los ignora el worker).

### Capas estaticas reales

```powershell
python backend\scripts\30_generar_static_layers_reales.py            # genera + sube
python backend\scripts\30_generar_static_layers_reales.py --sin-subir # solo genera (revision)
```

* Rejilla del composite (EPSG:32719, X 380480..529180, Y 8543460..8617720)
  a 40 m/px; rios con **buffer 50 m**; valor = distancia al rasgo /
  distancia maxima (`dist/max`), float32 en [0,1] (contrato de
  `preprocessing.calcular_dist_capa_estatica`, que ademas los re-escala
  bilineal al shape del composite).
* Antes de sobrescribir deja las demo en `static-layers/mineria-demo.tif` y
  `static-layers/rios-demo.tif`. Volver a demo:

  ```bash
  aws s3 cp s3://apuguard-datalake-prod/static-layers/mineria-demo.tif \
            s3://apuguard-datalake-prod/static-layers/mineria.tif
  aws s3 cp s3://apuguard-datalake-prod/static-layers/rios-demo.tif \
            s3://apuguard-datalake-prod/static-layers/rios.tif
  ```

* Regenerar cuando cambie el catastro minero o la red hidrica.

### Permisos (estado real)

* `apuguard-deploy` tiene SageMaker Create/Update/Describe*/List*,
  `sagemaker:UpdateEndpointWeightsAndCapacities` (solo
  `endpoint/apuguard-endpoint`, verificado 2026-10-07),
  `s3:GetObject`/`PutObject` en `model*.tar.gz` e `iam:PassRole` a
  `apuguard-sagemaker-role`. **NO** tiene `s3:DeleteObject` en la raiz del
   bucket (borrado de artefactos desde la instancia, cuyo rol `apuguard-ec2`
   si tiene `s3:*`; hoy el borrado se hizo con el usuario local
   `apuguard-local`, que si tiene `s3:DeleteObject`). Tampoco
   `iam:ListUserPolicies` -> no se puede leer la politica real desde aqui.
   [`politica-deploy.json`](politica-deploy.json) es desde 2026-10-07 una
   **reconstruccion de referencia** (acciones del despliegue: anade
   SageMaker y S3), no una copia de la politica aplicada; la cuenta real
   difiere en detalles (p. ej. `apuguard-deploy` NO tiene `s3:GetObject`
   salvo en `model*`).
* En EC2 `backend/.env` lleva `AWS_ACCESS_KEY_ID=` vacio: el contenedor usa
  el **rol de instancia** (`sagemaker:InvokeEndpoint/InvokeEndpointAsync` +
  S3/SQS/SNS).

### Pendientes conocidos

* SMS reales sin probar: `core_tecnicocampo` esta vacio (0 filos), asi que
  el bucle de alertas no tiene destinatarios.
* TLS de espectador en `TLSv1`: sin dominio propio el certificado de
  CloudFront ignora `MinimumProtocolVersion` (ver seccion 2, Paso 3).
* La regla 22/tcp del SG esta atada a la IP `38.25.16.186/32`: si cambia la
  IP hay que editarla en la consola.
