"""Minimal HTML-to-text helper for SZSE official pages.

This is an audit helper only and does not modify project code or data.
"""

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
from pathlib import Path


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data.strip())

    def text(self) -> str:
        return "\n".join(self.parts)


def extract(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "gbk"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")
    parser = TextExtractor()
    parser.feed(text)
    out = parser.text()
    return re.sub(r"\n{3,}", "\n\n", out)


def main() -> None:
    for html_path in sys.argv[1:]:
        text = extract(Path(html_path))
        out = Path(html_path).with_suffix(".txt")
        out.write_text(text, encoding="utf-8")
        print(f"{html_path}: {len(text)} chars -> {out}")


if __name__ == "__main__":
    main()
