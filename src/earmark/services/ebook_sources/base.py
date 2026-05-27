import re
import unicodedata
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel


class EbookCandidate(BaseModel):
    ref: str
    title: str
    author: str | None = None
    format: str = "epub"


class EbookSource(Protocol):
    async def search(self, title: str, author: str | None) -> list[EbookCandidate]:
        ...

    async def fetch(self, ref: str, dest: Path) -> None:
        ...


def normalize(value: str) -> str:
    decoded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", "", decoded.lower()).strip()
