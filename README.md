# earmark

Syncs reading progress between [Audiobookshelf](https://www.audiobookshelf.org/) and [KOReader](https://koreader.rocks/) via a built-in KOSync-compatible server.

## How it works

earmark runs a KOSync-compatible API server that KOReader can sync to directly. A background scheduler periodically pulls progress from Audiobookshelf and pushes updates in both directions, keeping your reading position in sync across devices.

## Stack

- **Backend**: Python / FastAPI, SQLAlchemy (async), APScheduler
- **Frontend**: SvelteKit
- **Database**: SQLite (via aiosqlite + Alembic)

## Setup

### 1. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in your Audiobookshelf URL and API key:

```
AUDIOBOOKSHELF_URL=http://your-abs-host:13378
AUDIOBOOKSHELF_API_KEY=your_api_key_here
SYNC_INTERVAL_SECONDS=300
```

### 2. Backend

Requires Python 3.12 or 3.13 (PyTorch has no Python 3.14 wheels yet) and [uv](https://github.com/astral-sh/uv).

```bash
uv python install 3.13               # if 3.13 isn't already installed
uv venv --python 3.13                # only needed if your default uv venv is on a newer Python
uv sync                              # installs all deps including faster-whisper for alignment
uv run earmark-reset                 # create a clean empty database (fresh install)
uv run earmark-seed                  # alternatively: create and seed with sample data
uv run fastapi dev src/earmark/main.py --reload-dir src/earmark   # dev server on :8000
```

The `[align]` extra is roughly 2 GB of model dependencies. Skip it if you only need progress sync (the KOSync server, scheduler, and web UI all work without it); alignment jobs will fail with `ModuleNotFoundError: No module named 'faster_whisper'` until it's installed.

`earmark-reset` drops and recreates the schema with no data — use this for a clean slate.

`earmark-seed` populates the database with sample users and reading progress for local development:

| Username | Password |
|----------|----------|
| testuser | password |
| alice    | secret   |

Running `earmark-seed` more than once is safe — it skips records that already exist.

### 3. Frontend

```bash
cd src/frontend
npm install
npm run dev   # dev server on :5173 (proxies /api -> :8000)
```

## Development

```bash
uv run pytest          # tests
uv run ruff check .    # lint
uv run ruff format .   # format
uv run mypy src/earmark    # type check

cd src/frontend
npm run check          # svelte-check + tsc
npm run build
```
