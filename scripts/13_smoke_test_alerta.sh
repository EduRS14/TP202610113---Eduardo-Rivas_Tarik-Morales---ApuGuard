#!/bin/bash
# APU GUARD - Crear alerta de smoke test

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose exec -T web python /app/scripts/13_smoke_test_alerta.py
