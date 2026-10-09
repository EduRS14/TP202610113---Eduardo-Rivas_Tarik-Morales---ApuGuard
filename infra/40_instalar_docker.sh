#!/usr/bin/env bash
# =============================================================================
# 40_instalar_docker.sh — Fase D
# Se ejecuta DENTRO del EC2 (Amazon Linux 2023), no en local.
#
#   ssh -i ~/.ssh/apuguard-ec2.pem ec2-user@<ip> 'bash -s' < infra/40_instalar_docker.sh
#
# Instala Docker, el plugin de `docker compose`, gira los logs del demonio
# (CloudWatch Logs esta bloqueado: sin rotacion, los logs llenarian el disco
# de 20 GB) y crea /opt/apuguard.
# =============================================================================
set -euo pipefail

echo "-> instalando Docker (paquete de Amazon Linux 2023)"
sudo dnf -y install docker >/dev/null
sudo systemctl enable --now docker

# `docker compose` (plugin v2). Si el paquete de Amazon no lo trae, se baja
# el binario oficial al directorio de cli-plugins.
if ! docker compose version >/dev/null 2>&1; then
    echo "-> plugin de compose no incluido: descargando"
    sudo mkdir -p /usr/local/lib/docker/cli-plugins
    sudo curl -fsSL \
        "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose
    sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
fi

echo "-> rotacion de logs del demonio (10 MB x 3 por contenedor)"
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'JSON'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
JSON
sudo systemctl restart docker

sudo usermod -aG docker ec2-user || true
sudo mkdir -p /opt/apuguard && sudo chown ec2-user:ec2-user /opt/apuguard

echo
echo "  docker        : $(docker --version)"
echo "  docker compose: $(docker compose version)"
echo "  proyecto      : /opt/apuguard"
echo
echo "  Para usar docker sin sudo en esta sesion:"
echo "    newgrp docker"
