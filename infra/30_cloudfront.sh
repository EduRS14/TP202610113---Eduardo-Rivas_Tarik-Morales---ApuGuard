#!/usr/bin/env bash
# =============================================================================
# 30_cloudfront.sh — Fase D, paso 3
#
# Crea (o reutiliza) la distribucion CloudFront que da la URL publica:
#   https://dxxxxxxxxxxxx.cloudfront.net
#
#   * certificado *.cloudfront.net automatico y gratuito (no hay dominio propio)
#   * origen: EC2 por HTTP (CloudFront termina TLS del lado del cliente)
#   * default: CachingDisabled -> la API no se cachea nunca
#   * /assets/*, *.js, *.css: CachingOptimized -> si se cachean
#   * PriceClass_100 (solo Norteamerica/Europa: mas barato)
#   * sin WAF (desde 5 USD/mes), sin ALB, sin NAT
#
# POLITICA DE ORIGEN PROPIA (no usar la gestionada AllViewer)
#   La gestionada AllViewer (216adef6-...) no anade CloudFront-Forwarded-Proto,
#   asi que en el origen nadie sabe que el espectador llego por HTTPS: nginx
#   ve $scheme=http, Django recibe X-Forwarded-Proto vacio y
#   SECURE_SSL_REDIRECT le da la vuelta 301 en bucle (y nunca envia HSTS).
#   Se crea apuguard-all-viewer-proto = todos los headers del espectador +
#   CloudFront-Forwarded-Proto, sin meterlo en la cache key.
#
# Los IDs de las politicas gestionadas de cache se resuelven por NOMBRE:
#   CachingDisabled  4135ea2d-6df8-44a3-9df3-4b5a84be39ad
#   CachingOptimized 658327ea-f89d-4fab-a63d-7e88639e58f6
#
# El script es idempotente: si la distribucion ya existe, en lugar de crear
# otra (y cambiar la URL), parchea su politica de origen en el sitio.
#
# Requiere: cloudfront:CreateOriginRequestPolicy, cloudfront:UpdateDistribution
#
# Uso:
#   ./30_cloudfront.sh ec2-3-4-5-6.compute-1.amazonaws.com
#   ./30_cloudfront.sh                      # descubre la IP por etiqueta
# =============================================================================
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
PROYECTO="apuguard"
COMENTARIO="APU GUARD - apuguard_stac"
ORP_NOMBRE="apuguard-all-viewer-proto"
DIR="$(cd "$(dirname "$0")" && pwd)"

# En Windows/MSYS `python3` apunta al atajo de la Microsoft Store que no
# funciona: se comprueba que cada candidato ejecuta algo antes de usarlo.
PYBIN=""
for _c in python python3 py; do
    _p="$(command -v "$_c" 2>/dev/null || true)"
    [ -n "$_p" ] || continue
    if "$_p" -c 'import json, sys' >/dev/null 2>&1; then
        PYBIN="$_p"
        break
    fi
done
if [ -z "$PYBIN" ]; then
    echo "[FALLA] hace falta python (o python3) para editar la configuracion"
    exit 1
fi
echo "Python          : $PYBIN"

# --- Politica de origen propia: AllViewer + CloudFront-Forwarded-Proto -------
# Los items de list-*-policies salen anidados ({Type, OriginRequestPolicy:{...}})
# y las gestionadas llevan prefijo "Managed-": con la ruta plana la busqueda
# devuelve vacio y el script intenta crear una politica que ya existe.
orp_id="$(aws cloudfront list-origin-request-policies --region "$REGION" --type custom \
    --query "OriginRequestPolicyList.Items[?OriginRequestPolicy.OriginRequestPolicyConfig.Name=='$ORP_NOMBRE'].OriginRequestPolicy.Id" \
    --output text || true)"
if [ -z "$orp_id" ] || [ "$orp_id" = "None" ]; then
    echo "-> creando politica de origen $ORP_NOMBRE"
    orp_id="$(aws cloudfront create-origin-request-policy --region "$REGION" \
        --origin-request-policy-config "{
            \"Name\": \"$ORP_NOMBRE\",
            \"Comment\": \"Todos los headers del espectador + CloudFront-Forwarded-Proto (APU GUARD)\",
            \"CookiesConfig\": { \"CookieBehavior\": \"all\" },
            \"HeadersConfig\": {
                \"HeaderBehavior\": \"allViewerAndWhitelistCloudFront\",
                \"Headers\": { \"Quantity\": 1, \"Items\": [\"CloudFront-Forwarded-Proto\"] }
            },
            \"QueryStringsConfig\": { \"QueryStringBehavior\": \"all\" }
        }" --query 'OriginRequestPolicy.Id' --output text)"
fi
echo "Politica origen : $orp_id ($ORP_NOMBRE)"

# --- Actualiza en el sitio la politica de origen de la distribucion ---------
# No usa ficheros temporales (mktemp devuelve rutas MSYS que el python de
# Windows no abre): la configuracion viaja por stdin/stdout.
actualizar_distribucion() {
    local id="$1" cfg_full etag salida cambios nuevo_cfg
    # python en Windows escribe \n como \r\n: hay que quitar el \r,
    # si no el \r queda pegado al ETag y --if-match lo rechaza.
    cfg_full="$(aws cloudfront get-distribution-config --region "$REGION" --id "$id")"
    etag="$(printf '%s' "$cfg_full" | "$PYBIN" -c \
        'import json,sys; print(json.load(sys.stdin)["ETag"])' | tr -d '\r')"

    # Linea 1: comportamientos tocados (vacio = nada que hacer)
    # Linea 2: DistributionConfig resultante (json en una sola linea)
    salida="$(printf '%s' "$cfg_full" | "$PYBIN" -c '
import json, sys
orp = sys.argv[1]
cfg = json.load(sys.stdin)["DistributionConfig"]
toca = []
def fijar(behavior, etiqueta):
    if behavior.get("OriginRequestPolicyId") == orp:
        return
    behavior["OriginRequestPolicyId"] = orp
    toca.append(etiqueta)
fijar(cfg["DefaultCacheBehavior"], "default")
for item in cfg.get("CacheBehaviors", {}).get("Items", []):
    fijar(item, item.get("PathPattern", "?"))
print("; ".join(toca))
print(json.dumps(cfg))
' "$orp_id" | tr -d '\r')"

    cambios="${salida%%$'\n'*}"
    nuevo_cfg="${salida#*$'\n'}"

    if [ -z "$cambios" ]; then
        echo "[PASA] $id ya usa $ORP_NOMBRE ($orp_id)"
        return 0
    fi

    echo "-> cambiando politica de origen en: $cambios"
    aws cloudfront update-distribution --region "$REGION" --id "$id" \
        --if-match "$etag" --distribution-config "$nuevo_cfg" \
        --query 'Distribution.Status' --output text
    echo "[OK] $id actualizado. La propagacion tarda 5-15 min:"
    echo "       aws cloudfront get-distribution --id $id --query 'Distribution.Status'"
}

# --- Si ya existe, no creamos otra (cada distribucion nueva se propaga) ------
# El campo cuelga de DistributionList.Items, no de Items: con la ruta erronea
# la consulta siempre devuelve "None" y se intentaria crear una segunda
# distribucion (DistributionAlreadyExists) en vez de parchear la existente.
EXISTE_ID="$(aws cloudfront list-distributions --region "$REGION" \
    --query "DistributionList.Items[?Comment=='$COMENTARIO'].Id" --output text 2>/dev/null || true)"
if [ -n "$EXISTE_ID" ] && [ "$EXISTE_ID" != "None" ]; then
    echo "Distribucion     : $EXISTE_ID"
    actualizar_distribucion "$EXISTE_ID"
    exit 0
fi

# --- Origen ------------------------------------------------------------------
ORIGEN="${1:-}"
if [ -z "$ORIGEN" ]; then
    ORIGEN="$(aws ec2 describe-instances --region "$REGION" \
        --filters "Name=tag:Proyecto,Values=$PROYECTO" "Name=instance-state-name,Values=running" \
        --query 'Reservations[0].Instances[0].PublicDnsName' --output text)"
fi
if [ -z "$ORIGEN" ] || [ "$ORIGEN" = "None" ]; then
    echo "[FALLA] no hay instancia en ejecucion. Ejecuta ./20_instancia.sh"
    exit 1
fi
echo "Origen           : $ORIGEN (EC2, HTTP 80)"

# --- Politicas gestionadas de cache resueltas por nombre ---------------------
# (si en el futuro AWS renombra una politica, el respaldo de abajo la salva)
cache_disabled="$(aws cloudfront list-cache-policies --region "$REGION" --type managed \
    --query "CachePolicyList.Items[?CachePolicy.CachePolicyConfig.Name=='Managed-CachingDisabled'].CachePolicy.Id" \
    --output text || true)"
cache_optimized="$(aws cloudfront list-cache-policies --region "$REGION" --type managed \
    --query "CachePolicyList.Items[?CachePolicy.CachePolicyConfig.Name=='Managed-CachingOptimized'].CachePolicy.Id" \
    --output text || true)"

# Respaldo con los IDs documentados por AWS.
cache_disabled="${cache_disabled:-4135ea2d-6df8-44a3-9df3-4b5a84be39ad}"
cache_optimized="${cache_optimized:-658327ea-f89d-4fab-a63d-7e88639e58f6}"

echo "CachingDisabled  : $cache_disabled"
echo "CachingOptimized : $cache_optimized"

# --- Configuracion -----------------------------------------------------------
# ADVERTENCIA: MinimumProtocolVersion=TLSv1.2_2021 se pide aqui, pero con
# CloudFrontDefaultCertificate=true (sin dominio propio) CloudFront lo ignora
# y deja TLSv1/vip: solo fija la politica TLS si hay un certificado ACM.
# Para endurecerlo hay que anadir un dominio y un certificado ACM (gratis)
# y apuntar el alias a CloudFront.
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

cat > "$tmp" <<EOF
{
  "CallerReference": "apuguard-stac-fase-d",
  "Comment": "$COMENTARIO",
  "Enabled": true,
  "HttpVersion": "http2and3",
  "IsIPV6Enabled": true,
  "PriceClass": "PriceClass_100",
  "Origins": {
    "Quantity": 1,
    "Items": [
      {
        "Id": "ec2-origen",
        "DomainName": "$ORIGEN",
        "CustomOriginConfig": {
          "HTTPPort": 80,
          "HTTPSPort": 443,
          "OriginProtocolPolicy": "http-only",
          "OriginSslProtocols": { "Quantity": 1, "Items": ["TLSv1.2"] },
          "OriginReadTimeout": 60,
          "OriginKeepaliveTimeout": 60
        }
      }
    ]
  },
  "OriginGroups": { "Quantity": 0 },
  "DefaultCacheBehavior": {
    "TargetOriginId": "ec2-origen",
    "ViewerProtocolPolicy": "redirect-to-https",
    "Compress": true,
    "CachePolicyId": "$cache_disabled",
    "OriginRequestPolicyId": "$orp_id",
    "AllowedMethods": {
      "Quantity": 7,
      "Items": ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"],
      "CachedMethods": { "Quantity": 2, "Items": ["GET", "HEAD"] }
    },
    "SmoothStreaming": false,
    "FieldLevelEncryptionId": ""
  },
  "CacheBehaviors": {
    "Quantity": 3,
    "Items": [
      {
        "PathPattern": "/assets/*",
        "TargetOriginId": "ec2-origen",
        "ViewerProtocolPolicy": "redirect-to-https",
        "Compress": true,
        "CachePolicyId": "$cache_optimized",
        "OriginRequestPolicyId": "$orp_id",
        "AllowedMethods": {
          "Quantity": 2,
          "Items": ["GET", "HEAD"],
          "CachedMethods": { "Quantity": 2, "Items": ["GET", "HEAD"] }
        },
        "SmoothStreaming": false,
        "FieldLevelEncryptionId": ""
      },
      {
        "PathPattern": "*.js",
        "TargetOriginId": "ec2-origen",
        "ViewerProtocolPolicy": "redirect-to-https",
        "Compress": true,
        "CachePolicyId": "$cache_optimized",
        "OriginRequestPolicyId": "$orp_id",
        "AllowedMethods": {
          "Quantity": 2,
          "Items": ["GET", "HEAD"],
          "CachedMethods": { "Quantity": 2, "Items": ["GET", "HEAD"] }
        },
        "SmoothStreaming": false,
        "FieldLevelEncryptionId": ""
      },
      {
        "PathPattern": "*.css",
        "TargetOriginId": "ec2-origen",
        "ViewerProtocolPolicy": "redirect-to-https",
        "Compress": true,
        "CachePolicyId": "$cache_optimized",
        "OriginRequestPolicyId": "$orp_id",
        "AllowedMethods": {
          "Quantity": 2,
          "Items": ["GET", "HEAD"],
          "CachedMethods": { "Quantity": 2, "Items": ["GET", "HEAD"] }
        },
        "SmoothStreaming": false,
        "FieldLevelEncryptionId": ""
      }
    ]
  },
  "Restrictions": {
    "GeoRestriction": { "RestrictionType": "none", "Quantity": 0 }
  },
  "ViewerCertificate": {
    "CloudFrontDefaultCertificate": true,
    "MinimumProtocolVersion": "TLSv1.2_2021",
    "SSLSupportMethod": "sni-only"
  }
}
EOF

echo "-> creando distribucion (tarda 5-15 min en propagarse)"
dominio="$(aws cloudfront create-distribution --region "$REGION" \
    --distribution-config "$(cat "$tmp")" \
    --query 'Distribution.DomainName' --output text)"

if [ -z "$dominio" ] || [ "$dominio" = "None" ]; then
    echo "[FALLA] no se pudo crear la distribucion"
    exit 1
fi

echo
echo "=== RESUMEN Fase D paso 3 ==="
echo "  URL publica: https://$dominio"
echo "  Siguiente  : despliega el codigo (scripts/deploy_*.ps1) y luego, ya"
echo "               dentro del servidor:"
echo "    python scripts/25_bootstrap_prod_env.py --cloudfront-url https://$dominio \\"
echo "        --ec2-dns <public-dns> --aplicar"
echo "  AVISO: la distribucion tarda 5-15 min en estar 'Deployed'. Espera"
echo "         a que 'aws cloudfront get-distribution --id <ID>' diga"
echo "         Status=Deployed antes de probar la URL."
