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

Requires Python 3.12 or 3.13 (WhisperX pulls in PyTorch, which has no Python 3.14 wheels yet) and [uv](https://github.com/astral-sh/uv).

```bash
uv python install 3.13               # if 3.13 isn't already installed
uv venv --python 3.13                # only needed if your default uv venv is on a newer Python
uv sync --extra align                # WhisperX + torch — required for alignment jobs
                                     # (use plain `uv sync` if you only need progress sync)
uv run earmark-seed                  # create and seed the local database
uv run fastapi dev src/earmark/main.py --reload-dir src/earmark   # dev server on :8000
```

The `[align]` extra is roughly 2 GB of model dependencies. Skip it if you only need progress sync (the KOSync server, scheduler, and web UI all work without it); alignment jobs will fail with `ModuleNotFoundError: No module named 'whisperx'` until it's installed.

The seed command creates two users and five reading progress records for local development:

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
