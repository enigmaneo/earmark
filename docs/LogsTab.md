# Logs Tab

`earmark` writes application logs to rotating files on disk and exposes them through an
authenticated API and a **Logs** tab in the web UI. This lets an operator inspect recent
sync/alignment activity from the browser without attaching to the container.

## Overview

- Logs are written as **JSON lines** (one JSON object per line) to a file in the `logs/` directory
  (`logs/earmark.log`), in addition to the existing human-readable console output.
- Rotation is handled by Python's stdlib rotating handlers — **no scheduler task**. The strategy is
  selectable (size- or time-based) and defaults to size-based so nothing needs to be configured.
- The API reads and filters the log files; it never stores log content in the database.
- The UI tab supports filtering by **level**, **text**, **date/time range**, and **which file** to view.

## Configuration

Environment defaults live in [`src/earmark/config.py`](../src/earmark/config.py); the runtime-tunable
ones are also surfaced as DB-backed settings (see [`Settings.md`](Settings.md)) so they can be changed
from the Settings tab without a restart. Each setting falls back to its env default when unset, so the
feature works out of the box.

| Setting key | Env var | Type | Default | Meaning |
|---|---|---|---|---|
| _(env only)_ | `LOG_DIR` | path | `./logs` | Directory the log file is written to |
| `log_rotation_strategy` | `LOG_ROTATION_STRATEGY` | string | `size` | `size` (RotatingFileHandler) or `time` (TimedRotatingFileHandler) |
| `log_max_size_mb` | `LOG_MAX_SIZE_MB` | int | `10` | Size strategy: rotate when the file exceeds this many MB |
| `log_rotation_when` | `LOG_ROTATION_WHEN` | string | `midnight` | Time strategy: `TimedRotatingFileHandler` `when` value |
| `log_backup_count` | `LOG_BACKUP_COUNT` | int | `5` | How many rotated files to keep |

Changing any `log_*` setting via `PUT /web/settings/{key}` re-applies the file handler live (same
pattern as rescheduling the sync job).

## Log format

Each line is a JSON object produced by `python-json-logger`:

```json
{"timestamp": "2026-06-14T12:00:01Z", "level": "INFO", "name": "earmark.scheduler", "message": "Sync complete"}
```

Console output is unchanged (plain text, or rich when `LOG_PRETTY=true`).

## API

All endpoints require an earmark web session (`Authorization: Bearer <jwt>`), under the `/web` prefix.

### `GET /web/logs/files`

Lists the current log file and its rotated siblings, newest first.

```json
[
  {"name": "earmark.log", "size_bytes": 20480, "modified_at": "2026-06-14T12:00:01Z"},
  {"name": "earmark.log.1", "size_bytes": 10485760, "modified_at": "2026-06-13T23:59:58Z"}
]
```

### `GET /web/logs`

Returns parsed, filtered, newest-first, paginated log entries.

Query parameters (all optional):

| Param | Default | Meaning |
|---|---|---|
| `file` | current log | Which file to read (must resolve inside `LOG_DIR`) |
| `level` | all | Minimum level — include this level and above (`DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`) |
| `q` | — | Case-insensitive substring match on message + logger name |
| `from` | — | ISO timestamp; include entries at or after this time |
| `to` | — | ISO timestamp; include entries at or before this time |
| `page` | 1 | 1-based page number |
| `per_page` | 100 | Page size (1–200) |

```json
{
  "data": [
    {"timestamp": "2026-06-14T12:00:01Z", "level": "INFO", "name": "earmark.scheduler", "message": "Sync complete"}
  ],
  "total": 1,
  "page": 1,
  "per_page": 100
}
```

Malformed lines are tolerated (skipped). An unknown/invalid `file` returns `400`.

## Frontend

The **Logs** tab (`src/frontend/src/routes/logs/`) follows the Progress page conventions
(see [`Frontend.md`](Frontend.md)): a filter row (level select, text input, from/to datetime inputs,
file select), a `table table-hover` of entries, and Previous/Next pagination. Filter state lives in
the URL query string so it survives reloads.

## Bruno

Requests live in `testing/bruno/logs/` (`list-logs.bru`, `list-log-files.bru`), using the shared
`{{jwt_token}}` bearer auth.
