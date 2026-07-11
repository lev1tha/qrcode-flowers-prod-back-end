#!/usr/bin/env bash
#
# Установка зависимостей на ЧИСТЫЙ сервер (Ubuntu 22.04/24.04 или Debian 12).
# Запускать от root:  bash bootstrap.sh
#
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

echo "→ apt update + базовые пакеты"
apt-get update -y
apt-get install -y ca-certificates curl gnupg git ufw nginx

echo "→ Docker Engine + compose plugin"
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

echo "→ Node.js 22 LTS (для Vite dev-сервера фронта)"
if ! command -v node >/dev/null 2>&1; then
  # Если Ubuntu слишком свежая и NodeSource ещё не поддерживает её codename —
  # фолбэк: apt-get install -y nodejs npm (из репозиториев Ubuntu).
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && apt-get install -y nodejs \
    || apt-get install -y nodejs npm
fi

echo "→ certbot (Let's Encrypt, nginx-плагин)"
apt-get install -y certbot python3-certbot-nginx

echo "→ firewall: SSH + HTTP/HTTPS"
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable

echo ""
echo "✓ Готово:"
docker --version
docker compose version
node --version
nginx -v
echo "✓ Дальше — по DEPLOY.md (клонирование репозиториев и запуск)."
