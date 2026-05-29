import hashlib
from pathlib import Path


def safe_subpath(root: str | Path, name: str) -> Path | None:
    """Join ``name`` onto ``root`` only if the result stays inside ``root``.

    Returns the resolved path, or ``None`` if ``name`` escapes the root
    (e.g. contains ``..`` or is absolute). Use for any path built from
    user/external input before reading, writing, or deleting it.
    """
    root_resolved = Path(root).resolve()
    candidate = (root_resolved / name).resolve()
    if candidate == root_resolved or root_resolved in candidate.parents:
        return candidate
    return None


def partial_md5(path: Path) -> str:
    """Compute KOReader-compatible partial MD5 of a file.

    Mirrors KOReader's util.partialMD5: lshift(1024, 2*i) for i in -1..10.
    LuaJIT bit.lshift uses shift & 31, so i=-1 gives lshift(1024,30) which
    overflows 32 bits to 0, making the first offset 0 (not 256).
    """
    m = hashlib.md5()
    for i in range(-1, 11):
        offset = (1024 << ((2 * i) % 32)) & 0xFFFFFFFF
        with path.open("rb") as f:
            f.seek(offset)
            chunk = f.read(1024)
        if not chunk:
            break
        m.update(chunk)
    return m.hexdigest()
