<#
  deploy_migrar_bd.ps1 — Fase E
  Migra la BD de DESARROLLO (local) a PRODUCCION (EC2) y deja copia en S3.

  Hace:
    1. local : levanta el contenedor `db` si hace falta
    2. local : pg_dump -Fc -> build\apuguard_bd_<fecha>.dump
    3. local : cuenta filas de las tablas de negocio (referencia a comparar)
    4. scp   : dump -> /opt/apuguard/backups/
    5. remoto: sube el dump a s3://<bucket>/backups/ con el perfil de la
               instancia. OJO: el usuario `apuguard-deploy` NO tiene
               permisos S3 (solo EC2/CloudFront/IAM), por eso el upload
               se hace desde el servidor.
    6. remoto: valida el archivo (pg_restore --list), para web/celery,
               DROP SCHEMA public, pg_restore, repone extensiones y
               arranca de nuevo. El arranque va en un trap: si la
               restauracion falla los servicios NO se quedan parados.
    7. local : vuelve a contar en prod y compara con la referencia.

  Uso:
    .\scripts\deploy_migrar_bd.ps1 -Ip <ip-publica>
    .\scripts\deploy_migrar_bd.ps1 -Ip <ip-publica> -SoloCopia   # sin restaurar
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Ip,
    [string]$Usuario = 'ec2-user',
    [string]$Clave   = "$env:USERPROFILE\.ssh\apuguard-ec2.pem",
    [string]$Remoto  = '/opt/apuguard',
    [string]$Bucket  = 'apuguard-datalake-prod',
    [switch]$SoloCopia
)

$ErrorActionPreference = 'Stop'
$raiz   = Split-Path -Parent $PSScriptRoot
$salida = Join-Path $raiz 'build'

if (-not (Test-Path $Clave)) { throw "no existe la clave privada: $Clave" }

$destino = "$Usuario@$Ip"
$sshArgs = @('-i', $Clave, '-o', 'IdentitiesOnly=yes',
             '-o', 'StrictHostKeyChecking=accept-new', '-o', 'LogLevel=ERROR')

# Un solo SQL, usado tanto en local como en prod, para que la comparacion
# sea exactamente la misma consulta.
$sqlConteos = @"
SELECT 'core_casoauditoria' AS tabla, count(*) FROM core_casoauditoria
UNION ALL SELECT 'core_casoauditoria_sectores', count(*) FROM core_casoauditoria_sectores
UNION ALL SELECT 'core_parcheprocesamiento', count(*) FROM core_parcheprocesamiento
UNION ALL SELECT 'core_sectorreserva', count(*) FROM core_sectorreserva
UNION ALL SELECT 'auth_user', count(*) FROM auth_user
UNION ALL SELECT 'django_migrations', count(*) FROM django_migrations
ORDER BY 1
"@

# ---------------------------------------------------------------------------
# 1. BD local levantada
# ---------------------------------------------------------------------------
Write-Host "==> [1/7] comprobando la BD de desarrollo"
Push-Location $raiz
try {
    & docker compose up -d db
    if ($LASTEXITCODE -ne 0) { throw "no se pudo levantar el contenedor db local" }
} finally { Pop-Location }

$estado = (& docker inspect -f '{{.State.Health.Status}}' apuguard_db) 2>$null
for ($i = 0; $i -lt 30 -and $estado -ne 'healthy'; $i++) {
    Start-Sleep -Seconds 2
    $estado = (& docker inspect -f '{{.State.Health.Status}}' apuguard_db) 2>$null
}
if ($estado -ne 'healthy') { throw "el contenedor db local no llega a healthy (estado: $estado)" }
Write-Host "    contenedor db local: healthy"

# ---------------------------------------------------------------------------
# 2. pg_dump
# ---------------------------------------------------------------------------
$fecha    = Get-Date -Format 'yyyyMMdd-HHmmss'
$nombre   = "apuguard_bd_$fecha.dump"
$dumpLocal = Join-Path $salida $nombre
New-Item -ItemType Directory -Force -Path $salida | Out-Null

Write-Host "==> [2/7] pg_dump (formato custom, comprimido)"
& docker exec apuguard_db rm -f /tmp/apuguard_bd.dump
& docker exec apuguard_db pg_dump -U apuguard -d apuguard_db -Fc -f /tmp/apuguard_bd.dump
if ($LASTEXITCODE -ne 0) { throw "pg_dump fallo" }
& docker cp "apuguard_db:/tmp/apuguard_bd.dump" $dumpLocal
if ($LASTEXITCODE -ne 0) { throw "docker cp del dump fallo" }
& docker exec apuguard_db rm -f /tmp/apuguard_bd.dump

$mb = [math]::Round((Get-Item $dumpLocal).Length / 1MB, 2)
Write-Host "    $dumpLocal  ($mb MB)"

# ---------------------------------------------------------------------------
# 3. referencia local
# ---------------------------------------------------------------------------
Write-Host "==> [3/7] contando filas en desarrollo"
$localConteos = (@(& docker exec -i apuguard_db psql -U apuguard -d apuguard_db `
    -t -A -F ' ' -c $sqlConteos) -join "`n").Trim()
if (-not $localConteos) { throw "no se pudieron contar las filas en local" }
foreach ($linea in ($localConteos -split "`n")) { Write-Host "    $linea" }

# ---------------------------------------------------------------------------
# 4. subir el dump
# ---------------------------------------------------------------------------
Write-Host "==> [4/7] subiendo el dump al servidor (${destino}:$Remoto/backups/)"
& ssh @sshArgs $destino "mkdir -p $Remoto/backups"
if ($LASTEXITCODE -ne 0) { throw "no se pudo abrir sesion en $destino" }
& scp @sshArgs $dumpLocal "${destino}:$Remoto/backups/"
if ($LASTEXITCODE -ne 0) { throw "scp del dump fallo" }

# ---------------------------------------------------------------------------
# 5. subir a S3 DESDE el servidor: el usuario `apuguard-deploy` no tiene
#    permisos S3, asi que usa el perfil de la instancia.
# ---------------------------------------------------------------------------
Write-Host "==> [5/7] subiendo el dump a S3 (perfil de la instancia)"
$s3Cmd = "aws s3 cp '$Remoto/backups/$nombre' 's3://$Bucket/backups/$nombre' --only-show-errors; aws s3 ls 's3://$Bucket/backups/$nombre'"
$s3Cmd | & ssh @sshArgs $destino "tr -d '\r' | bash -s"
if ($LASTEXITCODE -ne 0) { throw "la subida a S3 fallo" }

if ($SoloCopia) {
    Write-Host ""
    Write-Host "=== COPIA HECHA (no se restauro nada) ==="
    Write-Host "  local : $dumpLocal"
    Write-Host "  remoto: ${Remoto}/backups/$nombre"
    Write-Host "  S3    : s3://$Bucket/backups/$nombre"
    exit 0
}

# ---------------------------------------------------------------------------
# 6. script remoto: validar -> DROP SCHEMA -> pg_restore -> comprobar -> arrancar
#    Se pasa por stdin (bash -s) para no luchar con el escaping.
# ---------------------------------------------------------------------------
$plantilla = @'
set -euo pipefail
REMOTO=@@REMOTO@@
NOMBRE=@@NOMBRE@@

cd "$REMOTO"
COMPOSE="sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml"

# Si algo falla a mitad, los servicios parados se reponen igualmente:
# un stack caido es peor que una BD a medias (el dump ya esta en S3).
PARADO=0
reponer() {
    if [ "$PARADO" = "1" ]; then
        echo "-> reponiendo servicios tras un fallo"
        $COMPOSE start web celery_worker celery_beat || true
    fi
}
trap reponer EXIT

echo "==> [6/7] validando el archivo antes de tocar la BD"
sudo docker cp "backups/$NOMBRE" apuguard_db:/tmp/restore.dump
sudo docker exec apuguard_db pg_restore --list /tmp/restore.dump > /tmp/restore.lst
echo "    indice con $(wc -l < /tmp/restore.lst) lineas"

echo "==> parando web y celery (db y redis se quedan)"
$COMPOSE stop web celery_worker celery_beat
PARADO=1

echo "==> DROP SCHEMA public + extensiones"
sudo docker exec -i apuguard_db psql -U apuguard -d apuguard_db -v ON_ERROR_STOP=1 <<'SQL'
DROP EXTENSION IF EXISTS postgis_tiger_geocoder CASCADE;
DROP EXTENSION IF EXISTS postgis_topology CASCADE;
DROP EXTENSION IF EXISTS postgis CASCADE;
DROP EXTENSION IF EXISTS fuzzystrmatch CASCADE;
DROP SCHEMA IF EXISTS tiger CASCADE;
DROP SCHEMA IF EXISTS tiger_data CASCADE;
DROP SCHEMA IF EXISTS topology CASCADE;
DROP SCHEMA public CASCADE;
CREATE SCHEMA public;
SQL

echo "==> pg_restore"
# pg_restore devuelve != 0 con avisos "schema already exists" que no afectan
# a los datos; el criterio de verdad es la comprobacion de conteos de abajo.
set +e
sudo docker exec apuguard_db pg_restore -U apuguard -d apuguard_db \
    --no-owner --no-privileges /tmp/restore.dump
rc=$?
set -e
if [ "$rc" -ne 0 ]; then
    echo "    pg_restore devolvio $rc; se comprueba la integridad antes de seguir"
fi

echo "==> extensiones (idempotente, por si el dump no las trajo)"
sudo docker exec -i apuguard_db psql -U apuguard -d apuguard_db -v ON_ERROR_STOP=1 <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;
CREATE EXTENSION IF NOT EXISTS postgis_tiger_geocoder;
CREATE EXTENSION IF NOT EXISTS fuzzystrmatch;
SQL

echo "==> [7/7] comprobando los conteos contra los de desarrollo"
cat > /tmp/conteos_esperados.txt <<'EOF'
@@CONTEOS@@
EOF
sudo docker exec -i apuguard_db psql -U apuguard -d apuguard_db -t -A -F ' ' <<'SQL' > /tmp/conteos_prod.txt
@@SQL@@
SQL
if diff -u /tmp/conteos_esperados.txt /tmp/conteos_prod.txt; then
    echo "    [PASA] los conteos coinciden con los de desarrollo"
else
    echo "    [FALLA] los conteos no coinciden con los de desarrollo"
    exit 1
fi

echo "==> arrancando web y celery"
$COMPOSE start web celery_worker celery_beat
PARADO=0
sleep 10

echo "==> extensiones en produccion"
# OJO: nada de `docker exec -i` aqui. Sin heredoc, `-i` le enchufa al
# contenedor el stdin del propio script (`bash -s`) y se traga el resto
# del archivo: el proceso termina con exit 0 sin ejecutar lo que queda.
sudo docker exec apuguard_db psql -U apuguard -d apuguard_db -t -A \
    -c "SELECT extname FROM pg_extension ORDER BY extname" < /dev/null

echo "==> healthcheck (reintentando hasta 90 s)"
ok=0
for i in $(seq 1 18); do
    if $COMPOSE exec -T web env FRONTEND_BASE=http://frontend:80 HEALTH_PROTO=https \
        python /app/scripts/12_healthcheck.py < /dev/null; then
        ok=1
        break
    fi
    sleep 5
done
if [ "$ok" != "1" ]; then
    echo "[FALLA] el healthcheck no llega a pasar"
    $COMPOSE logs --tail=60 web || true
    exit 1
fi

rm -f /tmp/restore.lst /tmp/conteos_esperados.txt /tmp/conteos_prod.txt
sudo docker exec apuguard_db rm -f /tmp/restore.dump
'@

$remotoCmd = ($plantilla `
    -replace '@@REMOTO@@', $Remoto `
    -replace '@@NOMBRE@@', $nombre `
    -replace '@@CONTEOS@@', $localConteos `
    -replace '@@SQL@@',     $sqlConteos) -replace "`r", ''

Write-Host "==> [6-7] ejecutando la restauracion en el servidor"
$remotoCmd | & ssh @sshArgs $destino "tr -d '\r' | bash -s"
if ($LASTEXITCODE -ne 0) { throw "la migracion remota fallo (exit $LASTEXITCODE)" }

# ---------------------------------------------------------------------------
# 6. comparar
# ---------------------------------------------------------------------------
Write-Host "==> comparando conteos prod vs desarrollo"
$psqlRemoto = @"
docker exec -i apuguard_db psql -U apuguard -d apuguard_db -t -A -F ' ' <<'SQL'
$sqlConteos
SQL
"@
$remoteConteos = (@($psqlRemoto -replace "`r", '' | & ssh @sshArgs $destino "tr -d '\r' | bash -s") -join "`n").Trim()

$ref = @{}
foreach ($linea in ($localConteos -split "`n")) {
    if ($linea -match '^(\S+)\s+(\d+)$') { $ref[$Matches[1]] = [int]$Matches[2] }
}
$diferencias = @()
foreach ($linea in ($remoteConteos -split "`n")) {
    if ($linea -match '^(\S+)\s+(\d+)$') {
        $tabla = $Matches[1]; $n = [int]$Matches[2]
        $esperado = if ($ref.ContainsKey($tabla)) { $ref[$tabla] } else { -1 }
        if ($n -ne $esperado) { $diferencias += "  [FALLA] ${tabla}: prod=$n esperado=$esperado" }
        else                   { Write-Host "  [PASA] ${tabla}: $n" }
    }
}
foreach ($tabla in $ref.Keys) {
    if ($remoteConteos -notmatch [regex]::Escape($tabla)) {
        $diferencias += "  [FALLA] falta la tabla $tabla en produccion"
    }
}

Write-Host ""
if ($diferencias) {
    $diferencias | ForEach-Host
    throw "los conteos de produccion no coinciden con los de desarrollo"
}

Write-Host "=== FASE E COMPLETADA ==="
Write-Host "  dump local : $dumpLocal ($mb MB)"
Write-Host "  dump S3    : s3://$Bucket/backups/$nombre"
Write-Host "  Verificacion publica (desde la instancia):"
Write-Host "    cd $Remoto"
Write-Host "    sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web \"
Write-Host "        python /app/scripts/25_bootstrap_prod_env.py --verificar < /dev/null"
Write-Host "    sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web \"
Write-Host "        python /app/scripts/26_smoke_prod_https.py --url https://<cloudfront-domain>.cloudfront.net < /dev/null"
