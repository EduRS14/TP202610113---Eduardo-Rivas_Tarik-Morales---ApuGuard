#!/bin/bash
# APU GUARD - Lanzar escucha SQS 10 veces (bulk)

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose exec -T web python /app/scripts/06_lanzar_escucha_bulk.py
