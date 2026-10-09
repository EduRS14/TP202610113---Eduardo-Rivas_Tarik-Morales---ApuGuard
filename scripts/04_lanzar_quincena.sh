#!/bin/bash
# APU GUARD - Lanzar tarea quincenal (STAC + SageMaker)

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose exec -T web python /app/scripts/04_lanzar_quincena.py
