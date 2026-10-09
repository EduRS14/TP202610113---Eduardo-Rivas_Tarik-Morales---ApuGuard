#!/bin/bash
# APU GUARD - Verificar config del endpoint SageMaker

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose exec -T web python /app/scripts/17_verificar_sagemaker.py
