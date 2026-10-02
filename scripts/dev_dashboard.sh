#!/bin/bash
# Run the streamlit dashboard natively on the workstation with hot-reload.
#   scripts/dev_dashboard.sh prod    # read-only ssh tunnel to the VPS db (real, live data)
#   scripts/dev_dashboard.sh local   # local compose db (needs compose.override.yaml with db port 5432)
# Edit dashboard/app.py, save, and the page at http://localhost:8501 reruns.
set -euo pipefail

cd "$(dirname "$0")/.."
MODE=${1:-prod}
VPS=deploy@193.124.115.214
DB_CONTAINER_IP=172.18.0.2     # db container on the VPS compose network

case "$MODE" in
  prod)
    # -L on loopback -> VPN routing doesn't interfere; ExitOnForwardFailure so a
    # busy 5433 fails loudly instead of silently pointing at something else.
    ssh -fN -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 \
        -L 127.0.0.1:5433:$DB_CONTAINER_IP:5432 "$VPS"
    trap 'pkill -f "ssh -fN.*5433:$DB_CONTAINER_IP" || true' EXIT
    PW=$(ssh "$VPS" "grep -E '^READER_PASSWORD=' /opt/weather-station/.env | cut -d= -f2-")
    export DATABASE_URL="postgresql://ws_reader:${PW}@127.0.0.1:5433/weather"
    ;;
  local)
    PW=$(grep -E '^READER_PASSWORD=' .env | cut -d= -f2-)
    export DATABASE_URL="postgresql://ws_reader:${PW}@127.0.0.1:5432/weather"
    ;;
  *) echo "usage: $0 [prod|local]" >&2; exit 1 ;;
esac

export DASHBOARD_TZ=${DASHBOARD_TZ:-$(grep -E '^DASHBOARD_TZ=' .env | cut -d= -f2-)}
cd dashboard
exec uv run streamlit run app.py --server.address=127.0.0.1 --server.headless=true --browser.gatherUsageStats=false
