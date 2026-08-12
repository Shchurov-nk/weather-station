#!/bin/bash
# Runs ONCE, when the postgres image initializes an empty data volume
# (/docker-entrypoint-initdb.d is ignored on every later start).
set -euo pipefail

# The role lives here, not in a migration: .sql files get no env-var
# substitution, so a password from .env can only be injected via shell.
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE dashboard_ro LOGIN PASSWORD '${DASHBOARD_RO_PASSWORD}';
EOSQL

/usr/local/bin/apply_migrations
