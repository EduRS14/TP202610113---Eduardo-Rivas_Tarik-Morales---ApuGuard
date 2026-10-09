<#
  deploy_paquetear.ps1 — Fase D
  Prepara en .\build\ los dos artefactos que se suben al EC2:

    apuguard-fuentes.tgz     codigo + compose + scripts (sin .env, sin datos)
    apuguard-imagenes.tgz    las 4 imagenes Docker ya compiladas EN LOCAL

  Las imagenes se compilan aqui y no en la instancia a proposito: t3.small
  tiene 2 GB y el build de GDAL se queda sin memoria (se detecto en Fase 0).

  Uso:
    .\scripts\deploy_paquetear.ps1                # todo
    .\scripts\deploy_paquetear.ps1 -SoloFuentes   # solo codigo
    .\scripts\deploy_paquetear.ps1 -SoloImagenes  # solo imagenes
#>
[CmdletBinding()]
param(
    [switch]$SoloFuentes,
    [switch]$SoloImagenes
)

$ErrorActionPreference = 'Stop'
$raiz    = Split-Path -Parent $PSScriptRoot
$salida  = Join-Path $raiz 'build'
New-Item -ItemType Directory -Force -Path $salida | Out-Null

function Get-Peso([string]$ruta) {
    if (-not (Test-Path $ruta)) { return 0 }
    return [math]::Round((Get-Item $ruta).Length / 1MB, 1)
}

# ---------------------------------------------------------------- fuentes ----
if (-not $SoloImagenes) {
    Write-Host "==> Empaquetando fuentes"
    $fuentes = Join-Path $salida 'apuguard-fuentes.tgz'
    if (Test-Path $fuentes) { Remove-Item $fuentes -Force }

    # Los exclusiones van con la ruta tal cual queda dentro del tar.
    $tarArgs = @(
        '-czf', $fuentes,
        '--exclude=frontend/node_modules',
        '--exclude=frontend/dist',
        '--exclude=frontend/.angular',
        '--exclude=backend/staticfiles',
        '--exclude=backend/media',
        '--exclude=backend/.env',
        '--exclude=build',
        '--exclude=__pycache__',
        '--exclude=celerybeat-schedule',
        '--exclude=celerybeat-schedule.db',
        '--exclude=*.tif', '--exclude=*.tiff',
        '--exclude=*.npy', '--exclude=*.npz',
        '--exclude=*.log',
        '-C', $raiz,
        'backend', 'frontend', 'infra', 'scripts',
        'docker-compose.yml', 'docker-compose.prod.yml',
        '.env.example', '.gitignore', 'README.md'
    )
    & tar @tarArgs
    if ($LASTEXITCODE -ne 0) { throw "tar de fuentes fallo (exit $LASTEXITCODE)" }

    # Verificacion: el tar no debe llevar datos pesados ni secretos.
    $lista = & tar -tzf $fuentes
    $malo = $lista | Where-Object {
        $_ -match 'node_modules/' -or
        $_ -match '(^|/)\.env$' -or
        $_ -match '\.tif$' -or
        $_ -match 'staticfiles/'
    }
    if ($malo) {
        Write-Host "[FALLA] el paquete contiene elementos que no deben viajar:"
        $malo | Select-Object -First 10 | ForEach-Object { Write-Host "   $_" }
        throw "paquete de fuentes contaminado"
    }
    Write-Host ("   [PASA] {0} entradas, {1} MB" -f @($lista).Count, (Get-Peso $fuentes))
}

# --------------------------------------------------------------- imagenes ----
if (-not $SoloFuentes) {
    Write-Host "==> Compilando imagenes (esto NO se hace en el EC2)"
    Push-Location $raiz
    try {
        docker build -q -t apuguard-prod-web:latest .\backend
        if ($LASTEXITCODE -ne 0) { throw "build del backend fallo" }
        # celery worker y beat usan la misma imagen; solo se etiquetan.
        docker tag apuguard-prod-web:latest apuguard-prod-celery_worker:latest
        docker tag apuguard-prod-web:latest apuguard-prod-celery_beat:latest

        docker build -q -t apuguard-prod-frontend:latest .\frontend
        if ($LASTEXITCODE -ne 0) { throw "build del frontend fallo" }
    }
    finally { Pop-Location }

    $tarImg = Join-Path $salida 'apuguard-imagenes.tar'
    $tgzImg = Join-Path $salida 'apuguard-imagenes.tgz'
    if (Test-Path $tarImg) { Remove-Item $tarImg -Force }
    if (Test-Path $tgzImg) { Remove-Item $tgzImg -Force }

    Write-Host "==> docker save (puede tardar un par de minutos)"
    docker save `
        apuguard-prod-web:latest `
        apuguard-prod-celery_worker:latest `
        apuguard-prod-celery_beat:latest `
        apuguard-prod-frontend:latest `
        -o $tarImg
    if ($LASTEXITCODE -ne 0) { throw "docker save fallo" }

    & tar -czf $tgzImg -C $salida 'apuguard-imagenes.tar'
    if ($LASTEXITCODE -ne 0) { throw "compresion de imagenes fallo" }
    Remove-Item $tarImg -Force
    Write-Host ("   [PASA] {0} MB" -f (Get-Peso $tgzImg))
}

# ---------------------------------------------------------------- resumen ----
Write-Host ""
Write-Host "=== build\ ==="
Get-ChildItem $salida -File | ForEach-Object {
    Write-Host ("   {0,-28} {1,8} MB" -f $_.Name, [math]::Round($_.Length / 1MB, 1))
}
Write-Host ""
Write-Host "Siguiente: .\scripts\deploy_subir.ps1 -Ip <ip-publica>"
