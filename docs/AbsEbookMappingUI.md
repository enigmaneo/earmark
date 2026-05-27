# ABS–Ebook Mapping UI

This document covers the manual mapping feature: letting a logged-in earmark user pair an Audiobookshelf (ABS) audiobook with a local ebook file. The resulting link is stored in the database and used to display unified listening + reading progress on the landing page dashboard.

The alignment pipeline (forced audio↔text sync maps) is a separate concern covered in [`AudioBookEbookMapping.md`](AudioBookEbookMapping.md).

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `EBOOK_LOCAL_ROOT` | `"."` | Filesystem path scanned for ebook files. Defaults to the project root for development. Set to your actual ebooks folder in production. |

Change in `earmark/config.py`:
```python
ebook_local_root: str = "."   # was ""
```

Add to `.env`:
```
EBOOK_LOCAL_ROOT=.
```

---

## Data Model

### Table: `abs_ebook_mappings`

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `user_id` | INTEGER FK → `users.id` INDEX | Owner — mappings are per-user |
| `abs_item_id` | VARCHAR(255) INDEX | ABS item ID (e.g. `li_abc123`) |
| `abs_title` | VARCHAR(500) | Cached from ABS API at create time |
| `abs_author` | VARCHAR(500) nullable | Cached from ABS API at create time |
| `ebook_source` | VARCHAR(20) | `"local"` or `"calibre"`; server default `"local"` |
| `ebook_path` | VARCHAR(1000) nullable | For `local`: path relative to `ebook_local_root`. Null for `calibre`. |
| `ebook_filename` | VARCHAR(500) nullable | Basename of the local ebook file (for display). Null for `calibre`. |
| `ebook_source_ref` | VARCHAR(1000) nullable | For `calibre`: OPDS download href. Null for `local`. |
| `kosync_document` | VARCHAR(64) nullable INDEX | MD5 hex digest of the local ebook file content; null for `calibre` mappings |
| `created_at` | DATETIME | Server default |

### Table: `ebook_metadata_cache`

Stores extracted metadata for each ebook file so titles are not re-read on every request. Change detection uses the file's modification time and size — if either changes the cache entry is refreshed.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER PK | |
| `path` | VARCHAR(1000) UNIQUE INDEX | Path relative to `ebook_local_root` |
| `title` | VARCHAR(500) nullable | Extracted from ebook metadata |
| `author` | VARCHAR(500) nullable | Extracted from ebook metadata |
| `file_mtime` | FLOAT | `os.path.getmtime` at last cache write |
| `file_size` | INTEGER | `os.path.getsize` at last cache write |
| `updated_at` | DATETIME | Server default + onupdate |

```python
class EbookMetadataCache(Base):
    __tablename__ = "ebook_metadata_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(1000), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    author: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_mtime: Mapped[float] = mapped_column(Float)
    file_size: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
```

**User scoping:** `user_id` is a FK to `users.id`. All API endpoints filter by the authenticated user — a user can only see and manage their own mappings. This follows the same pattern as `KosyncUser.user_id`.

**Uniqueness:** enforced at the application layer (HTTP 409). For `local` mappings the check is `(user_id, abs_item_id, ebook_source, ebook_path)`; for `calibre` mappings it is `(user_id, abs_item_id, ebook_source, ebook_source_ref)`.

**Back-reference on `User`:**
```python
ebook_mappings: Mapped[list["AbsEbookMapping"]] = relationship(back_populates="user")
```

### SQLAlchemy Model

```python
class AbsEbookMapping(Base):
    __tablename__ = "abs_ebook_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    abs_item_id: Mapped[str] = mapped_column(String(255), index=True)
    abs_title: Mapped[str] = mapped_column(String(500))
    abs_author: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ebook_source: Mapped[str] = mapped_column(String(20), server_default="local")
    ebook_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    ebook_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ebook_source_ref: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    kosync_document: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="ebook_mappings")
```

`init_db()` calls `Base.metadata.create_all`, so the table is created automatically on first startup — no migration tooling needed. For existing SQLite databases predating the source-selection feature, `init_db()` also runs a small list of idempotent `ALTER TABLE` statements (see `src/earmark/database.py`) to add `ebook_source` and `ebook_source_ref`.

---

## KOSync Document ID

KOReader identifies books by the MD5 hex digest of the full file content. This is the same value stored in `reading_progress.document`. When a mapping is created, earmark computes it server-side:

```python
import hashlib, asyncio
content = await asyncio.to_thread(full_path.read_bytes)
kosync_document = hashlib.md5(content).hexdigest()
```

If the file cannot be read at create time, `kosync_document` is stored as `null` and the mapping is still saved. This allows the mapping to exist even if the file path is temporarily unavailable.

---

## Backend API

New router at `earmark/routers/mappings.py`, prefix `/web`, tag `mappings`. All endpoints require JWT Bearer auth via `get_current_earmark_user`.

Register in `earmark/main.py`:
```python
from earmark.routers import ..., mappings
app.include_router(mappings.router)
```

---

### `GET /web/abs-items`

Returns a list of ABS audiobooks for the create-mapping dropdown.

**Strategy (tried in order):**
1. If `audiobookshelf_url` and `audiobookshelf_api_key` are configured, call the ABS API:
   - `GET /api/libraries` → `{ "libraries": [{ "id": "...", ... }] }`
   - For each library: `GET /api/libraries/{id}/items?limit=0` → `{ "results": [...] }`
   - Filter to `mediaType == "book"` items only
   - Extract `item.id`, `item.media.metadata.title`, `item.media.metadata.authorName`
2. Fall back to the local `abs_library_items` table (populated by alignment jobs) if ABS is not configured or the live call fails.

**New methods on `AudiobookshelfClient`** (`earmark/services/audiobookshelf.py`):
```python
async def list_libraries(self) -> list[dict]:
    response = await self._client.get("/api/libraries")
    response.raise_for_status()
    return response.json().get("libraries", [])

async def list_library_items(self, library_id: str) -> list[dict]:
    response = await self._client.get(
        f"/api/libraries/{library_id}/items", params={"limit": "0"}
    )
    response.raise_for_status()
    return response.json().get("results", [])
```

**Response schema: `AbsItemSummary`**
```json
[
  { "abs_item_id": "li_abc123", "title": "The Name of the Wind", "author": "Patrick Rothfuss" }
]
```

---

### `GET /web/ebook-files`

Recursively scans `ebook_local_root` for ebook files and returns each file with its extracted title and author. Results are cached in `ebook_metadata_cache` so metadata is only read from disk when a file is new or has changed.

Supported extensions: `.epub`, `.pdf`, `.mobi`, `.azw3`

Returns `[]` if `ebook_local_root` is empty or the directory does not exist.

**Metadata extraction library:** `ebooklib` for EPUB; `pypdf` for PDF. Both are well-known packages that should be added to project dependencies. MOBI/AZW3 do not have a widely supported pure-Python metadata library — fall back to filename for those formats.

**Cache logic (runs in `asyncio.to_thread`):**

```
for each file found on disk:
    stat = os.stat(file)
    cached = lookup ebook_metadata_cache by path
    if cached and cached.file_mtime == stat.st_mtime and cached.file_size == stat.st_size:
        use cached.title, cached.author
    else:
        extract title/author from file content
        upsert ebook_metadata_cache row with new mtime/size/title/author

delete ebook_metadata_cache rows whose path is no longer on disk
```

The upsert and stale-entry cleanup happen in a single DB session after the scan completes.

**Title display fallback:** if no title is found in the file metadata, display the filename instead.

**Response schema: `EbookFileSummary`**
```json
[
  {
    "path": "fantasy/name-of-the-wind.epub",
    "filename": "name-of-the-wind.epub",
    "title": "The Name of the Wind",
    "author": "Patrick Rothfuss"
  }
]
```

`path` is always relative to `ebook_local_root`. `title` and `author` are `null` if extraction failed.

---

### `GET /web/calibre-ebooks`

Searches the configured Calibre Web OPDS server for ebooks matching an ABS audiobook. Used by the mapping UI when the user selects the *Calibre Web* source.

**Query parameters:**
- `abs_item_id` (required) — the ABS item to look up

**Resolution:** the backend reads the audiobook's title and author (via the ABS API if configured, else from the `abs_library_items` table) and calls `CalibreOpdsSource.search(title, author)` (`src/earmark/services/ebook_sources/calibre.py`). See [CalibreWebIntegration.md](CalibreWebIntegration.md) for the OPDS protocol details.

**Status codes:**
- `200` — list of `EbookCandidate` objects (may be empty if there is no match).
- `404` — unknown `abs_item_id`.
- `503` — `CWA_URL` is not configured.
- `502` — the OPDS server is unreachable.

**Response schema: `EbookCandidate`**
```json
[
  {
    "ref": "/opds/download/42/name-of-the-wind.epub",
    "title": "The Name of the Wind",
    "author": "Patrick Rothfuss",
    "format": "epub"
  }
]
```

`ref` is passed back to `POST /web/mappings` as `ebook_source_ref` when creating a `calibre` mapping.

---

### `GET /web/mappings`

Returns all mappings owned by the authenticated user, ordered newest first.

**Response:** array of `MappingRead`.

---

### `POST /web/mappings`

Creates a new mapping. The shape of the body depends on `ebook_source`.

**Local source:**
```json
{
  "abs_item_id": "li_abc123",
  "abs_title": "The Name of the Wind",
  "abs_author": "Patrick Rothfuss",
  "ebook_source": "local",
  "ebook_path": "fantasy/name-of-the-wind.epub"
}
```

**Calibre Web source:**
```json
{
  "abs_item_id": "li_abc123",
  "abs_title": "The Name of the Wind",
  "abs_author": "Patrick Rothfuss",
  "ebook_source": "calibre",
  "ebook_source_ref": "/opds/download/42/name-of-the-wind.epub"
}
```

`ebook_source_ref` is the OPDS download href returned by `GET /web/calibre-ebooks`.

**Behavior:**
1. Validate per-source fields: `local` requires `ebook_path`; `calibre` requires `ebook_source_ref`. 422 if missing.
2. Check for an existing mapping with the same `(user_id, abs_item_id, ebook_source, …)` tuple → 409.
3. For `local`: resolve `ebook_local_root / ebook_path`, compute the kosync MD5, store as `kosync_document`. 500 if the file cannot be read.
4. For `calibre`: `kosync_document` is left null (the file is fetched at alignment time).
5. Persist and return the created mapping.

**Response:** `201 Created` with the new `MappingRead`.

---

### `DELETE /web/mappings/{id}`

Deletes a mapping. The query is scoped to `(id, user_id)` so a user cannot delete another user's mapping.

Returns 404 if the mapping does not exist or is not owned by the current user.

**Response:** `{ "deleted": 1 }`

---

## Pydantic Schemas

Add to `earmark/schemas.py`:

```python
class AbsItemSummary(BaseModel):
    abs_item_id: str
    title: str
    author: str | None = None


class EbookFileSummary(BaseModel):
    path: str           # relative to ebook_local_root
    filename: str
    title: str | None = None
    author: str | None = None


class EbookCandidate(BaseModel):
    ref: str           # OPDS download href (calibre) or relative path (local search results)
    title: str
    author: str | None = None
    format: str = "epub"


class MappingCreate(BaseModel):
    abs_item_id: str
    abs_title: str
    abs_author: str | None = None
    ebook_source: str = "local"          # "local" | "calibre"
    ebook_path: str | None = None        # required when ebook_source == "local"
    ebook_source_ref: str | None = None  # required when ebook_source == "calibre"


class MappingRead(BaseModel):
    id: int
    user_id: int
    abs_item_id: str
    abs_title: str
    abs_author: str | None
    ebook_source: str
    ebook_path: str | None
    ebook_filename: str | None
    ebook_source_ref: str | None
    kosync_document: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
```

---

## Frontend — `/mappings` Route

New SvelteKit route at `frontend/src/routes/mappings/`.

### TypeScript interfaces (add to `frontend/src/lib/api.ts`)

```typescript
export interface AbsItemSummary {
    abs_item_id: string;
    title: string;
    author: string | null;
}

export interface EbookFileSummary {
    path: string;
    filename: string;
    title: string | null;
    author: string | null;
}

export type EbookSource = 'local' | 'calibre';

export interface EbookCandidate {
    ref: string;
    title: string;
    author: string | null;
    format: string;
}

export interface MappingRead {
    id: number;
    user_id: number;
    abs_item_id: string;
    abs_title: string;
    abs_author: string | null;
    ebook_source: EbookSource;
    ebook_path: string | null;
    ebook_filename: string | null;
    ebook_source_ref: string | null;
    kosync_document: string | null;
    created_at: string;
}
```

### `+page.server.ts`

- Read `earmark_session` cookie; redirect to `/login` if missing.
- Load `absItems`, `ebookFiles`, and `mappings` in parallel via `Promise.all`.
- Form actions:
  - `createMapping` — POST JSON to `/web/mappings`. Reads `ebook_source` from the form and forwards `ebook_path` (local) or `ebook_source_ref` (calibre).
  - `deleteMapping` — DELETE to `/web/mappings/{id}`
  - `syncMapping` — POST to `/web/mappings/{id}/sync`

Calibre candidates are fetched client-side via `GET /mappings/calibre?abs_item_id=…`, a SvelteKit `+server.ts` that proxies to the backend with the session token attached.

### `+page.svelte` — UI Layout

```
AppBar: earmark | [Mappings]  user@email  Sign out
─────────────────────────────────────────────────────────────────
┌───────────────────────────────────────────────────────────────┐
│ Add Mapping                                                   │
│                                                               │
│  ABS Audiobook                                                │
│  ┌──────────────────────────┐                                 │
│  │ Choose audiobook…      ▾ │                                 │
│  └──────────────────────────┘                                 │
│                                                               │
│  Ebook source                                                 │
│   (•) Local files    ( ) Calibre Web                          │
│                                                               │
│  Ebook  ← shows Local picker OR Calibre candidates            │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ Choose ebook…                                          ▾ │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                    [ Add ]    │
└───────────────────────────────────────────────────────────────┘

┌────────────────┬─────────────────┬───────────────┬────────────┬──────────┬────────┐
│ Audiobook      │ Author          │ Ebook File    │ KOSync Hash│ Created  │        │
├────────────────┼─────────────────┼───────────────┼────────────┼──────────┼────────┤
│ Name of Wind   │ Patrick Rothfuss│ notw.epub     │ 8b03a827…  │ 5/14/26  │ Remove │
│ Mistborn       │ Brandon Sanderson│ mistborn.epub │ —          │ 5/13/26  │ Remove │
└────────────────┴─────────────────┴───────────────┴────────────┴──────────┴────────┘
```

**Behaviour:**
- Selecting an ABS item reactively populates hidden form fields (`abs_title`, `abs_author`).
- The **Ebook source** radio group toggles between `local` and `calibre` (defaults to `local`).
- **Local mode**: the ebook dropdown is populated from `/web/ebook-files`. Option label is `"{title}" — {author}` when metadata is available, otherwise the filename. Empty list shows a disabled "No ebooks found — check EBOOK_LOCAL_ROOT".
- **Calibre mode**: when an ABS audiobook is selected, the page calls `GET /mappings/calibre?abs_item_id=…`. While the request is in flight the dropdown shows "Searching Calibre Web…". On success the matching candidates are listed; if there is exactly one candidate it is pre-selected. Empty result shows "No match on Calibre Web"; transport errors show the backend error message.
- "Add" button is disabled until the audiobook **and** an ebook (local file or Calibre candidate) are selected, and while Calibre search is loading.
- On successful create, the new row is appended to the table via `use:enhance` without a full page reload.
- "Remove" deletes the row inline (no confirmation dialog — the mapping can always be recreated).
- Empty ABS dropdown: single disabled option "No audiobooks found".
- Duplicate mapping attempt: inline error message above the form.

### Navigation

Add a "Mappings" link to the AppBar trail in `frontend/src/routes/+layout.svelte`:

```svelte
<a href="/mappings" class="btn btn-sm variant-ghost">Mappings</a>
```

---

## Bruno Test Requests

Create `testing/bruno/mappings/` with 5 `.bru` files. All use `auth: bearer` with `token: {{jwt_token}}`.

| File | Method | URL |
|------|--------|-----|
| `list-abs-items.bru` | GET | `{{base_url}}/web/abs-items` |
| `list-ebook-files.bru` | GET | `{{base_url}}/web/ebook-files` |
| `list-mappings.bru` | GET | `{{base_url}}/web/mappings` |
| `create-mapping.bru` | POST (JSON body) | `{{base_url}}/web/mappings` |
| `delete-mapping.bru` | DELETE | `{{base_url}}/web/mappings/:id` |

`create-mapping.bru` body:
```json
{
  "abs_item_id": "{{abs_item_id}}",
  "abs_title": "Test Book",
  "abs_author": "Test Author",
  "ebook_path": "test.epub"
}
```

`delete-mapping.bru` path param: `id: 1`

---

## Files to Create / Modify

| Action | Path |
|--------|------|
| Modify | `earmark/config.py` — change `ebook_local_root` default to `"."` |
| Modify | `.env` — add `EBOOK_LOCAL_ROOT=.` |
| Modify | `earmark/models.py` — add `AbsEbookMapping`, `EbookMetadataCache`; add `ebook_mappings` to `User` |
| Modify | `earmark/schemas.py` — add `AbsItemSummary`, `EbookFileSummary` (with `title`/`author`), `MappingCreate`, `MappingRead` |
| Modify | `pyproject.toml` — add `ebooklib` and `pypdf` dependencies |
| Modify | `earmark/services/audiobookshelf.py` — add `list_libraries`, `list_library_items` |
| Create | `earmark/routers/mappings.py` |
| Modify | `earmark/main.py` — import and register `mappings.router` |
| Modify | `frontend/src/lib/api.ts` — add `AbsItemSummary`, `EbookFileSummary`, `MappingRead` interfaces |
| Create | `frontend/src/routes/mappings/+page.server.ts` |
| Create | `frontend/src/routes/mappings/+page.svelte` |
| Modify | `frontend/src/routes/+layout.svelte` — add Mappings nav link |
| Create | `testing/bruno/mappings/list-abs-items.bru` |
| Create | `testing/bruno/mappings/list-ebook-files.bru` |
| Create | `testing/bruno/mappings/list-mappings.bru` |
| Create | `testing/bruno/mappings/create-mapping.bru` |
| Create | `testing/bruno/mappings/delete-mapping.bru` |

---

## Verification

1. Set `EBOOK_LOCAL_ROOT=.` in `.env` and place a `.epub` file in the project root.
2. `uv run fastapi dev earmark/main.py` — confirm both new tables (`abs_ebook_mappings`, `ebook_metadata_cache`) are created and no startup errors occur.
3. Bruno: `list-abs-items` → expect array of audiobooks from ABS (or from local DB if ABS not reachable).
4. Bruno: `list-ebook-files` → expect the `.epub` with its extracted `title` and `author` (not just the filename). Confirm the `ebook_metadata_cache` table now has a row.
5. Bruno: `list-ebook-files` again → second call should be fast (cache hit); confirm `updated_at` on the cache row has not changed.
6. Touch the `.epub` file (`touch test.epub`) and call `list-ebook-files` again → cache should refresh (new `updated_at`).
7. Bruno: `create-mapping` → expect `201` with a non-null `kosync_document`.
8. Bruno: `list-mappings` → expect the new mapping in the response.
9. Bruno: `delete-mapping` with the returned `id` → expect `{"deleted": N}`.
10. Browser: navigate to `/mappings` — verify ebook dropdown shows titles, not filenames.
11. `uv run pytest` — confirm no regressions.
