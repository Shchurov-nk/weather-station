FROM python:3.13-slim

# Ties the GHCR package to this repo on GitHub.
LABEL org.opencontainers.image.source=https://github.com/Shchurov-nk/weather-station

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

WORKDIR /app

# Dependency layer before the code layer: editing app.py won't bust the
# docker cache and re-download packages. --frozen fails the build if
# uv.lock is out of sync with pyproject.toml instead of silently resolving.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

# Containers don't need root; nothing here writes to disk.
RUN useradd --create-home appuser
USER appuser

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
# 2 workers is plenty for one sensor posting once a minute (README's old
# command used 5). Logs go to stdout so `docker compose logs api` sees them.
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "--access-logfile", "-", "app:app"]
