#!/bin/bash
# APU GUARD - Crear superusuario admin

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

docker compose exec -T web python manage.py crear_admin "$@"
