#!/bin/bash
# APU GUARD - Diagnosticar visualizaciones (PNGs en S3)

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose exec -T web python /app/scripts/15_diagnosticar_visualizaciones.py
