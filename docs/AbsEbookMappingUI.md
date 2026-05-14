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
| `ebook_path` | VARCHAR(1000) | Path relative to `ebook_local_root` |
| `ebook_filename` | VARCHAR(500) | Basename of the ebook file (for display) |
| `kosync_document` | VARCHAR(64) nullable INDEX | MD5 hex digest of the ebook file content |
| `created_at` | DATETIME | Server default |

**User scoping:** `user_id` is a FK to `users.id`. All API endpoints filter by the authenticated user — a user can only see and manage their own mappings. This follows the same pattern as `KosyncUser.user_id`.

**Uniqueness:** `(user_id, abs_item_id, ebook_path)` is enforced at the application layer (HTTP 409) rather than as a DB constraint, to avoid migration complexity with SQLite.

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
    ebook_path: Mapped[str] = mapped_column(String(1000))
    ebook_filename: Mapped[str] = mapped_column(String(500))
    kosync_document: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="ebook_mappings")
```

`init_db()` calls `Base.metadata.create_all`, so the table is created automatically on first startup — no migration tooling needed.

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

Recursively scans `ebook_local_root` for ebook files. Uses `asyncio.to_thread` to avoid blocking the event loop.

Supported extensions: `.epub`, `.pdf`, `.mobi`, `.azw3`

Returns `[]` if `ebook_local_root` is empty or the directory does not exist.

**Response schema: `EbookFileSummary`**
```json
[
  { "path": "fantasy/name-of-the-wind.epub", "filename": "name-of-the-wind.epub" }
]
```

`path` is always relative to `ebook_local_root`.

---

### `GET /web/mappings`

Returns all mappings owned by the authenticated user, ordered newest first.

**Response:** array of `MappingRead`.

---

### `POST /web/mappings`

Creates a new mapping.

**Request body:**
```json
{
  "abs_item_id": "li_abc123",
  "abs_title": "The Name of the Wind",
  "abs_author": "Patrick Rothfuss",
  "ebook_path": "fantasy/name-of-the-wind.epub"
}
```

**Behavior:**
1. Check for existing mapping with same `(user_id, abs_item_id, ebook_path)` → 409 if found.
2. Resolve `ebook_local_root / ebook_path`.
3. If the file exists: compute MD5, store as `kosync_document`.
4. If the file is missing: store `kosync_document = null`, continue without error.
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
    path: str       # relative to ebook_local_root
    filename: str


class MappingCreate(BaseModel):
    abs_item_id: str
    abs_title: str
    abs_author: str | None = None
    ebook_path: str


class MappingRead(BaseModel):
    id: int
    user_id: int
    abs_item_id: str
    abs_title: str
    abs_author: str | None
    ebook_path: str
    ebook_filename: str
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
}

export interface MappingRead {
    id: number;
    user_id: number;
    abs_item_id: string;
    abs_title: string;
    abs_author: string | null;
    ebook_path: string;
    ebook_filename: string;
    kosync_document: string | null;
    created_at: string;
}
```

### `+page.server.ts`

- Read `earmark_session` cookie; redirect to `/login` if missing.
- Load `absItems`, `ebookFiles`, and `mappings` in parallel via `Promise.all`.
- Two form actions:
  - `createMapping` — POST JSON to `/web/mappings`
  - `deleteMapping` — DELETE to `/web/mappings/{id}`

Follow the same pattern as the root `+page.server.ts`.

### `+page.svelte` — UI Layout

```
AppBar: earmark | [Mappings]  user@email  Sign out
─────────────────────────────────────────────────────────────────
┌───────────────────────────────────────────────────────────────┐
│ Add Mapping                                                   │
│                                                               │
│  ABS Audiobook                   Ebook File                   │
│  ┌──────────────────────────┐   ┌──────────────────────────┐  │
│  │ Choose audiobook…      ▾ │   │ Choose ebook…          ▾ │  │
│  └──────────────────────────┘   └──────────────────────────┘  │
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
- "Add" button is disabled until both dropdowns have a selection.
- On successful create, the new row is appended to the table via `use:enhance` without a full page reload.
- "Remove" deletes the row inline (no confirmation dialog — the mapping can always be recreated).
- Empty ABS dropdown: single disabled option "No audiobooks found".
- Empty ebook dropdown: single disabled option "No ebooks found — check EBOOK_LOCAL_ROOT".
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
| Modify | `earmark/models.py` — add `AbsEbookMapping`; add `ebook_mappings` to `User` |
| Modify | `earmark/schemas.py` — add `AbsItemSummary`, `EbookFileSummary`, `MappingCreate`, `MappingRead` |
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
2. `uv run fastapi dev earmark/main.py` — confirm `abs_ebook_mappings` table is created and no startup errors occur.
3. Bruno: `list-abs-items` → expect array of audiobooks from ABS (or from local DB if ABS not reachable).
4. Bruno: `list-ebook-files` → expect the `.epub` file you placed in the root.
5. Bruno: `create-mapping` → expect `201` with a non-null `kosync_document`.
6. Bruno: `list-mappings` → expect the new mapping in the response.
7. Bruno: `delete-mapping` with the returned `id` → expect `{"deleted": N}`.
8. Browser: navigate to `/mappings` and verify the full create + delete UI flow.
9. `uv run pytest` — confirm no regressions.
