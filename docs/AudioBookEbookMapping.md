# AudioBook–Ebook Forced Alignment

This document describes the pipeline that force-aligns an audiobook from Audiobookshelf (ABS) with its companion EPUB ebook, producing a JSON mapping from audio timestamps to EPUB paragraph positions. The output enables read-along synchronization between an audiobook player and an ebook reader (e.g., KOReader via KOSync).

## Table of Contents

1. [Overview](#1-overview)
2. [Database Schema](#2-database-schema)
3. [Audiobookshelf API Integration](#3-audiobookshelf-api-integration)
4. [Ebook Sourcing](#4-ebook-sourcing)
5. [Local Cache Storage Structure](#5-local-cache-storage-structure)
6. [EPUB Parsing & Extraction](#6-epub-parsing--extraction)
7. [Indexing](#7-indexing)
8. [The Core Mapping Mechanism](#8-the-core-mapping-mechanism)
9. [Multi-File Audio Handling](#9-multi-file-audio-handling)
10. [Audio Format Handling](#10-audio-format-handling)
11. [Aeneas Preparation](#11-aeneas-preparation)
12. [Forced Alignment](#12-forced-alignment)
    - [12a. Audio Trimming (Chapter Offset)](#12a-audio-trimming-chapter-offset)
13. [Final Assembly](#13-final-assembly)
    - [13a. Chapter-Based Rescaling](#13a-chapter-based-rescaling)
14. [Output Schema](#14-output-schema)
15. [Dependencies](#15-dependencies)
16. [Error Handling](#16-error-handling)

---

## 1. Overview

**Input:** An Audiobookshelf library item ID (`abs_item_id`) that has both audio files and an ebook file attached.

**Output:** `sync_map.json` — an ordered array of paragraph-level alignment entries, each pairing an audio time range with an EPUB position.

**Pipeline stages:**

```
ABS API
  └─► fetch item metadata & cache to DB (abs_library_items)
        └─► download audio files → local cache
              └─► download ebook → local cache
                    └─► parse EPUB, extract paragraphs, build index
                          └─► write paragraphs.txt for aeneas
                                └─► run aeneas forced alignment
                                      └─► merge timestamps + EPUB positions → sync_map.json
```

Progress for each run is tracked in the `alignment_jobs` database table, updated at each stage so the job can be monitored or resumed after failure.

---

## 2. Database Schema

Two new tables are added to `earmark/models.py`, following the existing `Mapped`/`mapped_column` SQLAlchemy pattern. An Alembic migration is required to create them.

### `abs_library_items` — ABS item metadata

Mirrors the Audiobookshelf item record locally. Used for cache invalidation: the `abs_updated_at` field is compared against the live ABS `updatedAt` value at pipeline start — if ABS is newer, the cached files are discarded and re-fetched. `raw_metadata` stores the full ABS response JSON for debugging.

```python
class AbsLibraryItem(Base):
    __tablename__ = "abs_library_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    abs_item_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    library_id: Mapped[str] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500))
    author: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ebook_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ebook_format: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "epub", "pdf"
    audio_file_count: Mapped[int] = mapped_column(Integer)
    total_duration_seconds: Mapped[float] = mapped_column(Float)
    abs_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    raw_metadata: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    alignment_jobs: Mapped[list["AlignmentJob"]] = relationship(back_populates="library_item")
```

### `alignment_jobs` — pipeline progress tracking

One row per pipeline run. `status` is updated as the pipeline advances through each stage. A failed job is never modified after failure; a retry creates a new row.

```python
class AlignmentJob(Base):
    __tablename__ = "alignment_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    abs_item_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("abs_library_items.abs_item_id"), index=True
    )
    status: Mapped[str] = mapped_column(String(50), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_cache_dir: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    ebook_cache_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    sync_map_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    paragraph_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fragment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    library_item: Mapped["AbsLibraryItem"] = relationship(back_populates="alignment_jobs")
```

**`status` lifecycle:**

```
pending
  └─► fetching_audio
        └─► fetching_ebook
              └─► parsing_epub
                    └─► aligning
                          └─► assembling
                                └─► complete
                                └─► failed  (from any stage)
```

Each transition writes `status` and `updated_at`. On failure, `error_message` is populated. `paragraph_count` is set after `parsing_epub`; `fragment_count` is set after `aligning`. A mismatch between them is logged as a warning but does not fail the job — alignment proceeds up to `min(paragraphs, fragments)`.

---

## 3. Audiobookshelf API Integration

The existing `earmark/services/audiobookshelf.py` client is extended with the methods below. Authentication uses a Bearer token from `settings.audiobookshelf_api_key` on every request.

```
Authorization: Bearer {api_key}
```

### 3a. Fetch Item Metadata

```
GET /api/items/{item_id}?expanded=1
```

Relevant response fields:

```json
{
  "id": "li_abc123",
  "libraryId": "lib_xyz",
  "updatedAt": 1715000000000,
  "mediaType": "book",
  "media": {
    "metadata": {
      "title": "A Tale of Two Cities",
      "authorName": "Charles Dickens"
    },
    "audioFiles": [
      {
        "index": 1,
        "filename": "Chapter01.mp3",
        "ext": ".mp3",
        "duration": 1823.4,
        "codec": "mp3",
        "bitrate": 64000,
        "channels": 2
      },
      {
        "index": 2,
        "filename": "Chapter02.mp3",
        "ext": ".mp3",
        "duration": 2104.8,
        "codec": "mp3"
      }
    ],
    "ebookFile": {
      "filename": "tale-of-two-cities.epub",
      "ext": ".epub"
    }
  }
}
```

`updatedAt` is a Unix millisecond timestamp. It is stored in `abs_library_items.abs_updated_at` and compared on every pipeline run to detect stale caches.

If `ebookFile` is `null`, the pipeline cannot proceed — the job is set to `failed` immediately.

### 3b. Download Audio Files

```
GET /api/items/{item_id}/file/{filename}
```

Stream the response body to disk. Files are sorted by their `index` field before downloading and stored with a zero-padded index prefix to preserve order:

```
audio/001_Chapter01.mp3
audio/002_Chapter02.mp3
```

### 3c. Library Discovery (batch mode)

```
GET /api/libraries
GET /api/libraries/{lib_id}/items?limit=0
```

For batch alignment runs, filter items where `media.ebookFile != null` (ABS-attached ebook) or where a CWA/local match is expected for the item's title.

---

## 4. Ebook Sourcing

The ebook can come from three sources, selected by `ebook_source` in `earmark/config.py`. The pipeline resolves the source before the `fetching_ebook` stage and always deposits the result at `.cache/earmark/{item_id}/ebook.epub`.

```python
ebook_source: str = "abs"      # "abs" | "cwa" | "local"
cwa_url: str = ""              # base URL of Calibre-Web instance
cwa_username: str = ""
cwa_password: str = ""
ebook_local_root: str = ""     # root directory when ebook_source = "local"
```

### Mode A — ABS-attached ebook (`ebook_source = "abs"`, default)

The ABS item carries the ebook directly. Check `media.ebookFile` in the item metadata response:

```json
"ebookFile": {
  "filename": "tale-of-two-cities.epub",
  "ext": ".epub"
}
```

If present, download with:

```
GET /api/items/{item_id}/ebook
Authorization: Bearer {api_key}
```

Stream the response body to `.cache/earmark/{item_id}/ebook.epub`. If `ebookFile` is `null`, fail the job immediately — do not fall through to another source.

### Mode B — Calibre-Web / CWA (`ebook_source = "cwa"`)

Calibre-Web does not expose a traditional REST API. The pipeline uses its OPDS feed for discovery and its web download route for retrieval.

**Step 1 — Authenticate and get a session cookie**

```
POST /login
Content-Type: application/x-www-form-urlencoded

username={cwa_username}&password={cwa_password}
```

Store the returned session cookie. It is reused for all subsequent requests in this pipeline run.

**Step 2 — Search via OPDS**

```
GET /opds/search/{normalized_title}
Authorization: Basic base64({cwa_username}:{cwa_password})
```

Returns an Atom XML feed. Each `<entry>` contains:
- `<title>` — book title
- `<author><name>` — author name
- `<link rel="http://opds-spec.org/acquisition" type="application/epub+zip" href="/get/EPUB/{book_id}/...">` — EPUB download URL

Parse entries, normalize titles (lowercase, strip punctuation), and find the entry matching the ABS item's `title` and `authorName`. Extract `{book_id}` from the acquisition link `href`.

**Matching rule:** Require an exact normalized-title match. If zero or multiple matches are found, log all candidates and fail the job — do not guess.

**Step 3 — Download the EPUB**

```
GET /get/EPUB/{book_id}/{title}.epub
Cookie: session={session_cookie}
```

Stream to `.cache/earmark/{item_id}/ebook.epub`.

### Mode C — Local filesystem (`ebook_source = "local"`)

The EPUB already exists on a drive accessible to earmark.

**Discovery:** Walk `ebook_local_root` recursively and collect all `.epub` files. Normalize both the candidate filenames/parent directory names and the ABS item's `title`/`authorName` (lowercase, strip punctuation and articles). Apply matching in priority order:

1. Filename matches normalized title exactly
2. Parent directory matches normalized author AND filename matches normalized title
3. Any path component contains the normalized title (fallback — log a warning)

The highest-priority match wins. If no match is found, fail the job with an error message listing the search terms used.

**Caching:** Copy the matched file to `.cache/earmark/{item_id}/ebook.epub`. The source file is never modified.

---

## 5. Local Cache Storage Structure

All downloaded and intermediate files live under `.cache/earmark/` within the project root, keyed by ABS item ID.

```
.cache/earmark/
  {abs_item_id}/
    metadata.json          ← full ABS /api/items/{id}?expanded=1 response
    audio/
      001_Chapter01.mp3    ← zero-padded index prefix preserves playback order
      002_Chapter02.mp3
    concatenated.wav       ← ephemeral; created before trim step, deleted after
    trimmed.wav            ← ephemeral; chapter-trimmed audio fed to aeneas, deleted after
    ebook.epub
    paragraphs.txt         ← ephemeral; one paragraph per line, fed to aeneas
    sync_map.json          ← durable output artifact
```

**Cache invalidation:** On pipeline start, `metadata.json` is read and its `updatedAt` value is compared against the live ABS API. If ABS is newer, all cached files for that item are deleted and re-downloaded.

`concatenated.wav` and `paragraphs.txt` are always regenerated from scratch and removed after the pipeline completes. They are not considered durable.

`sync_map.json` is the final artifact. Its path is written to `alignment_jobs.sync_map_path`.

---

## 6. EPUB Parsing & Extraction

**Libraries:** `ebooklib` to open the EPUB and iterate the spine; `BeautifulSoup` to parse each HTML document.

```python
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

book = epub.read_epub(ebook_path)
paragraphs = []

for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
    soup = BeautifulSoup(item.get_content(), "html.parser")
    for p in soup.find_all("p"):
        text = p.get_text(separator=" ").strip()
        if text:
            paragraphs.append((item.file_name, p, text))
```

Paragraphs are collected in EPUB spine order. Empty paragraphs (whitespace-only after stripping) are skipped. Each surviving paragraph is assigned a sequential ID: `para_001`, `para_002`, and so on.

The job's `status` is set to `parsing_epub` at the start of this stage, and `paragraph_count` is set to the final count on completion.

---

## 7. Indexing

As paragraphs are extracted, an in-memory index maps each ID to its text and EPUB position:

```python
index: dict[str, dict] = {}

for seq, (doc_filename, element, text) in enumerate(paragraphs, start=1):
    para_id = f"para_{seq:03d}"
    spine_pos = spine_index[doc_filename]   # 1-based position in EPUB spine
    rel_path = _element_full_xpath(element) # full path from <body> to element

    index[para_id] = {
        "text": text,
        "ebook_pos": f"/body/DocFragment[{spine_pos}]{rel_path}",
        "chapter_file": doc_filename,
    }
```

**`ebook_pos` construction:**
- `DocFragment[N]` — the 1-based index of the HTML document within the EPUB spine
- The remainder is the **full hierarchical path** from `<body>` to the block element, built by `_element_full_xpath`. At each ancestor level, the element's position is counted among its same-tag siblings (1-based).

This produces a path that mirrors the actual DOM structure of the EPUB HTML, for example:

```
/body/DocFragment[2]/body/section[1]/div[2]/p[3]
```

This format is critical: KOReader's CRE engine navigates positions using the real DOM tree, so the XPath must match the actual nesting of the HTML. A flattened path like `/body/DocFragment[2]/body/p[3]` only works when `<p>` elements are direct children of `<body>`, which is uncommon in commercial EPUBs.

---

## 8. The Core Mapping Mechanism

This is the critical design invariant: **the sequential paragraph ID is the sole join key between the audio timeline and the EPUB position.**

The mechanism relies on three steps that all share the same sequential order:

```
EPUB spine (reading order)
  │
  ▼
Extract paragraphs → assign IDs in order
  para_001  "It was the best of times..."     ebook_pos = /body/DocFragment[1]/body/section[1]/p[1]
  para_002  "it was the worst of times..."    ebook_pos = /body/DocFragment[1]/body/section[1]/p[2]
  para_003  "it was the age of wisdom..."     ebook_pos = /body/DocFragment[1]/body/section[1]/p[3]
  │
  ▼
Write paragraphs.txt in the SAME order (line N = para_N)
  line 1:  "It was the best of times..."
  line 2:  "it was the worst of times..."
  line 3:  "it was the age of wisdom..."
  │
  ▼
aeneas returns fragments in the SAME order (fragment[i] = line i+1)
  fragment[0]:  begin=0.000   end=5.210
  fragment[1]:  begin=5.210   end=12.100
  fragment[2]:  begin=12.100  end=18.700
  │
  ▼
Merge: fragment[i] → para_{i+1:03d} → index[para_id].ebook_pos

  para_001: audio 0.000–5.210   ebook_pos /body/DocFragment[1]/body/section[1]/p[1]
  para_002: audio 5.210–12.100  ebook_pos /body/DocFragment[1]/body/section[1]/p[2]
  para_003: audio 12.100–18.700 ebook_pos /body/DocFragment[1]/body/section[1]/p[3]
```

**Invariant to preserve:** `paragraphs.txt` must be written in exactly the same order the IDs were assigned during extraction. aeneas guarantees its output fragments are in input line order. Therefore `fragment[N-1]` unambiguously maps to `para_{N:03d}` without any text matching or fuzzy lookup.

---

## 9. Multi-File Audio Handling

Audiobookshelf commonly stores audiobooks as a folder of MP3 files — one per chapter. aeneas expects a single audio file. Two strategies are supported:

### Strategy A — Concatenate then trim (preferred)

1. Sort `audioFiles` by their `index` field (ascending).
2. Write an ffmpeg concat list:
   ```
   file '/path/to/cache/audio/001_Chapter01.mp3'
   file '/path/to/cache/audio/002_Chapter02.mp3'
   ```
3. Concatenate and normalize for aeneas:
   ```bash
   ffmpeg -f concat -safe 0 -i filelist.txt -ar 16000 -ac 1 concatenated.wav
   ```
4. **Trim** the concatenated audio to the first chapter start time (see [§12a Audio Trimming](#12a-audio-trimming-chapter-offset)):
   ```bash
   ffmpeg -ss {chapter_start} -i concatenated.wav -ar 16000 -ac 1 trimmed.wav
   ```
5. Feed `trimmed.wav` to aeneas.

### Strategy B — Per-file with offsets (fallback)

Used when concatenation fails (e.g., mixed codecs, codec errors) or total audio exceeds a memory threshold.

1. Sort audio files by `index`.
2. Maintain a `cumulative_offset` starting at `0.0`.
3. For each file:
   a. Run aeneas on the file independently against the subset of paragraphs it covers.
   b. Add `cumulative_offset` to every `begin`/`end` value in the fragment output.
   c. Advance `cumulative_offset` by the file's `duration` (from ABS metadata).
4. Concatenate all offset-adjusted fragment lists in file order.

Paragraph-to-file assignment (for Strategy B): divide paragraphs evenly by ABS chapter metadata if available, otherwise divide proportionally by file duration.

---

## 10. Audio Format Handling

| Format | Type | Strategy |
|--------|------|----------|
| `.mp3` | Single or multi-file | Concatenate if multi; pass directly if single |
| `.m4b` | Single AAC container | Pass directly — aeneas uses ffmpeg internally |
| `.m4a` | Single AAC | Same as `.m4b` |
| `.flac` | Lossless, single or multi | Pre-convert each file to WAV via ffmpeg |
| `.ogg` / `.opus` | Vorbis/Opus | Pre-convert each file to WAV via ffmpeg |
| `.aac` | Raw AAC | Pre-convert to WAV via ffmpeg |

**Format detection:** Read the `ext` field on each `audioFile` object from the ABS metadata. If all files share the same extension, apply the corresponding strategy. If files are mixed format (unlikely but possible), normalize all to WAV first.

**Pre-conversion command** (for formats other than `.mp3` and `.m4b`):
```bash
ffmpeg -i input.flac -ar 16000 -ac 1 output.wav
```

`-ar 16000 -ac 1` (16 kHz mono PCM) is the recommended input specification for aeneas. Applying it at the pre-conversion step — rather than leaving it to aeneas — avoids codec edge cases and produces predictable behavior across formats.

---

## 11. Aeneas Preparation

Before calling aeneas, write the extracted text to a plain text file — one paragraph per line, in `para_XXX` order, with no blank lines.

```python
with open(paragraphs_path, "w", encoding="utf-8") as f:
    for para_id in index:   # insertion order = seq order (para_000, para_001, ...)
        f.write(index[para_id]["text"] + "\n")
```

**Do not sort `index.keys()` lexicographically.** For books with ≥1000 paragraphs the IDs cross the 3-digit/4-digit boundary, and `sorted()` puts `"para_1000"` between `"para_100"` and `"para_101"`, scrambling the fragment→id mapping. Python dicts preserve insertion order since 3.7, so iterating `index` directly gives the correct seq order.

Blank lines must be excluded: aeneas treats every line — including blank ones — as a text fragment to align. A blank line would produce a spurious fragment that shifts all subsequent ID mappings by one.

---

## 12. Forced Alignment

aeneas is invoked programmatically via `aeneas.executetask.ExecuteTask`:

```python
from aeneas.executetask import ExecuteTask
from aeneas.task import Task

config_str = (
    "task_language=eng"
    "|is_text_type=plain"
    "|os_task_file_format=json"
    "|task_adjust_boundary_algorithm=rate"
    "|task_adjust_boundary_rate_value=21"
)

task = Task(config_string=config_str)
task.audio_file_path_absolute = str(audio_path)          # concatenated.wav or single file
task.text_file_path_absolute = str(paragraphs_path)      # paragraphs.txt
task.sync_map_file_path_absolute = str(raw_output_path)  # aeneas_raw.json

ExecuteTask(task).execute()
task.output_sync_map_file()
```

**Key configuration parameters:**

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `task_language` | `eng` | Language for TTS synthesis used in alignment |
| `is_text_type` | `plain` | One fragment per line (matches `paragraphs.txt` format) |
| `os_task_file_format` | `json` | Output format for the sync map |
| `task_adjust_boundary_algorithm` | `rate` | Adjusts boundaries to respect max reading rate |
| `task_adjust_boundary_rate_value` | `21` | Max characters per second (typical audiobook pace) |

**Raw aeneas output format:**

```json
{
  "fragments": [
    {
      "id": "f000001",
      "begin": "0.000",
      "end": "5.210",
      "lines": ["It was the best of times..."],
      "children": []
    }
  ]
}
```

`begin` and `end` are string-encoded float seconds. The `fragments` array is in the same order as the input lines.

The job's `status` is set to `aligning` before this call, and `fragment_count` is set to `len(fragments)` on completion.

### 12a. Audio Trimming (Chapter Offset)

Many audiobooks open with a few seconds of publisher intro, narration of title/author, or music before the first chapter begins. If aeneas receives the full audio including this intro, it forces the early paragraphs of the first chapter to "consume" the intro section, producing timestamps that are systematically too late for all subsequent paragraphs.

**Fix:** trim the audio to the first chapter start before running aeneas.

The first chapter start time is taken from `media.chapters[1]["start"]` in the ABS item metadata (index 1 skips the intro track at index 0). If the chapters list has fewer than 2 entries, no trimming is done.

```python
chapters = item_metadata["media"]["chapters"]
chapter_start = float(chapters[1]["start"]) if len(chapters) >= 2 else 0.0

# trim concatenated.wav → trimmed.wav
ffmpeg.input(str(concat_path), ss=chapter_start) \
      .output(str(trimmed_path), ar=16000, ac=1, acodec="pcm_s16le") \
      .run(quiet=True)
```

aeneas is then run on `trimmed.wav`. Its output timestamps start at 0.0 (relative to the trimmed file). After assembly, `chapter_start` is added to every `audio_start` and `audio_end` value to convert back to absolute audio positions.

**Effect:** without trimming, errors of 15–35 seconds were observed in the first chapter of a tested audiobook. With trimming, errors reduced to 4–5 seconds.

---

## 13. Final Assembly

Load the aeneas raw output and merge with the in-memory index using positional order:

```python
import json

with open(raw_output_path) as f:
    aeneas_output = json.load(f)

fragments = aeneas_output["fragments"]
para_ids = list(index.keys())  # seq order — see §11
sync_map = []

for i, fragment in enumerate(fragments):
    para_id = para_ids[i]
    entry = index[para_id]

    sync_map.append({
        "id": para_id,
        "audio_start": float(fragment["begin"]),
        "audio_end": float(fragment["end"]),
        "ebook_pos": entry["ebook_pos"],
        "text_snippet": entry["text"],
    })

# Drop fragments aeneas couldn't align (begin == end, parked at audio duration).
# Typical cause: EPUB back matter (acknowledgments, copyright) not in the audiobook.
sync_map = [e for e in sync_map if e["audio_start"] != e["audio_end"]]

with open(sync_map_path, "w", encoding="utf-8") as f:
    json.dump(sync_map, f, indent=2, ensure_ascii=False)
```

After writing `sync_map.json`, the `alignment_jobs` row is updated:

```python
job.status = "complete"
job.sync_map_path = str(sync_map_path)
job.fragment_count = len(fragments)
job.completed_at = datetime.utcnow()
```

Ephemeral files (`concatenated.wav`, `trimmed.wav`, `paragraphs.txt`, `aeneas_raw.json`) are deleted after successful assembly.

### 13a. Chapter-Based Rescaling

Even after trimming, aeneas's DTW alignment tends to absorb inter-paragraph silence into the preceding fragment, causing within-chapter timestamps to drift 2–5 seconds from reality. Chapter-based rescaling corrects this by using ABS chapter boundaries as hard anchors.

**Algorithm:** after building the initial sync map (with `chapter_start` offset applied), group entries by their `DocFragment[N]` spine position. Map each spine position to an ABS chapter using the assumption that `chapters[1]` corresponds to `DocFragment[first_chapter_spine_pos]`, `chapters[2]` to the next spine item, and so on. Then linearly rescale all timestamps within each group to fit exactly within `[chapters[ch_idx]["start"], chapters[ch_idx+1]["start"]]`.

```python
scale = abs_ch_duration / aeneas_ch_duration
for entry in chapter_entries:
    entry["audio_start"] = abs_ch_start + (entry["audio_start"] - aeneas_ch_start) * scale
    entry["audio_end"]   = abs_ch_start + (entry["audio_end"]   - aeneas_ch_start) * scale
```

**Assumption:** ABS chapters are granular enough to correspond 1:1 with EPUB spine items. This holds for audiobooks where each chapter is a separate audio file (common for commercially released audiobooks). If ABS has very few coarse chapters, the rescaling is still applied but has less effect.

**Effect:** combined with audio trimming, rescaling reduced per-paragraph timing errors from 4–5 seconds down to ±2 seconds in testing.

**Limitation:** the remaining ±2 second error is inherent DTW drift and cannot be reduced without replacing aeneas with a VAD-based or transformer-based aligner (e.g., WhisperX, wav2vec2-MFA).

---

## 14. Output Schema

`sync_map.json` is an ordered JSON array. Each entry corresponds to one paragraph from the ebook and its aligned position in the audio.

```json
[
  {
    "id": "para_001",
    "audio_start": 0.000,
    "audio_end": 5.210,
    "ebook_pos": "/body/DocFragment[1]/body/section[1]/p[1]",
    "text_snippet": "It was the best of times, it was the worst of times,"
  },
  {
    "id": "para_002",
    "audio_start": 5.210,
    "audio_end": 12.100,
    "ebook_pos": "/body/DocFragment[1]/body/section[1]/p[2]",
    "text_snippet": "it was the age of wisdom, it was the age of foolishness,"
  }
]
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Sequential paragraph ID (`para_001`, `para_002`, …) |
| `audio_start` | float | Start of aligned audio segment in seconds |
| `audio_end` | float | End of aligned audio segment in seconds |
| `ebook_pos` | string | Full hierarchical XPath to the element: `/body/DocFragment[spine_index]/body/<ancestor_path>/<tag>[sibling_index]` |
| `text_snippet` | string | The paragraph text as extracted from the EPUB |

**XPath format detail:** each step in `ebook_pos` after `DocFragment[N]` corresponds to a real ancestor element in the EPUB HTML, with the element's 1-based index among same-tag siblings at that level. KOReader's CRE engine uses this same format when recording its own reading position. The paths are compatible in both directions — earmark writes positions KOReader can navigate to, and earmark can parse positions KOReader sends back (after stripping any trailing character-offset suffix such as `.0`).

The array is ordered by `audio_start` (ascending), which matches EPUB reading order provided the ebook and audio are aligned chapter-for-chapter.

---

## 15. Dependencies

The following packages are added to `pyproject.toml`:

| Package | Purpose |
|---------|---------|
| `ebooklib` | Open and iterate EPUB spine documents |
| `beautifulsoup4` | Parse HTML within EPUB document items |
| `aeneas` | Forced alignment engine |
| `ffmpeg-python` | Audio concatenation and format normalization |

**System dependencies** (must be installed separately):

- `ffmpeg` — required by aeneas for audio decoding and by the concatenation step
- `espeak` (or `espeak-ng`) — required by aeneas for TTS synthesis during alignment

Install on macOS:
```bash
brew install ffmpeg espeak
```

Install on Debian/Ubuntu:
```bash
apt-get install ffmpeg espeak
```

---

## 16. Error Handling

| Scenario | Stage | Behavior |
|----------|-------|----------|
| `ebookFile` is `null` on ABS item (mode `abs`) | Pre-flight | Set `status=failed`, `error_message="No ebook file on ABS item {id}"` |
| CWA OPDS returns zero matches | `fetching_ebook` | Set `status=failed`, log search terms used |
| CWA OPDS returns multiple ambiguous matches | `fetching_ebook` | Set `status=failed`, log all candidate titles — do not guess |
| CWA login fails (bad credentials) | `fetching_ebook` | Set `status=failed`, `error_message="CWA authentication failed"` |
| No EPUB found in `ebook_local_root` | `fetching_ebook` | Set `status=failed`, log normalized search terms |
| Audio download HTTP error | `fetching_audio` | Retry 3× with exponential backoff; fail job after exhaustion |
| Ebook download HTTP error | `fetching_ebook` | Retry 3× with exponential backoff; fail job after exhaustion |
| Unsupported audio format | `fetching_audio` | Set `status=failed`, `error_message="Unsupported audio format: {ext}"` |
| ffmpeg concatenation error | `aligning` | Fall back to per-file Strategy B; if that also fails, set `status=failed` |
| aeneas raises an exception | `aligning` | Capture exception message; set `status=failed`, `error_message=str(e)` |
| Fragment / paragraph count mismatch | `assembling` | Log warning; align up to `min(fragment_count, paragraph_count)` entries |
| Cache stale (`abs_updated_at` newer) | Pre-flight | Delete cached files; create a new `AlignmentJob` row; re-run from scratch |
| Partial cache (audio present, ebook missing) | Pre-flight | Re-download missing files only; reuse what is present |
