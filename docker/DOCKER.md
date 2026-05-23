# Running earmark with Docker

earmark ships as a single multi-stage `Dockerfile`. `docker compose up` starts three containers — backend, frontend, and nginx — behind a single exposed port.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Compose v2 (`docker compose`)

## Quickstart

```bash
cp .env.example .env
# Edit .env: set SECRET_KEY, AUDIOBOOKSHELF_URL, AUDIOBOOKSHELF_API_KEY
docker compose -f docker/docker-compose.yml up -d
```

Open `http://localhost:7070` in your browser.

## Environment variables

Copy `.env.example` to `.env` and fill in the values before starting.

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | **yes** | — | Random secret for signing JWTs. Must be the same value for backend and frontend. |
| `AUDIOBOOKSHELF_URL` | **yes** | — | URL of your Audiobookshelf server, e.g. `http://192.168.1.10:13378` |
| `AUDIOBOOKSHELF_API_KEY` | **yes** | — | API key from Audiobookshelf → Settings → API Keys |
| `SYNC_INTERVAL_SECONDS` | no | `300` | How often to sync progress between ABS and KOSync |
| `EBOOK_LOCAL_ROOT` | no | `.` | Root path for local ebook files (inside the container) |
| `TIMEZONE` | no | `America/New_York` | IANA timezone for timestamps |
| `LOG_LEVEL` | no | `INFO` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |
| `PORT` | no | `7070` | External port for the web UI |
| `ORIGIN` | no | `http://localhost:7070` | Public URL of the app — set this to your server's address when deploying remotely, e.g. `http://192.168.1.20:7070` |

## KOReader / KOSync setup

Point KOReader's KOSync plugin at:

```
Server: http://<your-host>:7070
Path:   /syncs
```

Use a KOSync username and password created via the earmark web UI (Users → Add KOSync User).

## Data persistence

All data (SQLite database, alignment cache) is stored in a Docker named volume `earmark-data`. It persists across `docker compose down` and image rebuilds.

## Updating

```bash
docker compose -f docker/docker-compose.yml build --no-cache
docker compose -f docker/docker-compose.yml up -d
```

## Stopping

```bash
docker compose -f docker/docker-compose.yml down          # stop containers, keep data
docker compose -f docker/docker-compose.yml down -v       # stop containers AND delete all data
```
