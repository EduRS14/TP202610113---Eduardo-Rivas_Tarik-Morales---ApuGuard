#!/bin/bash
# APU GUARD - Lanzar escucha SQS (1 vez)

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose exec -T web python /app/scripts/05_lanzar_escucha.py
