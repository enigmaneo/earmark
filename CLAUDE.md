# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`earmark` syncs Audiobookshelf and KOSync reading progress. It runs its own KOSync server. The repository is in early setup — no source code, build tooling, or package configuration exists yet. Update this file as the project takes shape.

## Rules

- **Prefer well-known packages** over custom implementations. If a library solves the problem, use it.
- **Favor readable code** over clever or complex solutions. Clarity beats brevity.

## Setup & Commands

No build system has been configured yet. Once `pyproject.toml` or equivalent is added, document the install, test, and lint commands here. The `.gitignore` references these tools as likely choices:

- **Tests:** pytest
- **Linting/formatting:** ruff
- **Type checking:** mypy
