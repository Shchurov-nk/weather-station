#!/bin/bash
# Idempotent migration runner. Runs INSIDE the db container:
#   first boot:  called by db/init/01_bootstrap.sh
#   later:       docker compose exec db apply_migrations
# Applies /migrations/*.sql in filename order, skipping ones already
# recorded in schema_migrations. Same tracking-table idea alembic/flyway
# use, in ~30 lines of bash we can read.
set -euo pipefail

# `compose exec` runs as root; connect as the app superuser instead.
export PGUSER="$POSTGRES_USER" PGDATABASE="$POSTGRES_DB"

psql -q -v ON_ERROR_STOP=1 -c "
    CREATE TABLE IF NOT EXISTS schema_migrations (
        filename   text PRIMARY KEY,
        applied_at timestamptz NOT NULL DEFAULT now()
    )"

for f in /migrations/*.sql; do
    name=$(basename "$f")
    if [ "$(psql -tA -c "SELECT 1 FROM schema_migrations WHERE filename = '$name'")" = "1" ]; then
        echo "skip   $name"
        continue
    fi
    echo "apply  $name"
    # One transaction for the migration AND its bookkeeping row:
    # either both land or neither does.
    psql -q -v ON_ERROR_STOP=1 --single-transaction \
        -f "$f" \
        -c "INSERT INTO schema_migrations (filename) VALUES ('$name')"
done
