#!/bin/bash
# APU GUARD - Inspeccionar un .npz procesado

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose exec -T web python /app/scripts/10_inspeccionar_output.py
