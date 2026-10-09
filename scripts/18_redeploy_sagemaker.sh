#!/bin/bash
# APU GUARD - Re-deploy endpoint SageMaker con nuevo model.tar.gz
# Uso: ./18_redeploy_sagemaker.sh s3://BUCKET/PATH/model.tar.gz

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ $# -eq 0 ]; then
    echo "Uso: ./18_redeploy_sagemaker.sh s3://BUCKET/PATH/model.tar.gz"
    echo
    echo "Ejemplo:"
    echo "  ./18_redeploy_sagemaker.sh s3://apuguard-datalake-prod/models/hrnet/model.tar.gz"
    exit 1
fi

docker compose exec -it web python /app/scripts/18_redeploy_sagemaker.py "$@"
