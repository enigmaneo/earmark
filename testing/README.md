# testing/

Integration tests and manual testing tools for the earmark pipeline.

## Contents

- [`test_alignment.py`](#test_alignmentpy) — End-to-end alignment pipeline test script
- [`bruno/`](#bruno-collection) — Bruno HTTP collection for REST API testing

---

## test_alignment.py

Runs a complete alignment against a real Audiobookshelf server using a local EPUB file.
Prints real-time stage progress and a sync map preview on completion.

### Prerequisites

**1. Python environment**

```bash
uv sync
```

**2. System dependencies**

aeneas requires `ffmpeg` and `espeak` (or `espeak-ng`):

```bash
# macOS
brew install ffmpeg espeak

# Debian / Ubuntu
sudo apt-get install ffmpeg espeak
```

**3. aeneas**

aeneas is not in `pyproject.toml` due to its C extension build requirements.
Install it separately into the project's virtualenv:

```bash
uv run pip install aeneas
```

If the install fails, follow the [aeneas installation guide](https://github.com/readbeyond/aeneas#installation).

**4. `.env` configured**

Copy `.env.example` to `.env` and set at minimum:

```
AUDIOBOOKSHELF_URL=http://your-abs-server:13378
AUDIOBOOKSHELF_API_KEY=your_api_key_here
```

The API key is a Bearer token from your ABS user profile (Settings → Users → your user → API Token).

**5. ABS server accessible**

The script downloads all audio files for the item, which can be hundreds of MB.
Ensure the server is reachable and you have a reasonably fast connection.

### Finding an ABS item ID

Item IDs look like `li_abc123abc123abc123abc1`. To find one:

- Open your ABS web UI and navigate to the audiobook. The item ID is in the URL:
  ```
  http://your-abs/item/li_abc123abc123abc123abc1
  ```
- Or query the API directly:
  ```bash
  curl -H "Authorization: Bearer $AUDIOBOOKSHELF_API_KEY" \
    "$AUDIOBOOKSHELF_URL/api/libraries" | jq '.[0].id'
  # then
  curl -H "Authorization: Bearer $AUDIOBOOKSHELF_API_KEY" \
    "$AUDIOBOOKSHELF_URL/api/libraries/<lib_id>/items" | jq '.results[].id'
  ```

### Running the test

```bash
uv run python testing/test_alignment.py \
  --item-id li_abc123abc123abc123abc1 \
  --ebook-file /path/to/book.epub
```

Both flags are required. The local EPUB bypasses the `ebook_source` config setting —
you do not need to configure `EBOOK_SOURCE` or attach the ebook to the ABS item.

### Sample output

```
Initializing database...
Created alignment job #42 for item 'li_abc123abc123abc123abc1'
EPUB: /Users/me/books/my-book.epub

Pipeline progress:
  [14:02:01] Pending
  [14:02:03] Fetching audio files from ABS
  [14:05:17] Fetching ebook
  [14:05:19] Parsing EPUB and extracting paragraphs
             Paragraphs extracted: 3,847
  [14:05:21] Running aeneas forced alignment
  [14:47:33] Assembling sync map
             Fragments aligned:    3,847
  [14:47:34] Complete

Completed in 45m 33s

Job statistics:
  Paragraphs : 3,847
  Fragments  : 3,847
  Duration   : 45m 33s
  Sync map   : .cache/earmark/li_abc123/sync_map.json

Sync map preview (first 10 entries):
  ID         Start      End        EPUB position                          Text preview
  ---------------------------------------------------------------------------------------------------------------
  para_001   0.00s      5.21s      /body/DocFragment[1]/body/p[1]         It was the best of times, it was the…
  para_002   5.21s      12.10s     /body/DocFragment[1]/body/p[2]         it was the worst of times, it was the…
  ...
```

### Interpreting the output

**Stage timestamps** — The wall-clock time at each status transition. The gap at
`Fetching audio files` reflects download time (can be minutes for large books).
The gap at `Running aeneas forced alignment` is the alignment itself — expect
10–60 minutes depending on book length and hardware.

**Paragraph / fragment mismatch** — A non-fatal warning printed when the counts
differ. The sync map is truncated to `min(paragraphs, fragments)` entries.
Mismatches typically indicate front matter, images, or non-paragraph text blocks
in the EPUB that aeneas skipped.

**Exit code** — `0` on success, `1` on failure. On failure, the error message is
printed to stderr. Check `AlignmentJob.error_message` in the DB for the full
stack trace.

**Sync map location** — Stored at `.cache/earmark/{item_id}/sync_map.json`
(or wherever `ALIGNMENT_CACHE_DIR` points). Audio files are cached in the same
directory, so re-running the same item ID after an ABS update will skip the audio
download step if the item hasn't changed.

---

## Bruno collection

A [Bruno](https://www.usebruno.com/) HTTP collection for manually testing the
earmark REST API. Open the `testing/` folder as a Bruno collection.

### Environment setup

Edit `bruno/environments/local.bru`:

- `base_url` — earmark API URL (default: `http://localhost:8000`)
- `jwt_token` — obtain by running **auth / login**, then copy the token here
- `abs_item_id` — the ABS item ID to use in alignment requests

### Available requests

| Folder | Requests |
|--------|----------|
| `alignment/` | Create job, list jobs, get job, get sync map |
| `auth/` | Register, login |
| `users/` | User management |
| `syncs/` | Trigger sync, get sync status |
| `web/` | Web session endpoints |
| `healthcheck.bru` | `GET /health` |
