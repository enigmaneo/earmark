# KOSync Server API

earmark implements a KOSync-compatible server that KOReader devices use to sync reading progress. The server is API-compatible with the [official koreader-sync-server](https://github.com/koreader/koreader-sync-server), so any KOReader client can point to it without modification.

## Authentication

All endpoints except `/users/create` and `/healthcheck` require two request headers:

| Header | Description |
|--------|-------------|
| `x-auth-user` | Username |
| `x-auth-key` | MD5 hash of the user's password |

KOReader hashes passwords client-side before sending them. The server never receives a plaintext password after registration.

---

## Endpoints

### POST /users/create

Register a new user account.

#### Request

No authentication required.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `username` | string | yes | Desired username |
| `password` | string | yes | Plaintext password (server stores a hash) |

```json
{
  "username": "alice",
  "password": "hunter2"
}
```

#### Response

| Status | Meaning |
|--------|---------|
| `201 Created` | User created successfully |
| `402 Payment Required` | Username already taken |

```json
{
  "username": "alice"
}
```

---

### GET /users/auth

Verify that a set of credentials is valid. KOReader calls this on startup to confirm the configured account is reachable.

#### Request

Authentication headers required. No request body.

#### Response

| Status | Meaning |
|--------|---------|
| `200 OK` | Credentials are valid |
| `401 Unauthorized` | Invalid username or password |

```json
{
  "authorized": "OK"
}
```

---

### PUT /syncs/progress

Upload the reading position for a document. Each call always creates a new record — existing records are never modified. The most recently created record is marked as the current position and is what `GET /syncs/progress/:document` returns. This endpoint is API-compatible with KOReader; the client behaviour is unchanged.

#### Request

Authentication headers required.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `document` | string | yes | MD5 hash of the book file |
| `progress` | string | yes | XPath position string produced by KOReader |
| `percentage` | number | yes | Reading progress as a fraction from `0.0` to `1.0` |
| `device` | string | yes | Human-readable device name |
| `device_id` | string | yes | Unique device identifier (32 hex chars) |
| `metadata` | object | no | Optional book metadata (see below) |

**metadata object**

| Field | Type | Description |
|-------|------|-------------|
| `filename` | string | Original filename of the book |
| `title` | string | Book title |
| `authors` | string | Author name(s) |

```json
{
  "document": "8b03a82761fae0ee6cd5a23700361e74",
  "progress": "/body/DocFragment[15]/body/div[65]/text()[1].41",
  "percentage": 0.2082,
  "device": "boox",
  "device_id": "197E7C6B3FD54A749C87DE9C1B05A3CE",
  "metadata": {
    "filename": "the_great_gatsby.epub",
    "title": "The Great Gatsby",
    "authors": "F. Scott Fitzgerald"
  }
}
```

#### Response

| Status | Meaning |
|--------|---------|
| `200 OK` | Progress stored (or skipped because stored percentage was higher) |
| `401 Unauthorized` | Invalid credentials |

```json
{
  "document": "8b03a82761fae0ee6cd5a23700361e74",
  "progress": "/body/DocFragment[15]/body/div[65]/text()[1].41",
  "percentage": 0.2082,
  "device": "boox",
  "device_id": "197E7C6B3FD54A749C87DE9C1B05A3CE",
  "timestamp": 1703123456
}
```

---

### GET /syncs/progress/:document

Retrieve the stored reading position for a document. KOReader calls this on book open to restore the last-known position.

#### Request

Authentication headers required.

| Parameter | Location | Description |
|-----------|----------|-------------|
| `document` | path | MD5 hash of the book file |

#### Response

| Status | Meaning |
|--------|---------|
| `200 OK` | Progress record returned |
| `401 Unauthorized` | Invalid credentials |
| `404 Not Found` | No progress stored for this document |

```json
{
  "document": "8b03a82761fae0ee6cd5a23700361e74",
  "progress": "/body/DocFragment[15]/body/div[65]/text()[1].41",
  "percentage": 0.2082,
  "device": "boox",
  "device_id": "197E7C6B3FD54A749C87DE9C1B05A3CE",
  "timestamp": 1703123456
}
```

---

### GET /healthcheck

Liveness check. Returns immediately with no side effects.

#### Request

No authentication required. No request body.

#### Response

| Status | Meaning |
|--------|---------|
| `200 OK` | Server is running |

```json
{
  "state": "OK"
}
```

---

### Website Endpoints

The following endpoints are earmark extensions — they are not part of the KOSync spec and will not be called by KOReader. They exist to support the earmark web UI.

#### GET /syncs/progress

List all historical reading progress entries for a specific document. Returns all sync records in reverse chronological order (most recent first).

##### Request

Authentication headers required. No request body.

Required query parameters:

| Parameter | Type | Description |
|-----------|------|-------------|
| `document` | string | MD5 hash of the book file |

Optional query parameters:

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `page` | integer | `1` | Page number (1-based) |
| `per_page` | integer | `50` | Results per page (max 100) |

##### Response

| Status | Meaning |
|--------|---------|
| `200 OK` | List returned (may be empty) |
| `401 Unauthorized` | Invalid credentials |

```json
{
  "data": [
    {
      "document": "8b03a82761fae0ee6cd5a23700361e74",
      "progress": "/body/DocFragment[15]/body/div[65]/text()[1].41",
      "percentage": 0.2082,
      "device": "boox",
      "device_id": "197E7C6B3FD54A749C87DE9C1B05A3CE",
      "filename": "the_great_gatsby.epub",
      "title": "The Great Gatsby",
      "authors": "F. Scott Fitzgerald",
      "timestamp": 1703123456
    }
  ],
  "total": 5,
  "page": 1,
  "per_page": 50
}
```

---

#### DELETE /syncs/progress/:document

Delete the reading progress record for a specific document belonging to the authenticated user.

##### Request

Authentication headers required. No request body.

| Parameter | Location | Description |
|-----------|----------|-------------|
| `document` | path | MD5 hash of the book file |

##### Response

| Status | Meaning |
|--------|---------|
| `200 OK` | Record deleted |
| `401 Unauthorized` | Invalid credentials |
| `404 Not Found` | No progress record found for this document |

```json
{
  "deleted": "8b03a82761fae0ee6cd5a23700361e74"
}
```

---

## Data Model

Data is persisted in SQLite via SQLAlchemy. There are two tables.

### `users`

Stores registered accounts. No changes needed from the initial model.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, autoincrement | Internal row ID |
| `username` | VARCHAR(255) | UNIQUE, NOT NULL, indexed | KOSync username |
| `password_hash` | VARCHAR(255) | NOT NULL | MD5 hash of the password — KOReader clients hash client-side before sending, so this value is stored as received |
| `created_at` | DATETIME | NOT NULL, server default | Account creation timestamp |

---

### `reading_progress`

Append-only log of reading positions. Each `PUT /syncs/progress` call inserts a new row — existing rows are never modified. The row with `is_latest = true` for a given `(kosync_user_id, document)` pair is the current position. Records can only be deleted, never updated.

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `id` | INTEGER | PK, autoincrement | Internal row ID |
| `kosync_user_id` | INTEGER | FK → kosync_users.id, NOT NULL, indexed | Owning KOSync user |
| `document` | VARCHAR(500) | NOT NULL, indexed | MD5 hash of the book file |
| `progress` | VARCHAR(1000) | NOT NULL | XPath position string from KOReader (e.g. `/body/DocFragment[15]/body/div[65]/text()[1].41`) |
| `percentage` | FLOAT | NOT NULL | Reading fraction 0.0–1.0 |
| `device` | VARCHAR(255) | NOT NULL | Device name |
| `device_id` | VARCHAR(255) | NOT NULL | Unique device identifier |
| `filename` | VARCHAR(500) | nullable | Original book filename, populated when KOReader sends metadata |
| `title` | VARCHAR(500) | nullable | Book title, populated when KOReader sends metadata |
| `authors` | VARCHAR(500) | nullable | Author name(s), populated when KOReader sends metadata |
| `is_latest` | BOOLEAN | NOT NULL, default true | True on the most recently inserted row for this `(kosync_user_id, document)` pair; false on all prior rows |
| `updated_at` | DATETIME | NOT NULL, server default | Insert timestamp; returned as `timestamp` in API responses |

#### Changes required from the current model (`earmark/models.py`)

The initial `ReadingProgress` model does not match the KOSync API. The following changes are needed before implementation:

| Column | Current state | Required state |
|--------|---------------|----------------|
| `progress` | `Float` | `String(1000)` — XPath string, not a number |
| `percentage` | missing | `Float`, NOT NULL — the 0–1 reading fraction |
| `device` | missing | `String(255)`, NOT NULL |
| `device_id` | missing | `String(255)`, NOT NULL |
| `filename` | missing | `String(500)`, nullable |
| `title` | missing | `String(500)`, nullable |
| `authors` | missing | `String(500)`, nullable |
