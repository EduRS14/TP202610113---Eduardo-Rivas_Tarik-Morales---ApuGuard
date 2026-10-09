#!/bin/bash
# =============================================
# APU GUARD - Reset (baja contenedores y borra volumenes)
# =============================================

set -e

cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "============================================="
echo " APU GUARD - Reset"
echo "============================================="
echo ""
echo "  Esto eliminara:"
echo "    - Todos los contenedores"
echo "    - El volumen postgres_data (BORRARA LA BD)"
echo "    - Todas las imagenes locales de apuguard"
echo ""
read -p "  Estas seguro? (s/n): " RESP
if [ "$RESP" != "s" ]; then
    echo "Cancelado."
    exit 0
fi

echo ""
echo "Deteniendo contenedores..."
docker compose down

echo "Borrando volumen postgres_data..."
docker compose down -v

echo "Borrando imagenes locales de apuguard..."
docker images | grep apuguard | awk '{print $3}' | xargs -r docker rmi -f 2>/dev/null || true

echo ""
echo "[OK] Reset completo. Ejecuta ./scripts/setup.sh para volver a inicializar."
