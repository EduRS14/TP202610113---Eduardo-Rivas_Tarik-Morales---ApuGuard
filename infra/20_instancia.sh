#!/usr/bin/env bash
# =============================================================================
# 20_instancia.sh — Fase D, paso 2
#
# Crea (o reutiliza) el EC2 de APU GUARD:
#   t3.small + Amazon Linux 2023 + gp3 20 GB + IMDSv2 obligatorio + EIP
#
# El resize manual a m7i-flex.large se hace el dia 15 y se mantiene hasta el
# dia 2 del mes siguiente (bajar a t3.small el dia 3) para cubrir las
# quincenas automaticas de los dias 16 y 1 (Fase 0.4):
#   aws ec2 stop-instances ... && aws ec2 modify-instance-attribute --instance-type m7i-flex.large ...
#   (ver infra/README.md; NO se para la instancia solo por la EIP:
#    una EIP desasociada cuesta ~0.005 USD/h = ~3.6 USD/mes)
#
# Requiere ./10_red_y_permisos.sh ejecutado antes.
# Idempotente.
# =============================================================================
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
PROYECTO="apuguard"
TIPO="${INSTANCIA_TIPO:-t3.small}"

tag() { printf 'ResourceType=%s,Tags=[{Key=Proyecto,Value=%s},{Key=Nombre,Value=%s}]' "$1" "$PROYECTO" "$2"; }

vpc="$(aws ec2 describe-vpcs --region "$REGION" --filters "Name=tag:Proyecto,Values=$PROYECTO" \
    --query 'Vpcs[0].VpcId' --output text)"
subred="$(aws ec2 describe-subnets --region "$REGION" --filters "Name=tag:Proyecto,Values=$PROYECTO" \
    --query 'Subnets[0].SubnetId' --output text)"
sg="$(aws ec2 describe-security-groups --region "$REGION" --filters "Name=tag:Proyecto,Values=$PROYECTO" \
    --query 'SecurityGroups[0].GroupId' --output text)"

for var in vpc subred sg; do
    if [ -z "${!var}" ] || [ "${!var}" = "None" ]; then
        echo "[FALLA] falta $var. Ejecuta primero ./10_red_y_permisos.sh"
        exit 1
    fi
done
ROL="$PROYECTO-ec2"

# --- AMI de Amazon Linux 2023 ------------------------------------------------
ami="$(aws ec2 describe-images --region "$REGION" --owners amazon \
    --filters "Name=name,Values=al2023-ami-*-x86_64" \
              "Name=architecture,Values=x86_64" \
              "Name=state,Values=available" \
              "Name=root-device-type,Values=ebs" \
    --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text)"
if [ -z "$ami" ] || [ "$ami" = "None" ]; then
    echo "[FALLA] no se encontro AMI de Amazon Linux 2023 en $REGION"
    exit 1
fi
echo "AMI              : $ami"
echo "Tipo             : $TIPO"

# --- Instancia ---------------------------------------------------------------
inst="$(aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:Proyecto,Values=$PROYECTO" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[0].Instances[0].InstanceId' --output text)"
if [ -z "$inst" ] || [ "$inst" = "None" ]; then
    echo "-> creando instancia"
    inst="$(aws ec2 run-instances --region "$REGION" \
        --image-id "$ami" \
        --instance-type "$TIPO" \
        --key-name "$PROYECTO-ec2" \
        --subnet-id "$subred" \
        --security-group-ids "$sg" \
        --iam-instance-profile "Name=$ROL" \
        --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":20,"VolumeType":"gp3","DeleteOnTermination":true}}]' \
        --metadata-options 'HttpTokens=required,HttpEndpoint=enabled' \
        --tag-specifications "$(tag instance "$PROYECTO-web")" "$(tag volume "$PROYECTO-vol")" \
        --query 'Instances[0].InstanceId' --output text)"
    echo "   instance-id: $inst"
    aws ec2 wait instance-running --region "$REGION" --instance-ids "$inst"
else
    echo "-> instancia ya existe: $inst"
    estado="$(aws ec2 describe-instances --region "$REGION" --instance-ids "$inst" \
        --query 'Reservations[0].Instances[0].State.Name' --output text)"
    echo "   estado: $estado"
    if [ "$estado" != "running" ]; then
        aws ec2 start-instances --region "$REGION" --instance-ids "$inst" >/dev/null
        aws ec2 wait instance-running --region "$REGION" --instance-ids "$inst"
    fi
fi

# --- Elastic IP (gratis mientras este adjunta a una instancia en ejecucion) ---
alloc="$(aws ec2 describe-addresses --region "$REGION" \
    --filters "Name=tag:Proyecto,Values=$PROYECTO" \
    --query 'Addresses[0].AllocationId' --output text)"
if [ -z "$alloc" ] || [ "$alloc" = "None" ]; then
    echo "-> reservando Elastic IP"
    alloc="$(aws ec2 allocate-address --region "$REGION" --domain vpc \
        --tag-specifications "$(tag elastic-ip "$PROYECTO-eip")" \
        --query 'AllocationId' --output text)"
else
    echo "-> EIP ya reservada: $alloc"
fi

asociada="$(aws ec2 describe-addresses --region "$REGION" --allocation-ids "$alloc" \
    --query 'Addresses[0].InstanceId' --output text)"
if [ "$asociada" = "$inst" ]; then
    echo "   [ya estaba] EIP asociada a $inst"
else
    echo "-> asociando EIP"
    aws ec2 associate-address --region "$REGION" --instance-id "$inst" \
        --allocation-id "$alloc" >/dev/null
fi

dns="$(aws ec2 describe-instances --region "$REGION" --instance-ids "$inst" \
    --query 'Reservations[0].Instances[0].PublicDnsName' --output text)"
ip="$(aws ec2 describe-addresses --region "$REGION" --allocation-ids "$alloc" \
    --query 'Addresses[0].PublicIp' --output text)"

echo
echo "=== RESUMEN Fase D paso 2 ==="
echo "  instancia : $inst ($TIPO)"
echo "  IP publica: $ip"
echo "  DNS       : $dns"
echo "  SSH       : ssh -i ~/.ssh/$PROYECTO-ec2.pem ec2-user@$ip"
echo "  Siguiente : ./30_cloudfront.sh $dns"
