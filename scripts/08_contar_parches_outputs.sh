#!/bin/bash
# APU GUARD - Contar parches en sagemaker-outputs/

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose exec -T web python /app/scripts/08_contar_parches_outputs.py
