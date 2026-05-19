# Alignment Pipeline Testing Guide

This guide explains how to set up and manually test the audiobook-ebook forced alignment pipeline end-to-end against a real Audiobookshelf server.

## Prerequisites

### 1. Install system and Python dependencies

```bash
uv sync                        # install Python deps
bash scripts/install_aeneas.sh # install aeneas + espeak (one-time)
```

`install_aeneas.sh` handles everything in one shot:
- Installs `espeak` via Homebrew (required by aeneas at runtime for TTS synthesis)
- Downloads `aeneas 1.7.3.0` from PyPI
- Patches the source for numpy 2.x compatibility (`numpy.distutils` was removed in numpy 2.0)
- Installs into the project venv (skipping the `cew` C extension, which requires `libespeak` at link time)
- Patches the installed `wavfile.py` to use `numpy.frombuffer` instead of the removed `numpy.fromstring`

### 2. Configure environment

Copy `.env.example` to `.env` and set at minimum:

```
AUDIOBOOKSHELF_URL=https://your-abs-server
AUDIOBOOKSHELF_API_KEY=your-api-key
```

To see detailed pipeline logging during a test run, also set:

```
LOG_LEVEL=DEBUG
```

### 3. Obtain an ABS item ID and an EPUB file

- **Item ID**: In the Audiobookshelf UI, open a book — the ID is the UUID in the URL (`/item/d07beaed-...`). The item must have audio files attached.
- **EPUB file**: The ebook corresponding to that audiobook. It can be a local file; it does not need to be attached to the ABS item.

---

## Running the Test Script

```bash
uv run python testing/test_alignment.py \
    --item-id  <ABS_ITEM_ID> \
    --ebook-file /path/to/book.epub
```

The script:
1. Initialises the database (creates tables if needed)
2. Creates an `AlignmentJob` row and starts the pipeline in the background
3. Polls and prints stage transitions every 2 seconds
4. On completion, prints job statistics and a preview of the first 10 sync map entries

### Example output

```
Initializing database...
Created alignment job #1 for item 'd07beaed-7367-4182-abb6-650283530f83'
EPUB: /Users/you/Downloads/Remarkably Bright Creatures.epub

Pipeline progress:
  [17:07:06] Pending
  [17:07:08] Parsing EPUB and extracting paragraphs
             Paragraphs extracted: 3,441
  [17:07:24] Running aeneas forced alignment
  [17:11:57] Complete
             Fragments aligned:    3,441

Completed in 4m 50s

Job statistics:
  Paragraphs : 3,441
  Fragments  : 3,441
  Duration   : 4m 50s
  Sync map   : .cache/earmark/<item-id>/sync_map.json

Sync map preview (first 10 entries):
  ID         Start      End        EPUB position                          Text preview
  ...
```

---

## Cache

All downloaded and intermediate files are stored under `.cache/earmark/<item-id>/`:

```
.cache/earmark/<item-id>/
  audio/             ← downloaded MP3/M4B files (zero-padded index prefix)
  ebook.epub         ← (only when ebook_source=abs; skipped when --ebook-file is used)
  concatenated.wav   ← ephemeral; created before aeneas, deleted after
  paragraphs.txt     ← ephemeral; one paragraph per line
  sync_map.json      ← final output
  .abs_updated_at    ← cache sentinel; compared against live ABS updatedAt on each run
```

**Cache invalidation**: if the ABS item's `updatedAt` timestamp has advanced since the last run, all cached files are deleted and re-downloaded. To force a clean run, delete `.cache/earmark/<item-id>/` manually.

---

## Common Failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| `404 Not Found` on audio download | Wrong file identifier used in URL | Fixed in code (uses `ino` field now) |
| `ModuleNotFoundError: No module named 'aeneas'` | aeneas not installed | Run `bash scripts/install_aeneas.sh` |
| `No module named 'numpy.distutils'` during install | numpy 2.x removed `numpy.distutils` | `install_aeneas.sh` patches this automatically |
| `ValueError: binary mode of fromstring is removed` | numpy 2.x removed `numpy.fromstring` | `install_aeneas.sh` patches this automatically |
| `Both the C extension and pure Python code failed` | `espeak` not installed | `install_aeneas.sh` installs `espeak` via Homebrew |
| ffmpeg `No such file or directory` in concat list | Relative paths in concat list | Fixed in code (uses absolute paths now) |
| `FAILED after Ns` with no error printed | Job failed; check `error_message` | Re-run; the DB row is never modified after failure — each retry creates a new job |

---

## Verifying Alignment Accuracy

The sync map preview printed at the end of each run shows the first 10 entries. To verify accuracy against a known audiobook, listen to the audio and note the actual start time of the first few paragraphs, then compare with the generated timestamps.

### Expected accuracy

The pipeline applies two corrections on top of raw aeneas output:

1. **Audio trimming** — the audio is trimmed to the first chapter start before aeneas runs, preventing publisher intros from inflating early paragraph timestamps.
2. **Chapter-based rescaling** — timestamps are linearly rescaled within each EPUB chapter to match ABS chapter boundaries.

In practice (tested on *Remarkably Bright Creatures*), this produces **±2 second accuracy** at the paragraph level. Raw aeneas without these corrections had errors of 15–35 seconds in the first chapter.

### Manual calibration

To check accuracy for a specific book, listen to the audio around the first few paragraph boundaries and note the actual start times. For example:

```
"Day 1,299 of My Captivity"    → actually starts at ~29s   (generated: 29.4s ✓)
"darkness suits me"            → actually starts at ~35s   (generated: 37.0s, ~2s late)
"Each evening, I await..."     → actually starts at ~39s   (generated: 38.4s, ~0.6s early)
```

Errors within ±2–3 seconds are expected and acceptable for read-along synchronization. Larger errors (>5s) suggest the ABS chapter data is coarse (few chapters covering many EPUB chapters), which reduces the effectiveness of rescaling.

---

## Re-running After Failure

Each test run creates a new `AlignmentJob` row. Failed jobs are never modified. Simply re-run the script — if audio is already cached and the ABS timestamp hasn't changed, the download stage is skipped and the pipeline picks up from scratch (it does not resume mid-pipeline).

To reset everything:

```bash
rm -rf .cache/earmark/<item-id>/
uv run python testing/test_alignment.py --item-id <id> --ebook-file /path/to/book.epub
```
