# Settings

earmark supports runtime configuration through a database-backed settings system. Database values override environment variables when set; env vars remain the fallback for any setting that has no DB value.

## Precedence

```
DB value (if set and non-empty)  →  env var / code default
```

Settings that are **env-only** and cannot be overridden from the UI:

| Env var | Reason |
|---------|--------|
| `DATABASE_URL` | Required before the DB is available |
| `LOG_LEVEL` | Affects log configuration at startup |
| `LOG_PRETTY` | Affects log configuration at startup |
| `LOG_REQUESTS` | Affects log configuration at startup |

---

## Database schema — `app_settings`

| Column | Type | Notes |
|--------|------|-------|
| `key` | `VARCHAR(100)` | Primary key; matches `config.py` field names |
| `label` | `VARCHAR(200)` | Human-readable name shown in the UI |
| `description` | `TEXT` | Help text shown in the UI |
| `value_type` | `VARCHAR(20)` | `string` \| `int` \| `password` |
| `value` | `TEXT` (nullable) | `NULL` = use env default |
| `is_secret` | `BOOLEAN` | Secrets are encrypted at rest (see below) |
| `updated_at` | `DATETIME` | Auto-updated on write |

---

## Secret encryption

Settings with `is_secret=True` (API keys, usernames, passwords) are **Fernet-encrypted** before being written to the database.

- **Algorithm**: Fernet symmetric encryption (`cryptography` package, already a transitive dependency via `python-jose[cryptography]`).
- **Key derivation**: `base64url(SHA-256(settings.secret_key))` — a 32-byte key derived from the app's `SECRET_KEY` env var.
- **At rest**: the `value` column stores the Fernet token (base64-encoded ciphertext + HMAC).
- **At call time**: decrypted in memory and passed directly to the external service (ABS, Calibre Web).
- **In API responses**: secret values are **never returned**. The `display_value` field is always `"••••••••"` for `is_secret=True` settings, regardless of whether a DB value is set.

> **Rotation**: Changing `SECRET_KEY` will invalidate all encrypted DB values. Clear and re-enter secrets after rotating the key.

---

## Seeded settings

These rows are inserted at startup if they do not already exist (idempotent). `value` starts as `NULL` for all — the app falls back to env vars until explicitly set.

| key | label | value_type | is_secret | Env fallback |
|-----|-------|------------|-----------|--------------|
| `audiobookshelf_url` | Audiobookshelf URL | string | No | `AUDIOBOOKSHELF_URL` |
| `audiobookshelf_api_key` | Audiobookshelf API Key | password | Yes | `AUDIOBOOKSHELF_API_KEY` |
| `cwa_url` | Calibre Web URL | string | No | `CWA_URL` |
| `cwa_username` | Calibre Web Username | string | Yes | `CWA_USERNAME` |
| `cwa_password` | Calibre Web Password | password | Yes | `CWA_PASSWORD` |
| `timezone` | Timezone | string | No | `TIMEZONE` |
| `sync_interval_seconds` | Sync Interval (seconds) | int | No | `SYNC_INTERVAL_SECONDS` |
| `sync_abs_idle_seconds` | ABS Idle Threshold (seconds) | int | No | `SYNC_ABS_IDLE_SECONDS` |

---

## API

All endpoints require a valid Bearer token (`Authorization: Bearer <jwt>`).

### `GET /web/settings`

Returns all settings. Secret values are masked.

**Response** — `200 OK`, array of:

```json
[
  {
    "key": "audiobookshelf_url",
    "label": "Audiobookshelf URL",
    "description": "URL of your Audiobookshelf server (e.g. http://localhost:13378)",
    "value_type": "string",
    "is_secret": false,
    "has_db_value": true,
    "display_value": "http://abs.local:13378"
  },
  {
    "key": "audiobookshelf_api_key",
    "label": "Audiobookshelf API Key",
    "description": "API key for your Audiobookshelf account",
    "value_type": "password",
    "is_secret": true,
    "has_db_value": true,
    "display_value": "••••••••"
  }
]
```

| Field | Description |
|-------|-------------|
| `has_db_value` | `true` if a DB value overrides the env var |
| `display_value` | The effective value for non-secrets; `"••••••••"` for secrets |

### `PUT /web/settings/{key}`

Set or update a setting value. For secrets, the value is encrypted before storage.

Changing `sync_interval_seconds` triggers an immediate scheduler reschedule so the new interval takes effect without restart.

**Request body:**
```json
{ "value": "http://abs.local:13378" }
```

**Response** — `200 OK`, updated setting object (same shape as GET item).

**Errors:**
- `404` — unknown key
- `422` — value fails type validation (e.g. non-integer for `int` type)

### `DELETE /web/settings/{key}`

Clears the DB value, reverting the setting to the env var / code default.

**Response** — `200 OK`, updated setting object with `has_db_value: false`.

---

## Overlay pattern (implementation guide)

Services never read `settings.*` directly for configurable values. Instead:

```python
# app_settings.py
async def get_effective_str(key: str, default: str, session: AsyncSession) -> str:
    row = await session.get(AppSetting, key)
    if row is None or not row.value:
        return default
    return decrypt_secret(row.value) if row.is_secret else row.value

async def get_effective_int(key: str, default: int, session: AsyncSession) -> int:
    val = await get_effective_str(key, str(default), session)
    try:
        return int(val)
    except ValueError:
        return default
```

Services that accept configurable values (e.g. `AudiobookshelfClient`, `CalibreOpdsSource`) accept optional constructor parameters so callers can pass the effective values:

```python
# Caller resolves effective settings then constructs the client:
url = await get_effective_str("audiobookshelf_url", settings.audiobookshelf_url, session)
api_key = await get_effective_str("audiobookshelf_api_key", settings.audiobookshelf_api_key, session)
client = AudiobookshelfClient(url=url, api_key=api_key)
```

---

## Frontend settings page (`/settings`)

Three sections corresponding to the three external integrations and application-level options:

1. **Audiobookshelf** — URL, API Key
2. **Calibre Web** — URL, Username, Password
3. **Application** — Timezone, Sync Interval, ABS Idle Threshold

UI rules:
- Non-secret fields are pre-filled with the current `display_value`.
- Secret fields (`is_secret=True`) are **never pre-filled**. A "currently set" badge is shown when `has_db_value=true`.
- Each field has a **Clear** button that sends `DELETE /web/settings/{key}` to revert to the env default.
- Env defaults are shown as placeholder text on each input.
