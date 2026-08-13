#!/bin/bash
# Nightly Postgres dump. Cron on the VPS (as deploy):
#   10 2 * * * /opt/weather-station/scripts/backup.sh >> /home/deploy/backup.log 2>&1
# The off-VPS copy is PULLED from home — see docs/vps-runbook.md §10.
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root, where compose.yaml lives
mkdir -p backups

# -Fc = custom format: compressed, and pg_restore can restore it selectively.
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
    > "backups/ws_$(date +%F).dump"

# Keep two weeks locally; older copies live off-VPS.
find backups/ -name 'ws_*.dump' -mtime +14 -delete

# Dead man's switch: healthchecks.io alerts when this line stops arriving.
# Uncomment after registering a check:
# curl -fsS -m 10 --retry 3 https://hc-ping.com/YOUR-UUID-HERE > /dev/null
