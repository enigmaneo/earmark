# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`earmark` syncs Audiobookshelf and KOSync reading progress. It runs its own KOSync server. The repository is in early setup — no source code, build tooling, or package configuration exists yet. Update this file as the project takes shape.

## Rules

- **Prefer well-known packages** over custom implementations. If a library solves the problem, use it.
- **Favor readable code** over clever or complex solutions. Clarity beats brevity.

## Setup & Commands

### Backend (Python)

```bash
uv sync                        # install deps (or: pip install -e ".[dev]")
uv run fastapi dev earmark/main.py   # dev server on :8000
uv run pytest                  # tests
uv run ruff check .            # lint
uv run ruff format .           # format
uv run mypy earmark            # type check
```

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
