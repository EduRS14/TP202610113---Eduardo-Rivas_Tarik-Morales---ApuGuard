#!/bin/bash
# =============================================
# APU GUARD - Setup inicial (Linux/Mac)
# Encadena: crear admin -> sectores -> verificar estado
# =============================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "============================================="
echo " APU GUARD - Setup Inicial"
echo "============================================="
echo ""

# 1. Verificar prerequisites
echo "[1/5] Verificando prerequisitos..."

if ! command -v docker &> /dev/null; then
    echo "  [ERROR] docker no esta instalado."
    exit 1
fi

if ! command -v docker compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "  [ERROR] docker compose no esta disponible."
    exit 1
fi

if [ ! -f backend/.env ]; then
    echo "  [AVISO] backend/.env no existe."
    echo "          Copia .env.example -> backend/.env y edita las credenciales."
    echo "          Comando: cp .env.example backend/.env"
    read -p "  Continuar de todos modos? (s/n): " RESP
    if [ "$RESP" != "s" ]; then
        exit 1
    fi
fi

echo "  [OK] Docker y .env disponibles."
echo ""

# 2. Levantar servicios base
echo "[2/5] Levantando servicios Docker (db, redis, web)..."
docker compose up -d --build db redis web
echo "  Esperando a que db este healthy..."
for i in {1..30}; do
    if docker compose exec -T db pg_isready -U apuguard -d apuguard_db &> /dev/null; then
        echo "  [OK] Base de datos lista."
        break
    fi
    sleep 2
done
echo ""

# Verificar que web esta corriendo
if ! docker compose ps web | grep -q "running"; then
    echo "  [ERROR] El contenedor web no esta corriendo."
    echo "          Ejecuta: docker compose up -d web"
    exit 1
fi

# 3. Crear superusuario admin
echo "[3/5] Creando usuario administrador..."
docker compose exec -T web python manage.py crear_admin
echo ""

# 4. Cargar sectores
echo "[4/5] Cargando sectores de la Reserva Tambopata..."
docker compose exec -T web python /app/scripts/01_cargar_sectores.py
echo ""

# 5. Generar static layers (omitido, el usuario lo maneja aparte)
echo "[5/5] Generando static layers (mineria.tif, rios.tif)..."
echo "  [SKIP] Omitido. El usuario genera los static layers aparte."
echo "          Para generarlos manualmente: ./scripts/02_generar_static_layers.sh"
echo ""

# 6. Verificar estado
echo "============================================="
echo " Estado final del sistema"
echo "============================================="
docker compose exec -T web python /app/scripts/03_verificar_estado.py

echo ""
echo "============================================="
echo " [OK] Setup completado."
echo "============================================="
echo ""
echo "  Frontend : http://localhost:4200"
echo "  API      : http://localhost:8000/api/"
echo "  Admin    : http://localhost:8000/admin/"
echo "  Login    : admin / apuguard123"
echo ""
echo "  Siguiente paso: levantar celery y frontend:"
echo "    docker compose up -d celery_worker celery_beat frontend"
echo ""
