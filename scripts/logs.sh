#!/bin/bash
# =============================================
# APU GUARD - Ver logs en tiempo real
# Uso: ./logs.sh [servicio]
#   servicios: web, celery_worker, celery_beat, frontend, db, redis
#   sin parametro = todos los servicios
# =============================================

cd "$(dirname "${BASH_SOURCE[0]}")/.."

SERVICE="${1:-}"

if [ -n "$SERVICE" ]; then
    echo "Mostrando logs de: $SERVICE (Ctrl+C para salir)"
    docker compose logs -f "$SERVICE"
else
    echo "Mostrando logs de todos los servicios (Ctrl+C para salir)"
    docker compose logs -f
fi
