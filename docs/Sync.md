# Bidirectional ABS ↔ KOSync Progress Sync

This document describes the scheduled sync job that keeps AudioBookshelf (ABS) audio progress and KOSync ebook progress in agreement. It relies on the sync map produced by the alignment pipeline (see [`docs/AudioBookEbookMapping.md`](AudioBookEbookMapping.md)) to convert positions between the two systems.

## Table of Contents

1. [Overview](#1-overview)
2. [Sync Rules](#2-sync-rules)
3. [Position Conversion](#3-position-conversion)
   - [3a. ABS → KOSync](#3a-abs--kosync)
   - [3b. KOSync → ABS](#3b-kosync--abs)
4. [ABS API Integration](#4-abs-api-integration)
5. [KOSync Write Logic](#5-kosync-write-logic)
6. [Warning and Skip Conditions](#6-warning-and-skip-conditions)
7. [Scheduler Integration](#7-scheduler-integration)
8. [Error Handling](#8-error-handling)

---

## 1. Overview

earmark runs a periodic sync job (default every 5 minutes) that compares reading progress between ABS and KOSync for every active mapping. The side with the newer timestamp wins and its position is pushed to the other side. Only forward progress is allowed — neither side is ever updated to an earlier position.

**Prerequisites for a mapping to be synced:**

- `AbsEbookMapping.kosync_document` is set (the MD5 hash linking to `ReadingProgress.document`)
- `AbsEbookMapping.alignment_job_id` points to an `AlignmentJob` with `status = "complete"` and a non-null `sync_map_path`
- The earmark `User` who owns the mapping has at least one linked `KosyncUser`

---

## 2. Sync Rules

For each eligible mapping, the sync job performs the following steps:

**Step 1 — Fetch both sides**

| Side | Field | Type | Source |
|------|-------|------|--------|
| ABS | `currentTime` | float (seconds) | `GET /api/me/progress/{abs_item_id}` |
| ABS | `lastUpdate` | int (Unix ms) | same response |
| ABS | `duration` | float (seconds) | same response |
| KOSync | `progress` | string (XPath) | latest `ReadingProgress` row for `kosync_document` |
| KOSync | `percentage` | float (0–1) | same row |
| KOSync | `updated_at` | datetime | same row |

**Step 2 — Compare timestamps**

Convert ABS `lastUpdate` (Unix ms) to a UTC datetime and compare against KOSync `updated_at`.

```
abs_ts  = datetime.fromtimestamp(lastUpdate / 1000, tz=UTC)
ko_ts   = ReadingProgress.updated_at (UTC-aware)
```

**Step 3 — Determine direction and apply forward-only guard**

| Condition | Action |
|-----------|--------|
| `abs_ts > ko_ts` | ABS is newer → attempt to update KOSync |
| `ko_ts > abs_ts` | KOSync is newer → attempt to update ABS |
| Timestamps equal | No-op |
| ABS has no progress | KOSync has no progress | No-op |
| ABS has progress, KOSync has none | Write ABS position to KOSync unconditionally |
| KOSync has progress, ABS has none | Write KOSync position to ABS unconditionally |

**Forward-only guard (applied before writing):**

- ABS → KOSync: if `new_percentage ≤ current_kosync_percentage`, log WARN and skip.
- KOSync → ABS: if `new_current_time ≤ abs_current_time`, log WARN and skip.

---

## 3. Position Conversion

The sync map (`AlignmentJob.sync_map_path`) is a JSON array of entries linking audio timestamps to EPUB XPath positions:

```json
[
  {
    "id": "para_001",
    "audio_start": 142.3,
    "audio_end": 148.7,
    "ebook_pos": "/body/DocFragment[3]/body/p[1]",
    "text_snippet": "It was the best of times, it was the worst of times,"
  }
]
```

### 3a. ABS → KOSync

**Input:** `currentTime` (float, seconds into the audiobook), `duration` (float, total seconds)

**Algorithm:**

1. Binary-search the sync map for the entry where `audio_start ≤ currentTime < audio_end`. If `currentTime` exceeds the last entry's `audio_end`, use the last entry.
2. Return:
   - `ebook_pos` — the XPath string from that entry (used as `ReadingProgress.progress`)
   - `percentage = currentTime / duration`

**Example:**

```
currentTime = 145.0, duration = 3600.0
→ matches para_001 (audio_start=142.3, audio_end=148.7)
→ ebook_pos = "/body/DocFragment[3]/body/p[1]"
→ percentage = 145.0 / 3600.0 = 0.0403
```

### 3b. KOSync → ABS

**Input:** KOSync XPath string (e.g. `/body/DocFragment[15]/body/div[65]/text()[1].41`)

KOReader uses more specific XPath than the sync map (which uses `/body/DocFragment[N]/body/tag[M]`). The conversion extracts the DocFragment index and element index from the KOReader XPath and finds the best-matching sync map entry.

**Algorithm:**

1. Parse the DocFragment index `N` from the XPath using the pattern `/body/DocFragment[(\d+)]/`.
2. Parse the element index `M` from the first element after `/body/` in the fragment body — match any tag name followed by `[\d+]` (e.g. `div[65]`, `p[12]`).
3. Collect all sync map entries whose `ebook_pos` contains `DocFragment[N]`.
4. Among those entries, parse the element index from each `ebook_pos` and find the entry with the closest element index to `M`.
5. Return `audio_start` of that entry.

If step 3 produces no entries (DocFragment not found in sync map), log WARN and return `None` to skip the update.

**Example:**

```
XPath = "/body/DocFragment[3]/body/div[2]/text()[1].41"
→ N = 3, M = 2
→ sync map entries for DocFragment[3]:
    para_001: ebook_pos="...p[1]" → element_index=1
    para_002: ebook_pos="...p[2]" → element_index=2   ← closest to M=2
    para_003: ebook_pos="...p[3]" → element_index=3
→ return para_002.audio_start = 148.7
```

**Note on DocFragment numbering:** `ebook_pos` values in the sync map use the 1-based index of each item in the EPUB spine (all items, including non-XHTML), matching KOReader's crengine DocFragment numbering. However, large logical chapters are sometimes split across multiple spine HTML files by publishers, meaning a single logical chapter may span several DocFragment indices. The element-index matching in step 4 accounts for this by matching within the correct DocFragment rather than assuming a chapter-per-DocFragment structure.

---

## 4. ABS API Integration

All requests use the shared Bearer token from `settings.audiobookshelf_api_key`.

### 4a. Fetch Progress

```
GET /api/me/progress/{libraryItemId}
Authorization: Bearer {api_key}
```

**Response (200 OK):**

```json
{
  "id": "...",
  "libraryItemId": "li_abc123",
  "currentTime": 145.0,
  "duration": 3600.0,
  "progress": 0.0403,
  "isFinished": false,
  "lastUpdate": 1715000000000
}
```

| Field | Type | Description |
|-------|------|-------------|
| `currentTime` | float | Playback position in seconds |
| `duration` | float | Total audiobook duration in seconds |
| `progress` | float | Fraction 0.0–1.0 |
| `lastUpdate` | int | Unix timestamp in milliseconds (UTC) |

Returns **404** if the user has no progress for this item — treat as no progress, not an error.

### 4b. Update Progress

```
PATCH /api/me/progress/{libraryItemId}
Authorization: Bearer {api_key}
Content-Type: application/json

{
  "currentTime": 310.5,
  "duration": 3600.0,
  "progress": 0.0863
}
```

No meaningful response body. Any non-2xx status is logged as an error and the sync for that mapping is aborted.

---

## 5. KOSync Write Logic

Progress is written directly to the database via a shared helper function extracted from `routers/progress.py`. The upsert logic must not be duplicated — both the HTTP endpoint (`PUT /syncs/progress`) and the sync job call the same function so that any future changes (new fields, `is_latest` behaviour, etc.) apply everywhere.

**Shared helper — `earmark/services/progress.py`:**

```python
async def write_reading_progress(
    session: AsyncSession,
    *,
    kosync_user_id: int,
    document: str,
    progress: str,
    percentage: float,
    device: str,
    device_id: str,
    title: str | None = None,
    authors: str | None = None,
    filename: str | None = None,
) -> ReadingProgress:
    await session.execute(
        update(ReadingProgress)
        .where(
            ReadingProgress.kosync_user_id == kosync_user_id,
            ReadingProgress.document == document,
            ReadingProgress.is_latest == True,
        )
        .values(is_latest=False)
    )
    record = ReadingProgress(
        kosync_user_id=kosync_user_id,
        document=document,
        progress=progress,
        percentage=percentage,
        device=device,
        device_id=device_id,
        title=title,
        authors=authors,
        filename=filename,
        is_latest=True,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record
```

`routers/progress.py:upsert_progress` is refactored to call `write_reading_progress` instead of containing the upsert inline. The sync job calls the same function.

**Device identity:** all sync-job writes use `device = "earmark-sync"` and `device_id = "earmark-sync"`. This identifies the sync job as its own virtual device in the KOSync history, separate from KOReader devices.

**Which KosyncUsers:** when syncing ABS → KOSync, write to **all** `KosyncUser` records owned by the earmark `User` (i.e., `KosyncUser.user_id == mapping.user_id`). This ensures all KOReader devices pick up the updated position on their next sync.

---

## 6. Warning and Skip Conditions

The sync job logs `logger.warning(...)` and silently skips the update in the following cases:

| Condition | Log message |
|-----------|-------------|
| ABS → KOSync: new `percentage ≤` current KOSync `percentage` | `"Skipping KOSync update for {abs_item_id}: new percentage {x:.4f} ≤ current {y:.4f}"` |
| KOSync → ABS: new `currentTime ≤` current ABS `currentTime` | `"Skipping ABS update for {abs_item_id}: new position {x:.1f}s ≤ current {y:.1f}s"` |
| KOSync → ABS: DocFragment not found in sync map | `"Cannot map KOSync XPath to ABS for {abs_item_id}: DocFragment[{N}] not in sync map"` |
| Mapping has no completed alignment job | `"Skipping {abs_item_id}: no completed alignment job"` |
| Mapping has no `kosync_document` | `"Skipping {abs_item_id}: no kosync_document"` |
| User has no KosyncUsers | `"Skipping user {user_id}: no KosyncUsers linked"` |

---

## 7. Scheduler Integration

The sync job runs on a fixed interval (default 5 minutes, configurable via `settings.sync_interval_minutes`) using APScheduler:

```python
# earmark/scheduler.py
async def sync_progress() -> None:
    logger.info("Running progress sync")
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(AbsEbookMapping)
            .join(AlignmentJob, AbsEbookMapping.alignment_job_id == AlignmentJob.id)
            .options(selectinload(AbsEbookMapping.user).selectinload(User.kosync_users))
            .where(
                AbsEbookMapping.kosync_document.isnot(None),
                AlignmentJob.status == "complete",
                AlignmentJob.sync_map_path.isnot(None),
            )
        )
        abs_client = AudiobookshelfClient()
        try:
            for mapping in result.scalars():
                await _sync_mapping(mapping, abs_client, session)
        finally:
            await abs_client.close()
```

`_sync_mapping` handles one mapping end-to-end: fetching both sides, comparing timestamps, converting positions, applying the forward-only guard, and writing. Errors within a single mapping are caught and logged so that one failing mapping does not abort the entire sync run.

The `AsyncSessionLocal` session factory is imported from `earmark.database` (line 7).

---

## 8. Error Handling

| Scenario | Behavior |
|----------|----------|
| ABS `GET /api/me/progress` returns 404 | Treat as no ABS progress — sync from KOSync to ABS if KOSync has a position |
| ABS `GET /api/me/progress` returns other error | Log error, skip this mapping for this run |
| ABS `PATCH /api/me/progress` fails | Log error, skip this mapping for this run |
| `sync_map_path` file missing from disk | Log error (`"Sync map not found: {path}"`), skip mapping |
| `sync_map_path` contains malformed JSON | Log error, skip mapping |
| Sync map is empty | Log warning, skip mapping |
| DocFragment[N] not found in sync map (KOSync → ABS) | Log warning (see §6), skip update |
| Exception inside `_sync_mapping` | Log exception with mapping ID, continue to next mapping |
| KosyncUser has no progress for `kosync_document` | Treat as no KOSync progress — sync from ABS to KOSync if ABS has a position |
