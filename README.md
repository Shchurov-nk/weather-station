# Home weather station

[![ci](https://github.com/Shchurov-nk/weather-station/actions/workflows/ci.yml/badge.svg)](https://github.com/Shchurov-nk/weather-station/actions/workflows/ci.yml)

ESP32 + BME280 posts temperature, humidity and pressure over HTTPS once a
minute; a Flask API validates and stores readings in Postgres. Everything
server-side runs as one `docker compose` stack behind Caddy and is
reproducible from a clean `git clone`.

## Architecture

| Service | Image / build | Published ports | Role |
|---|---|---|---|
| `caddy` | `caddy:2` | 80, 443 | TLS termination, the only public entry point |
| `api` | build `./api` | none | Flask + gunicorn: `POST /sensor`, `GET /table` |
| `db` | `postgres:17` | none | storage on a named volume, schema from `db/migrations/` |

The ESP32 authenticates with a bearer token (`SENSOR_TOKEN`) and validates
the server against the pinned Let's Encrypt root CAs — see
[docs/vps-runbook.md](docs/vps-runbook.md) §8.

## Quickstart (local)

```bash
git clone https://github.com/Shchurov-nk/weather-station.git
cd weather-station
cp .env.example .env      # edit passwords and SENSOR_TOKEN
docker compose up -d --build
```

The schema applies itself on first start (`db/init/` → `db/apply_migrations.sh`).
Locally `DOMAIN=localhost`, so Caddy signs with its internal CA — use `curl -k`:

```bash
curl -k https://localhost/sensor -X POST \
     -H "Authorization: Bearer <SENSOR_TOKEN from .env>" \
     -H 'Content-Type: application/json' \
     -d '{"temp": 21.5, "hum": 40, "pres": 995}'   # -> 201
# then https://localhost/table shows the reading
```

Server deployment (hardening, domain, backups): [docs/vps-runbook.md](docs/vps-runbook.md).

## Things worth knowing

- **`docker compose down` keeps the data, `down -v` destroys it.** The
  database lives on the named volume `pgdata`, not in the container.
- **`db/init/` runs only when that volume is empty** (first boot). Changing
  `POSTGRES_PASSWORD` in `.env` afterwards does *not* change the password of
  the live database.
- **Schema changes = a new numbered file in `db/migrations/`**, applied with
  `docker compose exec db apply_migrations`. The runner records applied files
  in the `schema_migrations` table and skips them next time.
- `reading_time` is stored as `timestamptz` (UTC); convert to local time when
  displaying.

## Development

```bash
cd api
uv sync            # exact versions from uv.lock
uv run pytest      # unit tests (no database needed)
uv run ruff check
```

## Firmware

`esp32/esp32.ino` (Arduino IDE for now; PlatformIO planned). Copy
`esp32/config_example.h` to `config.h` and fill in WiFi credentials, the
server URL and the sensor token. BME280 is on I2C: GPIO21 (SDA), GPIO22 (SCL),
address 0x76.

## Roadmap

See [weather-station-plan.md](weather-station-plan.md): Streamlit dashboard
(read-only DB role already provisioned), PlatformIO firmware with a retry
buffer, CI with ruff + pytest.
