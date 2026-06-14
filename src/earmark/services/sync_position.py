"""Sync-map loading and ebook-position conversion/comparison.

Shared by the scheduler (sync direction decisions) and the KOSync progress
writer (forward-only guard). Positions are only ever compared positionally —
never by percentage, because ABS percentages are audio-time fractions while
KOSync percentages are KOReader pagination fractions, and the two don't match
for the same physical position.
"""

import bisect
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# In-process cache of parsed sync maps, keyed by path. Each entry stores the
# file mtime it was parsed from so a regenerated map is reloaded automatically.
_SYNC_MAP_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}


def load_sync_map(path: str) -> list[dict[str, Any]] | None:
    p = Path(path)
    if not p.exists():
        logger.error("Sync map not found: %s", path)
        _SYNC_MAP_CACHE.pop(path, None)
        return None
    try:
        mtime = p.stat().st_mtime
        cached = _SYNC_MAP_CACHE.get(path)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        entries: list[dict[str, Any]] = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load sync map %s: %s", path, exc)
        return None
    if not entries:
        logger.warning("Sync map is empty: %s", path)
        return None
    _SYNC_MAP_CACHE[path] = (mtime, entries)
    return entries


DOCFRAG_RE = re.compile(r"/body/DocFragment\[(\d+)\]")
_BRACKET_IDX_RE = re.compile(r"\[(\d+)\]")
_TEXT_NODE_TAIL_RE = re.compile(r"/text\(\)(?:\[\d+\])?(?:\.\d+)?$")
_CHAR_OFFSET_TAIL_RE = re.compile(r"\.\d+$")
_INDEX_ONE_RE = re.compile(r"\[1\]")


def normalize_xpath(xpath: str) -> str:
    """Bring a KOReader xpath and a sync_map ebook_pos into a comparable form.

    Strips: trailing /text() node selector (with optional [N] and .N),
    trailing .N char offset, and all [1] sibling indices (CRE omits the
    index when an element has no same-tag siblings; the sync map always
    emits one).
    """
    xpath = _TEXT_NODE_TAIL_RE.sub("", xpath)
    xpath = _CHAR_OFFSET_TAIL_RE.sub("", xpath)
    xpath = _INDEX_ONE_RE.sub("", xpath)
    return xpath


def kosync_to_audio(xpath: str, sync_map: list[dict[str, Any]]) -> float | None:
    frag_match = DOCFRAG_RE.search(xpath)
    if not frag_match:
        return None
    n = int(frag_match.group(1))

    candidates = [e for e in sync_map if f"DocFragment[{n}]" in e["ebook_pos"]]
    if not candidates:
        return None

    clean_xpath = normalize_xpath(xpath)

    # Try exact match first (works when both sides use hierarchical XPaths).
    for entry in candidates:
        if normalize_xpath(entry["ebook_pos"]) == clean_xpath:
            return float(entry["audio_start"])

    # Fallback: compare deepest bracketed index in the path after DocFragment[n].
    after_frag = clean_xpath.split(f"DocFragment[{n}]", 1)[-1]
    indices = _BRACKET_IDX_RE.findall(after_frag)
    m = int(indices[-1]) if indices else 1

    def _deepest_idx(entry: dict[str, Any]) -> int:
        af = entry["ebook_pos"].split(f"DocFragment[{n}]", 1)[-1]
        idxs = _BRACKET_IDX_RE.findall(af)
        return int(idxs[-1]) if idxs else 1

    best = min(candidates, key=lambda e: abs(_deepest_idx(e) - m))
    return float(best["audio_start"])


def audio_to_kosync(
    current_time: float, duration: float, sync_map: list[dict[str, Any]]
) -> tuple[str, float]:
    starts = [e["audio_start"] for e in sync_map]
    idx = bisect.bisect_right(starts, current_time) - 1
    idx = max(0, min(idx, len(sync_map) - 1))
    entry = sync_map[idx]
    percentage = current_time / duration if duration > 0 else 0.0
    return entry["ebook_pos"], percentage


def compare_positions(
    a: str, b: str, sync_map: list[dict[str, Any]] | None
) -> int | None:
    """Order two ebook positions: negative if ``a`` is before ``b``, zero if
    equal, positive if after, or ``None`` when the positions aren't comparable.

    DocFragments are document-ordered, so differing fragment indices decide
    without a sync map. Within one fragment, order is taken from the sync map's
    audio times; XPath structure alone can't order sibling tags, so without a
    map (or when either position can't be mapped) the result is ``None``.
    """
    frag_a = DOCFRAG_RE.search(a)
    frag_b = DOCFRAG_RE.search(b)
    if frag_a is None or frag_b is None:
        return None
    delta = int(frag_a.group(1)) - int(frag_b.group(1))
    if delta != 0:
        return delta
    if sync_map is None:
        return None
    audio_a = kosync_to_audio(a, sync_map)
    audio_b = kosync_to_audio(b, sync_map)
    if audio_a is None or audio_b is None:
        return None
    if audio_a == audio_b:
        return 0
    return -1 if audio_a < audio_b else 1
