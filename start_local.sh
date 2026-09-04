#!/usr/bin/env bash
# Start family.poweredby.top on this laptop (MariaDB + Flask)
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "Missing .env — copy .env.example before starting."
  exit 1
fi

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
fi

echo "Starting MariaDB (docker)..."
docker compose up -d

echo "Waiting for MariaDB healthy..."
for i in $(seq 1 40); do
  status=$(docker inspect --format='{{.State.Health.Status}}' family-mariadb 2>/dev/null || echo starting)
  [[ "$status" == "healthy" ]] && break
  sleep 1
done

echo "Starting Flask on http://127.0.0.1:8060 (loopback). Tailscale Serve wraps HTTPS."
source .venv/bin/activate
export DEBUG_MODE=true
exec python main.py
