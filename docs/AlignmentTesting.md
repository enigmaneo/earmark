# Alignment Pipeline Testing Guide

This guide explains how to set up and manually test the audiobook-ebook alignment pipeline end-to-end against a real Audiobookshelf server.

## Prerequisites

### 1. Install system and Python dependencies

```bash
uv sync --extra align            # core deps + WhisperX (alignment-only extra; needs Python 3.12 or 3.13)
brew install ffmpeg              # macOS — required for audio decoding
# apt-get install ffmpeg         # Debian/Ubuntu equivalent
```

WhisperX pulls in PyTorch, which currently has wheels only for Python ≤3.13. `pyproject.toml` pins `requires-python = ">=3.12,<3.14"` to keep `uv sync` honest. If you previously created the venv on a newer Python, recreate it: `rm -rf .venv && uv venv --python 3.13`.

### 2. Configure environment

Copy `.env.example` to `.env` and set at minimum:

```
AUDIOBOOKSHELF_URL=https://your-abs-server
AUDIOBOOKSHELF_API_KEY=your-api-key
```

Tuning the WhisperX run (defaults in parentheses):

```
WHISPER_MODEL=tiny.en            # (tiny.en) other choices: base.en, small.en, medium.en, large-v3
WHISPER_DEVICE=cpu               # (cpu) — or "cuda" if you have a CUDA GPU, "mps" experimentally
WHISPER_COMPUTE_TYPE=int8        # (int8) — "float16" on GPU
WHISPER_BATCH_SIZE=16            # (16)
WHISPER_LANGUAGE=en              # (en)
LOG_LEVEL=DEBUG                  # see stage-by-stage logging
```

### 3. Obtain an ABS item ID and an EPUB file

- **Item ID**: in the ABS UI, open a book — the ID is the UUID in the URL (`/item/d07beaed-…`). The item must have audio files attached.
- **EPUB file**: the ebook corresponding to that audiobook. Local files work; the ebook does not need to be attached to the ABS item.

---

## Running the Test Script

```bash
uv run python testing/test_alignment.py \
    --item-id  <ABS_ITEM_ID> \
    --ebook-file /path/to/book.epub
```

The script:
1. Initialises the database (creates tables if needed).
2. Creates an `AlignmentJob` row and starts the pipeline.
3. Polls and prints stage transitions every 2 seconds.
4. On completion, prints job statistics and a preview of the first 10 sync map entries.

### Example output

```
Initializing database...
Created alignment job #1 for item 'd07beaed-…'
EPUB: /path/to/book.epub

Pipeline progress:
  [17:07:06] Pending
  [17:07:08] Parsing EPUB and extracting paragraphs
             Paragraphs extracted: 3,434
  [17:07:24] Running WhisperX transcription + alignment
  [18:23:11] Complete
             Fragments aligned:    3,420

Completed in 1h 16m
…
```

Expect transcription to dominate runtime — on CPU with the `tiny.en` model, a 12-hour audiobook takes roughly an hour; `base.en` is roughly 2×, and `medium.en` is 5×+. A CUDA GPU brings this down by an order of magnitude.

---

## Cache

All downloaded and intermediate files are stored under `.cache/earmark/<item-id>/`:

```
.cache/earmark/<item-id>/
  audio/             ← downloaded MP3/M4B files (zero-padded index prefix)
  ebook.epub         ← (only when ebook_source=abs; skipped when --ebook-file is used)
  concatenated.wav   ← ephemeral; created before WhisperX, deleted after
  sync_map.json      ← final output
  .abs_updated_at    ← cache sentinel; compared against live ABS updatedAt on each run
```

**Cache invalidation:** if the ABS item's `updatedAt` timestamp has advanced since the last run, all cached files are deleted and re-downloaded. To force a clean run, delete `.cache/earmark/<item-id>/` manually.

---

## Validation Warnings

After WhisperX runs, the pipeline scores the sync map and records any warnings on `AlignmentJob.warnings`. A job with warnings finishes in status `complete_with_warnings` (the sync map is still readable through the API). Warning strings:

| Warning | Meaning |
|---------|---------|
| `suspect_first_entry: …` | The first sync-map entry is very short or matches a blurb pattern — usually means front matter leaked through. |
| `audio_offset_excessive: Xs / Ys` | The first matched paragraph starts more than 5% into the book; potentially missed intro narration. |
| `docfragment_gap: missing […]` | More than two `DocFragment[N]` spine positions are absent from the final map — the pipeline silently skipped over chapters. |
| `low_transcript_coverage: N/M paragraphs unmatched` | More than 10% of EPUB paragraphs failed fuzzy-matching against the audio transcript. Usually indicates back-matter pollution or audio missing entire chapters. |

To exercise these in tests, run `uv run pytest tests/test_alignment.py -k validate -v`.

---

## Common Failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ModuleNotFoundError: No module named 'whisperx'` | `align` extra not installed | `uv pip install -e ".[align]"` |
| `Distribution torch can't be installed … no wheels for cp314` | Python 3.14 venv | Recreate venv with Python 3.12 or 3.13 |
| First sync-map entry is praise/blurb text | EPUB front matter not detected as front matter | See `_classify_spine` in `src/earmark/services/alignment.py` — landmarks/title/filename/blurb signals |
| `low_transcript_coverage` warning on a clean book | Whisper model too small | Try `WHISPER_MODEL=base.en` or `small.en` |
| Run times out / OOM | Audio too long for available RAM | Use `int8` compute_type and `tiny.en` model |
| ffmpeg `No such file or directory` in concat list | Relative paths in concat list | Fixed in code (uses absolute paths) |

---

## Verifying Alignment Accuracy

The sync map preview printed at the end of each run shows the first 10 entries. To verify against a known audiobook, listen to the audio and note actual start times of the first paragraphs, then compare.

WhisperX produces **word-level timestamps via wav2vec2 forced alignment**, then paragraphs are matched via `rapidfuzz.fuzz.partial_ratio_alignment`. Expected per-paragraph accuracy: **±1–2 seconds** with `tiny.en`, **±0.5 seconds** with `medium.en` or larger.

When ABS audio splits a chapter that the EPUB keeps whole (or vice versa), the old aeneas pipeline produced hours of offset error; WhisperX handles this naturally because the match is text-based, not positional.

---

## Re-running After Failure

Each test run creates a new `AlignmentJob` row. Failed jobs are never modified. Re-run the script — if audio is already cached and the ABS timestamp hasn't changed, the download stage is skipped.

To reset everything:

```bash
rm -rf .cache/earmark/<item-id>/
uv run python testing/test_alignment.py --item-id <id> --ebook-file /path/to/book.epub
```
