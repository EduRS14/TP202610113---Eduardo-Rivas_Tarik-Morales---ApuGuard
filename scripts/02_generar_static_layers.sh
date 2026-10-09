#!/bin/bash
# APU GUARD - Generar static layers (mineria.tif, rios.tif)

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose exec -T web python /app/scripts/02_generar_static_layers.py
