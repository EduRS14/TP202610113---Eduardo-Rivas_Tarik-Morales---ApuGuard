#!/bin/bash
# APU GUARD - Revocar tarea Celery por ID
# Uso: ./11_revocar_tarea.sh <TASK_ID> [--terminar]

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ $# -eq 0 ]; then
    echo "Uso: ./11_revocar_tarea.sh TASK_ID [--terminar]"
    echo
    echo "Ejemplo:"
    echo "  ./11_revocar_tarea.sh 5abd0500-c68b-440e-9995-95b2582e2e58"
    exit 1
fi

docker compose exec -T web python /app/scripts/11_revocar_tarea.py "$@"
