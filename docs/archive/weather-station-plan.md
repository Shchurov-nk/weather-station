# Weather station — rebuild plan (review requested)

Repo: https://github.com/Shchurov-nk/weather-station

## Context

Home weather station: ESP32 + BME280 sensor POSTs JSON over wifi to a Flask app,
which writes to Postgres and renders an HTML table.

It ran on an old laptop. **The laptop is gone.** Setup was manual and undocumented,
so the DB schema, gunicorn/systemd config and Arduino IDE library setup are all lost.
Historical data is lost too. Schema has been reconstructed from the SQL in the code.

I'm a data scientist, comfortable with Python, new to Docker and to running a server.

## Goal

Move to a rented VPS, make the whole thing reproducible from a clean `git clone`,
and add a Streamlit dashboard.

## Target architecture

One `docker compose` stack on the VPS:

| Service | Image / build | Published ports | Role |
|---|---|---|---|
| `caddy` | `caddy:2` | 80, 443 | TLS termination, only public entry point |
| `api` | build `./api` | none | Flask + gunicorn, `POST /sensor` |
| `dashboard` | build `./dashboard` | none | Streamlit, read-only DB user |
| `db` | `postgres:17` | none | Postgres on a named volume |

Key rule: only `caddy` publishes ports. Everything else talks over the internal
Compose network. Config via env vars (`.env` gitignored, `.env.example` committed).
Schema changes only ever via numbered files in `db/migrations/`.

## Plan (each phase has an acceptance test)

0. **Commit the reconstructed schema** + index + CHECK constraints. Fix missing
   `#include "config.h"` in the firmware. Fix `.gitignore`.
   → clean clone can rebuild the DB
1. **Local reproducibility.** Pin deps (uv), env-var config, Dockerfiles
   (`python:3.13-slim`, non-root), `compose.yaml` with named volume,
   `pg_isready` healthcheck, `restart: unless-stopped`.
   → `docker compose up` works from scratch; data survives `down`/`up`
2. **Harden the API.** Bearer token on `/sensor`, pydantic validation,
   `psycopg_pool`, logging, no `str(e)` in responses.
   → unauth = 401, malformed = 422, nothing leaks
3. **VPS.** SSH keys only, ufw 22/80/443, Caddy + Let's Encrypt.
   → HTTPS works; external scan shows only 3 open ports
4. **Backups.** Nightly `pg_dump` copied off the VPS.
   → I have actually restored one
5. **Streamlit dashboard.** Cached queries, time-series plots, range selector.
6. **Firmware.** PlatformIO with pinned lib versions, ring buffer + retry so
   outages don't create gaps.
7. **CI.** GitHub Actions: ruff + pytest against a Postgres service container.

Deliberately deferred: TimescaleDB, Grafana, MQTT. Nice to learn, but they don't
solve a problem I have yet.

## Decisions I'd like you to sanity-check

- Streamlit over Grafana. I know Grafana is the right tool for time-series and
  would take 15 minutes; I'm choosing Streamlit to learn and for the portfolio.
  Bad call?
- Caddy over nginx + certbot, to avoid learning two things at once.
- Sensor interval: dropping 6s → 60s. Enough?
- **ESP32 → VPS transport.** This is the bit I'm least sure about. Data now
  crosses the public internet. Options I see: (a) HTTPS with `setInsecure()`,
  (b) WireGuard tunnel from home to VPS, (c) plain HTTP with a bearer token.
  Which would you pick?
- Deploy story: `git pull && docker compose up -d --build` on the server to start,
  graduating to build-in-CI → push to GHCR → pull on server. Reasonable, or go
  straight to the second?
- Am I over- or under-engineering anywhere?
