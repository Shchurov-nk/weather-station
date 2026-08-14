#!/bin/bash
# Deploys the current checkout on the VPS: pull the api image from GHCR and
# restart what changed. CI runs this over ssh AFTER `git pull --ff-only` — the
# pull stays outside because bash reads this file as it executes, so a script
# that rewrites itself mid-run does something unpredictable. Safe by hand too.
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root, where compose.yaml lives

# Only our images: postgres/caddy upgrades stay deliberate, not a deploy side effect.
docker compose pull api dashboard

# The dashboard's read-only db role. Idempotent; needs db up, and on any
# deploy after the first the stack is already running.
./scripts/ensure_reader_role.sh

docker compose up -d
docker compose ps

# The Caddyfile is a bind mount: `up -d` won't recreate caddy when only the
# file's content changed, and caddy reads it once at startup. Graceful and a
# no-op when the config is unchanged.
docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile

# Smoke test through the public hostname, the same path a browser takes.
# Retried: `up -d` returns as soon as the container starts, a second or two
# before uvicorn accepts connections.
DOMAIN=$(grep -E '^DOMAIN=' .env | cut -d= -f2-)
for _ in $(seq 30); do
    # No -S: an early 502 is expected, only the final verdict is worth printing.
    if curl -fs --max-time 5 "https://${DOMAIN}/table" > /dev/null \
        && curl -fs --max-time 5 "https://${DOMAIN}/_stcore/health" > /dev/null; then
        echo "smoke OK"
        # Old image layers add up fast on a small disk.
        docker image prune -f
        exit 0
    fi
    sleep 1
done

echo "smoke FAILED: /table or dashboard /_stcore/health unreachable after 30s" >&2
docker compose logs --tail 50 api dashboard
exit 1
