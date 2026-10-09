#!/usr/bin/env bash
# =============================================================================
# 10_red_y_permisos.sh — Fase D, paso 1
#
# Crea (o reutiliza) todo lo previo a la instancia:
#   VPC + 1 subred publica + Internet Gateway + ruta 0.0.0.0/0   [sin NAT]
#   Security Group: 80 SOLO desde el prefix list de CloudFront
#                   22 SOLO desde tu IP (detectada o SSH_CIDR)
#   Par de claves
#   Rol de instancia + instance profile con permisos minimos S3/SQS/SNS/SageMaker
#
# Idempotente: se puede re-ejecutar. Los recursos se buscan por la etiqueta
# Proyecto=apuguard.
#
# Uso:
#   ./10_red_y_permisos.sh                 # detecta tu IP publica
#   SSH_CIDR=1.2.3.4/32 ./10_red_y_permisos.sh
# =============================================================================
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
PROYECTO="apuguard"
DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Tu IP para el SSH -------------------------------------------------------
SSH_CIDR="${SSH_CIDR:-}"
if [ -z "$SSH_CIDR" ]; then
    IP="$(curl -s --max-time 8 https://checkip.amazonaws.com 2>/dev/null || true)"
    IP="$(printf '%s' "$IP" | tr -d '[:space:]')"
    if [ -z "$IP" ]; then
        echo "[FALLA] no se pudo detectar tu IP publica."
        echo "        Exportala:  SSH_CIDR=1.2.3.4/32 ./10_red_y_permisos.sh"
        exit 1
    fi
    SSH_CIDR="${IP}/32"
fi
echo "Region           : $REGION"
echo "SSH solo desde   : $SSH_CIDR"
case "$SSH_CIDR" in
    0.0.0.0/0) echo "[FALLA] no se permite 0.0.0.0/0 en el puerto 22"; exit 1 ;;
esac
echo "AVISO: si lanzas esto desde CloudShell, la IP detectada NO es la tuya"
echo "       (es la de AWS). Re-ejecuta con SSH_CIDR=<tu-ip>/32 desde tu equipo."
echo

cuenta="$(aws sts get-caller-identity --query Account --output text)"
echo "Cuenta AWS       : $cuenta"

# --- Prefix list de CloudFront ----------------------------------------------
# Nombre real: com.amazonaws.global.cloudfront.origin-facing (global, no por
# region). Ocupa 55 de las 60 reglas que admite un SG por defecto.
pl_id="$(aws ec2 describe-managed-prefix-lists --region "$REGION" \
    --filters "Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing" \
    --query 'PrefixLists[0].PrefixListId' --output text)"
if [ -z "$pl_id" ] || [ "$pl_id" = "None" ]; then
    echo "[FALLA] no se encontro el prefix list de CloudFront en $REGION"
    exit 1
fi
echo "Prefix list      : $pl_id"

# --- VPC ---------------------------------------------------------------------
vpc="$(aws ec2 describe-vpcs --region "$REGION" \
    --filters "Name=tag:Proyecto,Values=$PROYECTO" \
    --query 'Vpcs[0].VpcId' --output text)"
if [ -z "$vpc" ] || [ "$vpc" = "None" ]; then
    echo "-> creando VPC"
    vpc="$(aws ec2 create-vpc --region "$REGION" --cidr-block 10.42.0.0/16 \
        --tag-specifications "ResourceType=vpc,Tags=[{Key=Proyecto,Value=$PROYECTO},{Key=Nombre,Value=$PROYECTO-vpc}]" \
        --query 'Vpc.VpcId' --output text)"
    aws ec2 modify-vpc-attribute --region "$REGION" --vpc-id "$vpc" \
        --enable-dns-hostnames '{"Value":true}' >/dev/null
    aws ec2 wait vpc-available --region "$REGION" --vpc-ids "$vpc"
else
    echo "-> VPC ya existe: $vpc"
fi

# --- Internet Gateway --------------------------------------------------------
igw="$(aws ec2 describe-internet-gateways --region "$REGION" \
    --filters "Name=tag:Proyecto,Values=$PROYECTO" \
    --query 'InternetGateways[0].InternetGatewayId' --output text)"
if [ -z "$igw" ] || [ "$igw" = "None" ]; then
    echo "-> creando Internet Gateway"
    igw="$(aws ec2 create-internet-gateway --region "$REGION" \
        --tag-specifications "ResourceType=internet-gateway,Tags=[{Key=Proyecto,Value=$PROYECTO}]" \
        --query 'InternetGateway.InternetGatewayId' --output text)"
    aws ec2 attach-internet-gateway --region "$REGION" \
        --internet-gateway-id "$igw" --vpc-id "$vpc"
else
    echo "-> IGW ya existe: $igw"
fi

# --- Subred publica (una sola: sin ALB ni multi-AZ a este presupuesto) ------
subred="$(aws ec2 describe-subnets --region "$REGION" \
    --filters "Name=tag:Proyecto,Values=$PROYECTO" \
    --query 'Subnets[0].SubnetId' --output text)"
if [ -z "$subred" ] || [ "$subred" = "None" ]; then
    echo "-> creando subred 10.42.1.0/24"
    subred="$(aws ec2 create-subnet --region "$REGION" --vpc-id "$vpc" \
        --cidr-block 10.42.1.0/24 \
        --tag-specifications "ResourceType=subnet,Tags=[{Key=Proyecto,Value=$PROYECTO}]" \
        --query 'Subnet.SubnetId' --output text)"
    aws ec2 wait subnet-available --region "$REGION" --subnet-ids "$subred"
    aws ec2 modify-subnet-attribute --region "$REGION" --subnet-id "$subred" \
        --map-public-ip-on-launch '{"Value":true}' >/dev/null
else
    echo "-> subred ya existe: $subred"
fi

# --- Tabla de rutas publica --------------------------------------------------
rt="$(aws ec2 describe-route-tables --region "$REGION" \
    --filters "Name=tag:Proyecto,Values=$PROYECTO" \
    --query 'RouteTables[0].RouteTableId' --output text)"
if [ -z "$rt" ] || [ "$rt" = "None" ]; then
    echo "-> creando tabla de rutas"
    rt="$(aws ec2 create-route-table --region "$REGION" --vpc-id "$vpc" \
        --tag-specifications "ResourceType=route-table,Tags=[{Key=Proyecto,Value=$PROYECTO}]" \
        --query 'RouteTable.RouteTableId' --output text)"
    aws ec2 create-route --region "$REGION" --route-table-id "$rt" \
        --destination-cidr-block 0.0.0.0/0 --gateway-id "$igw" >/dev/null
    aws ec2 associate-route-table --region "$REGION" \
        --route-table-id "$rt" --subnet-id "$subred" >/dev/null
else
    echo "-> tabla de rutas ya existe: $rt"
fi

# --- Security Group ----------------------------------------------------------
sg="$(aws ec2 describe-security-groups --region "$REGION" \
    --filters "Name=tag:Proyecto,Values=$PROYECTO" \
    --query 'SecurityGroups[0].GroupId' --output text)"
if [ -z "$sg" ] || [ "$sg" = "None" ]; then
    echo "-> creando Security Group"
    sg="$(aws ec2 create-security-group --region "$REGION" \
        --group-name "$PROYECTO-web" --description "APU GUARD: 80 CloudFront, 22 operador" \
        --vpc-id "$vpc" \
        --tag-specifications "ResourceType=security-group,Tags=[{Key=Proyecto,Value=$PROYECTO}]" \
        --query 'GroupId' --output text)"
else
    echo "-> SG ya existe: $sg"
fi

# 80 SOLO desde CloudFront (el prefix list pesa 55 reglas)
aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$sg" \
    --ip-permissions '[{"IpProtocol":"tcp","FromPort":80,"ToPort":80,"PrefixListIds":[{"PrefixListId":"'"$pl_id"'"}]}]' \
    2>/dev/null && echo "   [OK] 80 desde prefix list de CloudFront" \
    || echo "   [ya estaba] 80 desde prefix list de CloudFront"

# 22: primero se borra lo que hubiera (asi un cambio de IP de casa se aplica)
reglas22="$(aws ec2 describe-security-groups --region "$REGION" --group-ids "$sg" \
    --query 'SecurityGroups[0].IpPermissions[?FromPort==`22`]' --output json)"
if [ -n "$reglas22" ] && [ "$reglas22" != "[]" ]; then
    aws ec2 revoke-security-group-ingress --region "$REGION" --group-id "$sg" \
        --ip-permissions "$reglas22" >/dev/null 2>&1 || true
fi
aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$sg" \
    --ip-permissions '[{"IpProtocol":"tcp","FromPort":22,"ToPort":22,"IpRanges":[{"CidrIp":"'"$SSH_CIDR"'"}]}]' \
    >/dev/null && echo "   [OK] 22 desde $SSH_CIDR"

reglas="$(aws ec2 describe-security-groups --region "$REGION" --group-ids "$sg" --output text)"
echo "   Reglas actuales (ver: aws ec2 describe-security-groups --group-ids $sg):"
echo "$reglas" | head -20

# --- Par de claves -----------------------------------------------------------
KEY_NAME="$PROYECTO-ec2"
KEY_FILE="$HOME/.ssh/${KEY_NAME}.pem"
mkdir -p "$HOME/.ssh"
if aws ec2 describe-key-pairs --region "$REGION" --key-names "$KEY_NAME" >/dev/null 2>&1; then
    echo "-> par de claves ya existe: $KEY_NAME"
else
    echo "-> creando par de claves $KEY_NAME"
    aws ec2 create-key-pair --region "$REGION" --key-name "$KEY_NAME" \
        --key-type rsa --query 'KeyMaterial' --output text > "$KEY_FILE"
    chmod 600 "$KEY_FILE"
    echo "   guardada en $KEY_FILE"
fi

# --- Rol de instancia + instance profile ------------------------------------
ROL="$PROYECTO-ec2"
if aws iam get-role --role-name "$ROL" >/dev/null 2>&1; then
    echo "-> rol $ROL ya existe"
else
    echo "-> creando rol $ROL"
    aws iam create-role --role-name "$ROL" \
        --assume-role-policy-document "$(cat "$DIR/confianza-rol.json")" >/dev/null
fi

sed -e "s/__CUENTA__/$cuenta/g" -e "s/__REGION__/$REGION/g" \
    "$DIR/politica-instancia.tmpl.json" > "$DIR/.politica-instancia.json"
aws iam put-role-policy --role-name "$ROL" --policy-name "$PROYECTO-minima" \
    --policy-document "$(cat "$DIR/.politica-instancia.json")" >/dev/null
rm -f "$DIR/.politica-instancia.json"
echo "   [OK] politica minima aplicada (S3/SQS/SNS/SageMaker)"

if aws iam get-instance-profile --instance-profile-name "$ROL" >/dev/null 2>&1; then
    echo "-> instance profile $ROL ya existe"
else
    aws iam create-instance-profile --instance-profile-name "$ROL" >/dev/null
fi
if aws iam get-instance-profile --instance-profile-name "$ROL" \
    --query 'InstanceProfile.Roles[0].RoleName' --output text 2>/dev/null | grep -q "^$ROL$"; then
    echo "   [ya estaba] $ROL unido al instance profile"
else
    aws iam add-role-to-instance-profile --instance-profile-name "$ROL" \
        --role-name "$ROL" >/dev/null
    echo "   [OK] $ROL unido al instance profile"
fi

echo
echo "=== RESUMEN Fase D paso 1 ==="
echo "  vpc=$vpc  subred=$subred  sg=$sg  rol=$ROL"
echo "  clave SSH: $KEY_FILE"
echo "  Siguiente: ./20_instancia.sh"
