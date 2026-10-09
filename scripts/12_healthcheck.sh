#!/bin/bash
# =============================================
# APU GUARD - Healthcheck de endpoints REST
# =============================================

set +e

cd "$(dirname "${BASH_SOURCE[0]}")/.."

API_BASE="${API_BASE:-http://localhost:8000/api}"
FRONTEND_BASE="${FRONTEND_BASE:-http://localhost:4200}"
TOTAL=0
OK=0

echo "============================================="
echo " APU GUARD - Healthcheck de API"
echo "============================================="
echo ""
echo "API Base: $API_BASE"
echo "Frontend: $FRONTEND_BASE"
echo ""

# Funcion para chequear un endpoint con GET (sin auth, 401 = protegido pero alcanzable)
check() {
    local nombre="$1"
    local url="$2"
    local esperado="$3"
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url")
    TOTAL=$((TOTAL + 1))
    if [ "$code" = "$esperado" ]; then
        echo "  [OK]   $nombre ($url) -> $code"
        OK=$((OK + 1))
    else
        echo "  [FAIL] $nombre ($url) -> $code (esperado $esperado)"
    fi
}

# Igual que check() pero con POST y body JSON vacio.
check_post() {
    local nombre="$1"
    local url="$2"
    local esperado="$3"
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
        -X POST -H "Content-Type: application/json" -d "{}" "$url")
    TOTAL=$((TOTAL + 1))
    if [ "$code" = "$esperado" ]; then
        echo "  [OK]   $nombre ($url) -> $code"
        OK=$((OK + 1))
    else
        echo "  [FAIL] $nombre ($url) -> $code (esperado $esperado)"
    fi
}

# Endpoints publicos (sin auth, devuelven 401 = protegido pero alcanzable)
check "GET  /api/sectores/"             "$API_BASE/sectores/"             "401"
check "GET  /api/alertas/"              "$API_BASE/alertas/"              "401"
check "GET  /api/dashboard/stats/"      "$API_BASE/dashboard/stats/"      "401"
check "GET  /api/dashboard/audit-logs/" "$API_BASE/dashboard/audit-logs/" "401"

# El endpoint de token es solo POST: con body vacio devuelve 400 (serializer activo)
check_post "POST /api/auth/token/"      "$API_BASE/auth/token/"           "400"

# Endpoint de admin Django (curl no sigue la redireccion -> 302 al login)
check "GET  /admin/"                    "http://localhost:8000/admin/"    "302"

# Frontend Angular
check "GET  / (frontend)"               "$FRONTEND_BASE"                  "200"

echo ""
echo "Resultado: $OK / $TOTAL checks OK"
if [ "$OK" = "$TOTAL" ]; then
    echo "[OK] Todos los servicios respondiendo."
    exit 0
else
    echo "[WARN] Hay servicios que no responden. Revisa docker compose ps"
    exit 1
fi
