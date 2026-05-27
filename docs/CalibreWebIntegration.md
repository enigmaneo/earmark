# Calibre Web (OPDS) Integration

Status: Implemented.

Related: [AudioBookEbookMapping.md](AudioBookEbookMapping.md), [AbsEbookMappingUI.md](AbsEbookMappingUI.md), [Sync.md](Sync.md).

## 1. Goal & Motivation

`earmark` currently fetches the ebook side of an audiobook-ebook mapping from one of three sources, selected globally via the `EBOOK_SOURCE` env var:

- `abs` — pulled from the Audiobookshelf item that owns the audiobook.
- `cwa` — fetched from a Calibre Web instance via OPDS, matched by title/author after the mapping is created.
- `local` — scanned from `EBOOK_LOCAL_ROOT` on disk.

The selection is opaque to the user: switching sources requires editing `.env` and restarting, and the user only learns whether a match was found when an alignment job fails. We want the user to pick the source **per mapping** in the UI, with two first-class options:

- **Local** — pick a file from the configured local ebook root (today's flow).
- **Calibre Web** — match the audiobook against the configured Calibre Web OPDS server and pick a candidate.

## 2. Non-Goals (v1)

- Browsing the full OPDS catalog (search is driven by the audiobook's title/author).
- Per-user Calibre Web credentials.
- New ebook formats beyond what alignment already supports (EPUB-first).
- Backfilling source-tracking onto historical `AbsEbookMapping` rows beyond a default.

## 3. User Flow

On the mapping page (`src/frontend/src/routes/mappings/+page.svelte`):

1. User selects an ABS audiobook.
2. User selects a **source**: *Local* or *Calibre Web*.
3. Depending on source:
   - **Local** — existing dropdown populated from `GET /web/ebook-files`; user picks a file.
   - **Calibre Web** — frontend calls `GET /web/calibre-ebooks?abs_item_id=…`; backend queries the OPDS server with normalized title/author and returns ranked candidates. User confirms the match (or picks among multiple).
4. User submits. The mapping persists which source was used so the alignment worker fetches from the same place.

If Calibre Web returns no match, the UI shows "No match on Calibre Web" with the option to retry or switch to Local. If the OPDS server is unreachable, the UI surfaces the error and disables submission.

## 4. Backend Changes

### Config — `src/earmark/config.py`

- Remove `ebook_source` (or deprecate for one release: emit a startup warning if `EBOOK_SOURCE` is set in the environment, then ignore it).
- Keep `cwa_url`, `cwa_username`, `cwa_password`, `ebook_local_root`. No renames — existing deployments keep working.

### Data model — `src/earmark/models.py`, `AbsEbookMapping`

Add two columns:

- `ebook_source: str` — `"local"` | `"calibre"`. Defaults to `"local"`.
- `ebook_source_ref: str | None` — for `calibre`, the OPDS download href (or entry id); unused for `local` (the path lives in the existing `ebook_path`).

Schema upgrade: idempotent `ALTER TABLE` statements in `src/earmark/database.py` add the new columns at startup (the project does not use Alembic; `Base.metadata.create_all` plus a small stopgap list covers both fresh and existing SQLite DBs).

### Service abstraction — `src/earmark/services/ebook_sources/`

Extract the source-specific logic currently inlined in `alignment.py:784-936` into a small package:

```python
class EbookCandidate(BaseModel):
    ref: str         # download href (calibre) or filesystem path (local)
    title: str
    author: str
    format: str      # "epub", "pdf", ...

class EbookSource(Protocol):
    async def search(self, title: str, author: str) -> list[EbookCandidate]: ...
    async def fetch(self, ref: str, dest: Path) -> None: ...
```

- `LocalEbookSource` — wraps the rglob/normalize logic from `alignment.py:895-936`.
- `CalibreOpdsSource` — wraps the OPDS search + download logic from `alignment.py:825-893`, exposing `search()` so the frontend can preview candidates before commit.

`alignment.py:_fetch_ebook` becomes a thin dispatcher on the mapping's `ebook_source` column. The ABS-attached download path (`_download_ebook_from_abs`) stays as-is for now; it is implicit when ABS itself provides the file and is unaffected by the user-facing source toggle.

### Routes — `src/earmark/routers/mappings.py`

- **New** `GET /web/calibre-ebooks?abs_item_id=…` — looks up the ABS item, normalizes title/author, calls `CalibreOpdsSource.search()`, returns `list[EbookCandidate]`. Returns `502` if the OPDS server is unreachable.
- **Unchanged** `GET /web/ebook-files` — keeps powering the Local dropdown.
- **Updated** `POST /web/mappings` — accepts `ebook_source` (`"local"` | `"calibre"`) and `ebook_source_ref` (required when source is `calibre`). Validates that exactly one of `ebook_path` (local) or `ebook_source_ref` (calibre) is provided per the chosen source.

## 5. Frontend Changes

### API types — `src/frontend/src/lib/api.ts`

```ts
export interface EbookCandidate {
  ref: string;
  title: string;
  author: string;
  format: string;
}

export interface MappingCreate {
  abs_item_id: string;
  ebook_source: 'local' | 'calibre';
  ebook_path?: string;          // local
  ebook_source_ref?: string;    // calibre
}
```

### Mapping page — `src/frontend/src/routes/mappings/+page.svelte`

- Add a source toggle (radio group) between the audiobook selector and the ebook selector.
- When `local`: keep the existing dropdown bound to `/web/ebook-files`.
- When `calibre`: on audiobook change, call `/web/calibre-ebooks?abs_item_id=…`; render the returned candidates (or a "no match" state); selection writes `ebook_source_ref` to the submission payload.
- Disable the submit button while the OPDS search is in flight or while it has errored.

## 6. Migration & Backwards Compatibility

- Existing `AbsEbookMapping` rows are backfilled with `ebook_source = "local"` via an idempotent `ALTER TABLE ... DEFAULT 'local'` issued at startup in `src/earmark/database.py` (no Alembic). This is the safe default — re-running alignment on them resolves through `LocalEbookSource`.
- `EBOOK_SOURCE` env var is no longer read. If it is set, the app logs a startup warning pointing to this document.
- `CWA_URL` / `CWA_USERNAME` / `CWA_PASSWORD` keep their names to avoid breaking deployments. (A future rename to `OPDS_*` can ship with a deprecation cycle.)

## 7. Matching & Error Handling

### OPDS query (in `_build_search_query`)

Calibre Web's `/opds/search/{terms}` does **case-insensitive substring matching against the stored title** — it does *not* normalize away apostrophes or numeric prefixes. Sending the full normalized ABS title (e.g. `"09 winters heart"`) matches nothing because Calibre stores `"Winter's Heart"` literally. Earmark therefore builds the query from the **raw** title:

1. Strip a leading numeric/series prefix (`^(?:book\s+)?\d+[\W_]+`), so `"09 - Winter's Heart"` becomes `"Winter's Heart"`.
2. Tokenize on whitespace, drop punctuation, and split each token on the first apostrophe (`"Winter's"` → `"Winter"`).
3. Drop stopwords and tokens shorter than 3 characters.
4. Send the first remaining token, lowercased.

For `"09 - Winter's Heart"` the query becomes `"winter"`; for `"A Crown of Swords"` it becomes `"crown"`. The query is intentionally broad — the post-filter below narrows the result set.

### OPDS post-filter (in `_parse_opds_feed`)

Calibre Web returns a broad set of entries; earmark narrows them down with a permissive, tiered matcher rather than strict equality so that real titles with multi-author / series-prefix / non-EPUB variants still surface.

**Author check (`_author_matches`).** Iterate every `<author><name>` in the entry. Accept the entry when *any* of the following hold:

- The ABS author is empty.
- The OPDS entry has no author info.
- Any OPDS author normalizes equal to the ABS author.
- The ABS author's surname (last token) appears as a token in any OPDS author, or vice versa.

This is what makes "Towers of Midnight" (OPDS authors `Robert Jordan`, `Brandon Sanderson`) match an ABS audiobook listed under either author alone.

**Title check (`_title_match_tier`).** Three tiers; lower tier is better:

1. Exact normalized-title equality.
2. ABS title appears inside the OPDS title (with leading series tags like `Wheel of Time [07]:` stripped before comparison).
3. Every significant token of the ABS title (length ≥ 3, excluding the stopword set `{the, a, an, of, and, or, to}`) appears as a token in the OPDS title.

Candidates are sorted by `(tier, format_priority)` — exact title matches first, EPUB before AZW3 before MOBI before PDF.

**Format.** Every `<link rel="http://opds-spec.org/acquisition">` becomes a candidate. The `format` field is derived from the MIME (`application/epub+zip` → `epub`, `application/x-mobipocket-ebook` → `mobi`, `application/vnd.amazon.ebook` → `azw3`, `application/pdf` → `pdf`). Non-EPUB candidates are surfaced so the user sees that the book exists on Calibre Web; the UI labels them `(MOBI)` / `(PDF)` etc. **Alignment currently requires EPUB** — selecting a non-EPUB candidate will fail at the parse stage. Converting other formats is a follow-up.

### Error table

| Scenario | Behavior |
| --- | --- |
| OPDS returns zero candidates after filtering | Endpoint returns `[]`; UI shows "No match on Calibre Web". |
| OPDS unreachable / 5xx | Endpoint returns `502`; UI surfaces the error and disables submission. |
| OPDS returns multiple candidates | All returned, sorted; user picks one. |
| Non-EPUB candidate selected | Mapping is created; alignment job will fail at `parsing_epub` with a clear `sync_error`. |
| Local file missing at alignment time | Existing behavior: alignment job fails with a clear error in `sync_error`. |

## 8. Testing

- Unit tests for `LocalEbookSource.search` covering the existing priority rules (exact title match, parent-directory author match, fuzzy fallback).
- Unit tests for `CalibreOpdsSource.search` against a fixture OPDS XML feed using `httpx.MockTransport` (or `respx`).
- Integration test for `POST /web/mappings` with each source variant, asserting the persisted columns and that the alignment job is enqueued.
- Manual end-to-end: configure a real Calibre Web instance via `.env`, create a mapping through the UI with the Calibre source, confirm the alignment job downloads and completes.

## 9. Open Questions

- **Per-user OPDS credentials** — not in v1. Worth revisiting once we have a Settings UI; the data model can accommodate by moving `cwa_*` into a per-user table without touching this flow.
- **Mapping uniqueness across sources** — recommend keeping the current `(user_id, abs_item_id)` uniqueness constraint. Allowing the same audiobook to be mapped against multiple sources adds UX ambiguity (which one does sync use?) without a clear use case.

## 10. File-Level Touch List

- `src/earmark/config.py` — remove `ebook_source`, add deprecation warning.
- `src/earmark/models.py` — `AbsEbookMapping`: add `ebook_source`, `ebook_source_ref`.
- `src/earmark/services/ebook_sources/__init__.py` — new package: protocol + implementations.
- `src/earmark/services/alignment.py` — replace inline source dispatch with the abstraction.
- `src/earmark/routers/mappings.py` — add `GET /web/calibre-ebooks`, extend `POST /web/mappings`.
- `src/earmark/database.py` — idempotent `ALTER TABLE` for the new columns at startup.
- `src/frontend/src/lib/api.ts` — new types.
- `src/frontend/src/routes/mappings/+page.svelte` — source toggle and Calibre candidate selector.
