# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`earmark` syncs Audiobookshelf and KOSync reading progress. It runs its own KOSync server.

## User Model

There are two separate user systems:

- **User** (`users` table) — the earmark web app user. Authenticates with email + password (bcrypt). Issues JWT tokens used for the web session.
- **KosyncUser** (`kosync_users` table) — the KOReader/KOSync user. Authenticates with `x-auth-user` / `x-auth-key` headers (MD5 hash, per KOSync protocol). One User can own many KosyncUsers.

Web sessions are stored as HTTP-only cookies (`earmark_session`) containing a JWT Bearer token. The SvelteKit frontend validates the session by calling `GET /auth/me`.

## Docs

Project documentation lives in `docs/`:

- [`docs/KosyncApi.md`](docs/KosyncApi.md) — KOSync API reference
- [`docs/Frontend.md`](docs/Frontend.md) — Frontend design principles (theming, layout, accessibility)
- [`docs/AudioBookEbookMapping.md`](docs/AudioBookEbookMapping.md) — Audiobook-ebook mapping and alignment
- [`docs/AlignmentTesting.md`](docs/AlignmentTesting.md) — Alignment pipeline testing guide
- [`docs/Sync.md`](docs/Sync.md) — Bidirectional ABS ↔ KOSync progress sync

## Rules

- **Prefer well-known packages** over custom implementations. If a library solves the problem, use it.
- **Favor readable code** over clever or complex solutions. Clarity beats brevity.
- **Ask, don't assume** — If something is unclear, ask before writing a single line. Never make silent assumptions about intent, architecture, or requirements.
- **Simplest solution first** — Always implement the simplest thing that could work. Do not add abstractions or flexibility that weren't explicitly requested.
- **Don't touch unrelated code** — If a file or function is not directly part of the current task, do not modify it, even if you think it could be improved.
- **Flag uncertainty explicitly** — If you are not confident about an approach or technical detail, say so before proceeding. Confidence without certainty causes more damage than admitting a gap.

## Setup & Commands

### Backend (Python)

```bash
uv sync                        # install deps (or: pip install -e ".[dev]")
bash scripts/install_aeneas.sh # one-time: install aeneas + espeak (alignment pipeline only)
uv run fastapi dev earmark/main.py   # dev server on :8000
uv run pytest                  # tests
uv run ruff check .            # lint
uv run ruff format .           # format
uv run mypy earmark            # type check
```

> **Note:** `install_aeneas.sh` is only needed if you use the forced-alignment pipeline. It patches `aeneas 1.7.3.0` for numpy 2.x / Python 3.12+ compatibility and installs `espeak`. See [`docs/AlignmentTesting.md`](docs/AlignmentTesting.md) for the full testing guide.

### Frontend (SvelteKit)

```bash
cd frontend
npm install
npm run dev       # dev server on :5173 (proxies /api -> :8000)
npm run build
npm run check     # svelte-check + tsc
```

### Environment

Copy `.env.example` to `.env` and fill in values before running the backend.

Required variables:
- `SECRET_KEY` — used to sign JWTs; must be set to a strong random value in production
