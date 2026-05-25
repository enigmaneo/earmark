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
11. [Audio Transcription (WhisperX)](#11-audio-transcription-whisperx)
12. [Paragraph Matching (rapidfuzz)](#12-paragraph-matching-rapidfuzz)
13. [Final Assembly](#13-final-assembly)
14. [Output Schema](#14-output-schema)
15. [Dependencies](#15-dependencies)
16. [Error Handling](#16-error-handling)
    - [16a. Validation Warnings](#16a-validation-warnings)

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
                    └─► parse EPUB, classify spine, extract bodymatter paragraphs
                          └─► concatenate audio → WhisperX transcribe (word-level timestamps)
                                └─► fuzzy-match EPUB paragraphs to transcript (rapidfuzz)
                                      └─► validate + write sync_map.json (warnings → status)
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
    concatenated.wav       ← ephemeral; fed to WhisperX, deleted after assembly
    ebook.epub
    sync_map.json          ← durable output artifact
```

**Cache invalidation:** On pipeline start, `metadata.json` is read and its `updatedAt` value is compared against the live ABS API. If ABS is newer, all cached files for that item are deleted and re-downloaded.

`concatenated.wav` is regenerated each run and removed after the pipeline completes.

`sync_map.json` is the final artifact. Its path is written to `alignment_jobs.sync_map_path`.

---

## 6. EPUB Parsing & Extraction

**Libraries:** `ebooklib` to open the EPUB and iterate the spine; `BeautifulSoup` to parse each HTML document.

```python
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup

book = epub.read_epub(ebook_path)
first_body_pos, last_body_pos, _ = _classify_spine(book)  # see §6a

paragraphs = []
for spine_pos, (item_id, _attrs) in enumerate(book.spine, start=1):
    if spine_pos < first_body_pos or spine_pos > last_body_pos:
        continue
    item = book.get_item_with_id(item_id)
    soup = BeautifulSoup(item.get_content(), "html.parser")
    for p in soup.find_all("p"):
        text = p.get_text(separator=" ").strip()
        if text:
            paragraphs.append((item.file_name, p, text))
```

Paragraphs are collected in EPUB spine order, restricted to the **bodymatter range** `[first_body_pos, last_body_pos]` (1-based, inclusive). Empty paragraphs are skipped. Each surviving paragraph is assigned a sequential ID: `para_001`, `para_002`, …

The job's `status` is set to `parsing_epub` at the start of this stage, and `paragraph_count` is set to the final count on completion.

### 6a. Front/Back Matter Detection (`_classify_spine`)

`_classify_spine` walks the EPUB spine and classifies each item as `front`, `back`, `body`, `ambiguous`, or `skip`. The bodymatter range is the position of the first `body` item through the position of the last `body` item, inclusive — anything outside that range is dropped.

Classification uses four signals, in priority order:

1. **EPUB3 `nav` landmarks** — when a `<nav epub:type="landmarks">` element is present in the EPUB navigation document, an `<a>` whose `epub:type` is `frontmatter`, `bodymatter`, or `backmatter` is authoritative for that spine item. This is the cleanest signal and always wins.
2. **Spine `linear="no"`** — items the publisher flagged as non-linear (covers, supplementary pages) are classified `front`.
3. **TOC title and spine filename/id substrings** — the TOC title (lowercase, whitespace-collapsed) is tested against a phrase list (`_FRONT_PHRASES`, `_BACK_PHRASES` — "praise", "dedication", "contents", "copyright", "about the author", "acknowledgments", "glossary", "bibliography", …). The spine item's `file_name` and `id` (joined and lowercased with `-` → `_`) are tested against substring tokens (`_FRONT_FILE_TOKENS`, `_BACK_FILE_TOKENS` — "frontmatter", "copyright", "dedication", "halftitle", "acknowledg", "about_the_author", "backmatter", …). Tokens like `also_by` and `acknowledg` appear on both sides; an item that matches both is `ambiguous`.
4. **Content shape** — items dominated by short attribution lines (`— The New York Times`) or `<blockquote>`/`<cite>` content are `front` (`_is_blurb_shaped`). Items with fewer than two paragraphs of ≥40 characters are `ambiguous` (likely chapter dividers or end-of-book ad pages).

A strong **body** signal (an `<h1>`/`<h2>` that matches `prologue|epilogue|chapter|book|part|<digit>|<roman>`) overrides front-matter filename hints. This is what catches the common case where a publisher names a spine item `frontmatter02.xhtml` but it actually contains the Prologue.

When the EPUB ships with `nav` landmarks, classification is essentially exact. Without landmarks, the heuristic still handles the practical cases seen in commercial releases: drift in the heuristic shows up later as warnings (see [§16a](#16a-validation-warnings)).

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

EPUB paragraphs are matched to audio time ranges by fuzzy-matching paragraph text against the WhisperX word-level transcript. The matcher is **monotonic** — paragraphs are processed in EPUB reading order and the search cursor only moves forward in the transcript:

```
EPUB spine (reading order)
  │
  ▼
Extract paragraphs (bodymatter only) → assign IDs in order
  para_000  "It was the best of times..."     ebook_pos = /body/DocFragment[1]/body/section[1]/p[1]
  para_001  "it was the worst of times..."    ebook_pos = /body/DocFragment[1]/body/section[1]/p[2]
  │
  ▼
WhisperX transcribes the audio → word-level timestamps
  [
    {"word": "it", "start": 0.10, "end": 0.18},
    {"word": "was", "start": 0.19, "end": 0.30},
    ...
  ]
  │
  ▼
Build a normalized transcript string + (char → time) mapping.
For each paragraph in order, rapidfuzz finds the best partial-ratio
substring match in a forward-only window. The matched char range
maps back to (audio_start, audio_end). Paragraphs whose best score
is below `min_score=60` are recorded as None and dropped.

  para_000: audio 0.10–5.21    ebook_pos /body/DocFragment[1]/body/section[1]/p[1]
  para_001: audio 5.30–12.10   ebook_pos /body/DocFragment[1]/body/section[1]/p[2]
```

**Invariant:** the paragraph search cursor advances monotonically through the transcript. EPUB paragraphs that don't appear in the audio (front-matter blurbs, back-matter acknowledgments) simply don't anchor anywhere and are dropped from the final map — they never poison the alignment of surrounding paragraphs.

---

## 9. Multi-File Audio Handling

Audiobookshelf commonly stores audiobooks as a folder of MP3 files — one per chapter. WhisperX expects a single audio file. The pipeline concatenates files in `index` order with ffmpeg:

1. Sort `audioFiles` by their `index` field (ascending).
2. Write an ffmpeg concat list of absolute paths.
3. Concatenate and normalize:
   ```bash
   ffmpeg -f concat -safe 0 -i filelist.txt -ar 16000 -ac 1 concatenated.wav
   ```
4. Pass `concatenated.wav` to WhisperX.

If the audio is already a single `.mp3`, `.m4b`, or `.m4a` file, concatenation is skipped and the original file is fed in directly — WhisperX handles those formats via its internal ffmpeg call.

---

## 10. Audio Format Handling

| Format | Notes |
|--------|-------|
| `.mp3` | Single or multi-file. Multi-file → concatenate. Single → pass directly. |
| `.m4b` | Single AAC audiobook container. Passed directly. |
| `.m4a` | Single AAC. Same as `.m4b`. |
| `.flac` / `.ogg` / `.opus` / `.aac` | Concatenated to WAV at 16 kHz mono via ffmpeg before WhisperX. |

`-ar 16000 -ac 1` (16 kHz mono PCM) is what WhisperX expects internally — pre-normalizing avoids codec edge cases and keeps memory predictable across formats.

---

## 11. Audio Transcription (WhisperX)

WhisperX transcribes the concatenated audio and produces **word-level timestamps** via wav2vec2 forced alignment. It replaces the previous aeneas + chapter-rescaling pipeline. The key win: alignment is now text-based, not positional — front matter, back matter, intro tracks, and split chapters no longer cascade errors through the rest of the book.

```python
import whisperx

model = whisperx.load_model(model_name, device, compute_type=compute_type, language=lang)
audio = whisperx.load_audio(str(audio_path))
result = model.transcribe(audio, batch_size=batch_size, language=lang)

align_model, metadata = whisperx.load_align_model(language_code=lang, device=device)
aligned = whisperx.align(
    result["segments"], align_model, metadata, audio, device,
    return_char_alignments=False,
)

words = [
    {"word": w["word"], "start": float(w["start"]), "end": float(w["end"])}
    for seg in aligned["segments"]
    for w in seg.get("words", [])
    if "start" in w and "end" in w
]
```

Word timestamps are **absolute** seconds in the original audio. No pre-trim is needed; intros and credits just don't get matched to any EPUB paragraph.

**Configuration** (all via `Settings` / env vars):

| Setting | Default | Notes |
|---------|---------|-------|
| `WHISPER_MODEL` | `tiny.en` | `tiny.en` / `base.en` / `small.en` / `medium.en` / `large-v3` |
| `WHISPER_DEVICE` | `cpu` | `cuda` for NVIDIA GPU; `mps` experimentally on Apple Silicon |
| `WHISPER_COMPUTE_TYPE` | `int8` | `float16` on GPU |
| `WHISPER_BATCH_SIZE` | `16` | Higher uses more memory |
| `WHISPER_LANGUAGE` | `en` | wav2vec2 alignment model is loaded per-language |

The pipeline updates `status=aligning, progress=30` before transcription and `progress=85, fragment_count=len(words)` after. Transcription is the dominant cost: ~1× real-time on `tiny.en` CPU, scaling roughly linearly with model size; CUDA cuts this 10×+.

---

## 12. Paragraph Matching (rapidfuzz)

WhisperX gives a stream of timestamped words. Each EPUB paragraph is mapped onto a contiguous run of those words by **monotonic fuzzy substring matching**.

```python
def _build_transcript_index(words):
    # Concatenate normalized words into a single transcript; record each
    # word's (char_start, char_end, time_start, time_end).
    ...

def _align_paragraphs_to_transcript(paragraphs, transcript, ranges):
    # For each paragraph in order, search a forward-only window for the best
    # fuzzy match; convert matched char range to a time range via `ranges`.
    from rapidfuzz import fuzz
    cursor = 0
    for i, p in enumerate(paragraphs):
        win = transcript[max(cursor, expected - W//4) : … + W]
        m = fuzz.partial_ratio_alignment(_normalize_text(p), win)
        if m.score < 60:
            yield None                       # paragraph not in narrated audio
            continue
        t_start = ranges[_word_index_at_char(ranges, m.dest_start)][2]
        t_end   = ranges[_word_index_at_char(ranges, m.dest_end - 1)][3]
        cursor  = m.dest_start + len(p)//2   # advance monotonically
        yield (t_start, t_end)
```

Two properties matter:

1. **Monotonic:** paragraphs are matched in order, the search window only moves forward. This stops repeated phrasing from re-anchoring later paragraphs to earlier audio.
2. **Per-paragraph score gate:** if the best match scores below `min_score=60`, the paragraph is recorded as `None` and dropped from the final sync map. This is how unnarrated back matter (acknowledgments, copyright pages) and unmapped front matter naturally fall out of the result.

Both properties together let the pipeline degrade gracefully when ABS audio splits a chapter that the EPUB keeps whole, or when either side has extra material — the fuzzy matcher just doesn't anchor those paragraphs and they're skipped without poisoning the surrounding alignment.

The job's `status` is set to `assembling, progress=92` after transcription finishes and matching begins.

---

## 13. Final Assembly

Matched paragraphs are written to `sync_map.json` in EPUB order:

```python
sync_map = []
for para_id, alignment in zip(para_ids, alignments):
    if alignment is None:
        continue                                          # skipped — see §12
    audio_start, audio_end = alignment
    entry = index[para_id]
    sync_map.append({
        "id": para_id,
        "audio_start": audio_start,
        "audio_end": audio_end,
        "ebook_pos": entry["ebook_pos"],
        "text_snippet": entry["text"],
    })

sync_map_path.write_text(json.dumps(sync_map, indent=2, ensure_ascii=False))
```

After writing the file, the pipeline runs `_validate_sync_map` (see [§16a](#16a-validation-warnings)) and any warnings are persisted on the `alignment_jobs.warnings` column (JSON-encoded `list[str]`). The job's terminal `status` is:

- `complete` — no warnings, sync map fully usable
- `complete_with_warnings` — warnings present but sync map is still readable through the API

```python
job.status = "complete_with_warnings" if warnings else "complete"
job.sync_map_path = str(sync_map_path)
job.fragment_count = len(sync_map)
job.warnings = json.dumps(warnings) if warnings else None
job.completed_at = datetime.utcnow()
```

The only ephemeral file is `concatenated.wav`, deleted on success. WhisperX model weights are cached by `huggingface_hub` outside of the project tree.

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

| Package | Purpose |
|---------|---------|
| `ebooklib` | Open and iterate EPUB spine documents |
| `beautifulsoup4` | Parse HTML within EPUB document items |
| `whisperx` (optional `align` extra) | Whisper transcription + wav2vec2 forced alignment |
| `rapidfuzz` | Monotonic fuzzy substring matching of paragraphs to transcript |
| `ffmpeg-python` | Audio concatenation and format normalization |

The `whisperx` dependency lives behind the `align` optional extra (`pip install -e ".[align]"`). It pulls in PyTorch, which currently ships wheels only for Python ≤3.13.

**System dependencies:**

- `ffmpeg` — audio decoding and concatenation

Install on macOS: `brew install ffmpeg`
Install on Debian/Ubuntu: `apt-get install ffmpeg`

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
| ffmpeg concatenation error | `aligning` | Set `status=failed`, `error_message=str(e)` |
| WhisperX raises an exception | `aligning` | Capture exception message; set `status=failed`, `error_message=str(e)` |
| Cache stale (`abs_updated_at` newer) | Pre-flight | Delete cached files; create a new `AlignmentJob` row; re-run from scratch |
| Partial cache (audio present, ebook missing) | Pre-flight | Re-download missing files only; reuse what is present |

### 16a. Validation Warnings

After matching, `_validate_sync_map` scores the result. Any warnings are stored as a JSON list on `AlignmentJob.warnings` and the job's status becomes `complete_with_warnings` (sync map is still readable through the API).

| Warning string | Trigger |
|---|---|
| `suspect_first_entry: '<snippet>'` | `sync_map[0].text_snippet` is shorter than 40 characters or matches the blurb attribution pattern `^[—\-–]\s*[A-Z]`. Usually means front matter slipped through `_classify_spine`. |
| `audio_offset_excessive: Xs / Ys` | The first matched paragraph starts more than 5% into the book's total duration. Either the EPUB skipped a long intro or the audio has unmatched front narration. |
| `docfragment_gap: missing [N, …]` | More than two `DocFragment[N]` spine positions are absent between the first and last entry in the final sync map. Indicates whole chapters were skipped — likely a misclassification or a transcript coverage problem. |
| `low_transcript_coverage: N/M paragraphs unmatched` | More than 10% of EPUB paragraphs failed to fuzzy-match (`score < 60`). Usual causes: back matter still in the EPUB, transcript model too small for the speaker, or large audio gaps. |
| `chapter_rescale_extreme: …` | *(legacy)* preserved in `_validate_sync_map` for callers that still pass non-empty scale data; the WhisperX pipeline does not emit chapter rescales. |

Operationally: a `complete_with_warnings` job is still consumable — the sync map is written and the API serves it. Warnings just surface what to check: usually re-classifying spine items or bumping `WHISPER_MODEL` to `base.en`/`small.en` resolves the underlying issue.
