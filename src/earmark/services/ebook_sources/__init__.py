from earmark.services.ebook_sources.base import EbookCandidate, EbookSource
from earmark.services.ebook_sources.calibre import CalibreOpdsSource
from earmark.services.ebook_sources.local import LocalEbookSource

__all__ = [
    "EbookCandidate",
    "EbookSource",
    "CalibreOpdsSource",
    "LocalEbookSource",
]
