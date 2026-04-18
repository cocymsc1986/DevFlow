#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/cocymsc1986/devflow.git"
APP_DIR="/home/ubuntu/DevFlow"

apt-get update -y
apt-get install -y python3 python3-pip python3-venv nginx git curl

curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt-get install -y nodejs

git clone "$REPO_URL" "$APP_DIR" 2>/dev/null || git -C "$APP_DIR" pull

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/backend/requirements.txt"

cd "$APP_DIR/frontend" && npm install --silent && npm run build

cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/devflow
ln -sf /etc/nginx/sites-available/devflow /etc/nginx/sites-enabled/devflow
rm -f /etc/nginx/sites-enabled/default
systemctl enable nginx && systemctl restart nginx

cp "$APP_DIR/deploy/devflow.service" /etc/systemd/system/devflow.service
systemctl daemon-reload
systemctl enable devflow
# Service starts only when .env exists — user creates it after first boot
[ -f "$APP_DIR/.env" ] && systemctl start devflow || true
