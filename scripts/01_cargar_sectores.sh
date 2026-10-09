#!/bin/bash
# APU GUARD - Cargar 5 sectores de Tambopata

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose exec -T web python /app/scripts/01_cargar_sectores.py
