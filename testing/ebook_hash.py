#!/usr/bin/env python3
"""Print the KOReader-compatible partial MD5 hash of an ebook file."""
import argparse
from pathlib import Path

from earmark.utils import partial_md5


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("epub", type=Path, help="Path to the ebook file")
    args = parser.parse_args()

    if not args.epub.exists():
        parser.error(f"File not found: {args.epub}")

    print(partial_md5(args.epub))


if __name__ == "__main__":
    main()
