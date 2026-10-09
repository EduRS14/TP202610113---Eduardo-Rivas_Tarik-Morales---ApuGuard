<#
  deploy_subir.ps1 — Fase D
  Sube los artefactos de .\build\ al EC2 y deja el stack levantado.

  Hace:
    1. crea /opt/apuguard en el servidor
    2. scp de apuguard-fuentes.tgz y apuguard-imagenes.tgz
    3. remoto: descomprime, instala Docker si falta, `docker load`
    4. remoto: crea backend/.env SOLO si no existe (los secretos no se
       regeneran en cada despliegue: rotarlos invalida los JWT y deja la
       BD con un password que ya no coincide)
    5. remoto: docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

  Uso:
    # primer despliegue (requiere la URL de CloudFront, paso 30_cloudfront.sh)
    .\scripts\deploy_subir.ps1 -Ip 3.4.5.6 `
        -CloudFrontUrl https://dxxxxxxxxxxxx.cloudfront.net

    # despliegues siguientes
    .\scripts\deploy_subir.ps1 -Ip 3.4.5.6
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Ip,
    [string]$Usuario  = 'ec2-user',
    [string]$Clave    = "$env:USERPROFILE\.ssh\apuguard-ec2.pem",
    [string]$Remoto   = '/opt/apuguard',
    [string]$CloudFrontUrl = '',
    [string]$Ec2Dns   = '',
    [switch]$SinImagenes
)

$ErrorActionPreference = 'Stop'
$raiz    = Split-Path -Parent $PSScriptRoot
$salida  = Join-Path $raiz 'build'
$fuentes = Join-Path $salida 'apuguard-fuentes.tgz'
$imagenes = Join-Path $salida 'apuguard-imagenes.tgz'

if (-not (Test-Path $Clave))  { throw "no existe la clave privada: $Clave" }
if (-not (Test-Path $fuentes)) { throw "falta $fuentes - ejecuta deploy_paquetear.ps1" }
if (-not $SinImagenes -and -not (Test-Path $imagenes)) {
    throw "falta $imagenes - ejecuta deploy_paquetear.ps1 (o usa -SinImagenes)"
}

$destino = "$Usuario@$Ip"
$sshArgs = @('-i', $Clave, '-o', 'IdentitiesOnly=yes',
             '-o', 'StrictHostKeyChecking=accept-new', '-o', 'LogLevel=ERROR')

Write-Host "==> Preparando $Remoto en $destino"
& ssh @sshArgs $destino "sudo mkdir -p $Remoto && sudo chown ${Usuario}:${Usuario} $Remoto"
if ($LASTEXITCODE -ne 0) { throw "no se pudo abrir sesion en $destino" }

Write-Host "==> Subiendo fuentes ($( [math]::Round((Get-Item $fuentes).Length/1MB,1) )) MB"
& scp @sshArgs $fuentes "${destino}:${Remoto}/"
if ($LASTEXITCODE -ne 0) { throw "scp de fuentes fallo" }

if (-not $SinImagenes) {
    Write-Host "==> Subiendo imagenes ($( [math]::Round((Get-Item $imagenes).Length/1MB,1) )) MB  (tarda)"
    & scp @sshArgs $imagenes "${destino}:${Remoto}/"
    if ($LASTEXITCODE -ne 0) { throw "scp de imagenes fallo" }
}

# ---------------------------------------------------------------------------
# Script remoto. Se pasa por stdin (bash -s) para no luchar con el escaping
# de PowerShell/bash. Los @@...@@ se sustituyen abajo.
# ---------------------------------------------------------------------------
$plantilla = @'
set -euo pipefail
REMOTO=@@REMOTO@@
cd "$REMOTO"

echo "-> descomprimiendo fuentes"
tar -xzf apuguard-fuentes.tgz

if ! docker compose version >/dev/null 2>&1; then
    echo "-> instalando docker"
    bash infra/40_instalar_docker.sh
else
    sudo systemctl enable --now docker
fi

if [ -f apuguard-imagenes.tgz ]; then
    echo "-> cargando imagenes"
    tar -xzf apuguard-imagenes.tgz
    sudo docker load -i apuguard-imagenes.tar
    rm -f apuguard-imagenes.tar apuguard-imagenes.tgz
fi
rm -f apuguard-fuentes.tgz

if [ ! -f backend/.env ]; then
    if [ -z "@@CFURL@@" ]; then
        echo "[FALLA] falta backend/.env y no se paso -CloudFrontUrl."
        echo "        Vuelve a ejecutar con:"
        echo "          -CloudFrontUrl https://dxxxxxxxxxxxx.cloudfront.net"
        exit 1
    fi
    echo "-> creando backend/.env de produccion"
    DNS="@@EC2DNS@@"
    if [ -z "$DNS" ]; then
        T=$(curl -s -X PUT http://169.254.169.254/latest/api/token \
            -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' || true)
        DNS=$(curl -s -H "X-aws-ec2-metadata-token: $T" \
            http://169.254.169.254/latest/meta-data/public-hostname || true)
    fi
    echo "   CloudFront: @@CFURL@@"
    echo "   EC2 DNS   : $DNS"
    python3 backend/scripts/25_bootstrap_prod_env.py \
        --cloudfront-url '@@CFURL@@' --ec2-dns "$DNS" --aplicar
else
    echo "-> backend/.env ya existe: se conserva (los secretos NO se regeneran)"
fi

echo "-> arrancando el stack"
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
'@

# PowerShell anade un `\r` al volcar la cadena en el stdin de ssh; sin mas,
# se pega al ultimo comando (`ps\r` -> unknown docker command). Se limpian
# los CR aqui y, ademas, el remoto los vuelve a filtrar con `tr`.
$remotoCmd = ($plantilla `
    -replace '@@REMOTO@@',   $Remoto `
    -replace '@@CFURL@@',    $CloudFrontUrl `
    -replace '@@EC2DNS@@',   $Ec2Dns) -replace "`r", ''

Write-Host "==> Ejecutando despliegue remoto"
$remotoCmd | & ssh @sshArgs $destino "tr -d '\r' | bash -s"
if ($LASTEXITCODE -ne 0) { throw "el despliegue remoto fallo (exit $LASTEXITCODE)" }

Write-Host ""
Write-Host "=== DESPLIEGUE HECHO ==="
Write-Host "  URL    : $CloudFrontUrl"
Write-Host "  Comprobar desde el servidor (dentro del contenedor web):"
Write-Host "    ssh -i $Clave $destino"
Write-Host "    cd $Remoto"
Write-Host "    sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml ps"
Write-Host "    # FRONTEND_BASE: en prod no existe el 4200 de desarrollo."
Write-Host "    # HEALTH_PROTO : SECURE_SSL_REDIRECT=True, gunicorn no ve el header solo."
Write-Host "    # < /dev/null  : si no, el exec se traga el stdin del resto del script."
Write-Host "    sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web \"
Write-Host "        env FRONTEND_BASE=http://frontend:80 HEALTH_PROTO=https \"
Write-Host "        python /app/scripts/12_healthcheck.py < /dev/null   # 7/7"
Write-Host "    sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web \"
Write-Host "        python /app/scripts/25_bootstrap_prod_env.py --verificar < /dev/null"
Write-Host "    sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T web \"
Write-Host "        python /app/scripts/26_smoke_prod_https.py --url $CloudFrontUrl < /dev/null"
Write-Host "    sudo docker compose -f docker-compose.yml -f docker-compose.prod.yml logs --tail=50 web"
