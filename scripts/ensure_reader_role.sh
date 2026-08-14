#!/bin/bash
# Ensures the read-only ws_reader role (used by the dashboard) exists and
# matches READER_PASSWORD from .env. Idempotent, so deploy.sh runs it on
# every deploy: init.sql only creates the role on a FRESH data volume, and
# both the VPS and local dev volumes predate it.
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root, where compose.yaml and .env live

get_env() { grep -E "^$1=" .env | cut -d= -f2-; }
POSTGRES_USER=$(get_env POSTGRES_USER)
POSTGRES_DB=$(get_env POSTGRES_DB)
READER_PASSWORD=$(get_env READER_PASSWORD)

if [ -z "$READER_PASSWORD" ]; then
    echo "READER_PASSWORD is not set in .env (see .env.example)" >&2
    exit 1
fi

# stdin (not -c) so psql interpolates :'pw' — the password never lands on a
# command line; the heredoc is quoted so bash leaves $$ and :'pw' to psql.
docker compose exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -v ON_ERROR_STOP=1 -v pw="$READER_PASSWORD" --quiet <<'SQL'
DO $$ BEGIN
    CREATE ROLE ws_reader;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
ALTER ROLE ws_reader LOGIN PASSWORD :'pw';
GRANT SELECT ON sensor_readings TO ws_reader;
SQL

echo "ws_reader role OK"
