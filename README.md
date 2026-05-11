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
SYNC_INTERVAL_MINUTES=5
```

### 2. Backend

Requires Python 3.12+ and [uv](https://github.com/astral-sh/uv).

```bash
uv sync
uv run fastapi dev earmark/main.py   # dev server on :8000
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev   # dev server on :5173 (proxies /api -> :8000)
```

## Development

```bash
uv run pytest          # tests
uv run ruff check .    # lint
uv run ruff format .   # format
uv run mypy earmark    # type check

cd frontend
npm run check          # svelte-check + tsc
npm run build
```
