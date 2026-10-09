#!/bin/bash
# APU GUARD - Verificar estado del sistema (BD)

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose exec -T web python /app/scripts/03_verificar_estado.py
