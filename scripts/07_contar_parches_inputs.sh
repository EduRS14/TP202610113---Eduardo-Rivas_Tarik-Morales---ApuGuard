#!/bin/bash
# APU GUARD - Contar parches en sagemaker-inputs/
# Uso: ./07_contar_parches_inputs.sh [captura_id]

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ $# -eq 0 ]; then
    docker compose exec -T web python /app/scripts/07_contar_parches_inputs.py
else
    docker compose exec -T web python /app/scripts/07_contar_parches_inputs.py "$@"
fi
