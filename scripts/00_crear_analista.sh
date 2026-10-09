#!/bin/bash
# APU GUARD - Crear usuario Analista
# Uso: ./00_crear_analista.sh --username juan --password juan123 --sectores SEC-01 SEC-04

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if [ $# -eq 0 ]; then
    echo "Uso: ./00_crear_analista.sh --username USER --password PASS [--email EMAIL] [--sectores SEC-01 SEC-02]"
    echo
    echo "Ejemplo:"
    echo "  ./00_crear_analista.sh --username juan --password juan123 --sectores SEC-01 SEC-04"
    exit 1
fi

docker compose exec -T web python manage.py crear_analista "$@"
