#!/bin/bash
# APU GUARD - Generar PNGs historicos (backfill)
# Uso: ./14_generar_visualizaciones_historicas.sh [--todos] [--captura-id N] [--dry-run]

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose exec -T web python /app/scripts/14_generar_visualizaciones_historicas.py "$@"
