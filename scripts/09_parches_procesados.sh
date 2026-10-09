#!/bin/bash
# APU GUARD - Verificar consistencia BD vs S3 (parches procesados)

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose exec -T web python /app/scripts/09_parches_procesados.py
