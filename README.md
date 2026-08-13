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
| `api` | build `./api` locally, GHCR image on the VPS | none | Flask + gunicorn: `POST /sensor`, `GET /table` |
| `db` | `postgres:17` | none | storage on a named volume, schema from `db/init.sql` |

CI (GitHub Actions, [ci.yml](.github/workflows/ci.yml)): every push and PR
runs ruff + pytest and builds the Docker image; pushes to `main` also publish
it to GHCR as `ghcr.io/shchurov-nk/weather-station-api` (`latest` + `sha-<short>`).
The VPS never builds: `scripts/deploy.sh` pulls that image and restarts the
stack. `API_TAG` in `.env` pins an older tag to roll back.

## Quickstart (local)

```bash
git clone https://github.com/Shchurov-nk/weather-station.git
cd weather-station
cp .env.example .env      # edit passwords and SENSOR_TOKEN
docker compose up -d --build
```

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

- **`docker compose down` keeps the data, `down -v` DESTROYS it.** The
  database lives on the named volume `pgdata`, not in the container.
- **`db/init.sql` runs only when that volume is empty** (first boot).
  Changing it afterwards does nothing to a live database — either apply the
  change by hand with `docker compose exec db psql`, or recreate the volume
  with `down -v` (losing the data).
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
address 0x76. TLS roots are pinned in `esp32/certs.h` (ISRG Root X1/X2 plus
the next-gen Root YE/YR, valid to 2035–2045); certificate renewals need no
firmware action.

## History

The learning write-ups that accompanied earlier iterations of this project
(Docker walkthrough, CI/CD walkthrough, roadmap) live in
[docs/archive/](docs/archive/).
