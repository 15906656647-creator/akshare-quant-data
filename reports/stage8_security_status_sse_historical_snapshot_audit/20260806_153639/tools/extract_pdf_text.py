"""Minimal PDF text extraction for official SSE documentation.

This is an audit helper only and does not modify any project code or data.
"""

from __future__ import annotations

import re
import sys
import zlib
from pathlib import Path


def iter_streams(data: bytes):
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.S):
        yield match.group(1)


def decode_stream(raw: bytes) -> bytes | None:
    if raw.startswith(b"FlateDecode") or b"FlateDecode" in raw[:128]:
        try:
            return zlib.decompress(raw)
        except zlib.error:
            return None
    return None


def extract_text(path: Path) -> str:
    data = path.read_bytes()
    chunks: list[str] = []
    for raw in iter_streams(data):
        decoded = decode_stream(raw)
        if not decoded:
            continue
        for text_match in re.finditer(
            rb"(?:\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]*>)\s*Tj|\[(?:[^\[\]]*)\]\s*TJ",
            decoded,
        ):
            token = text_match.group(0)
            parts = re.findall(rb"\((?:\\.|[^\\()])*\)|<[0-9A-Fa-f\s]*>", token)
            for part in parts:
                if part.startswith(b"<"):
                    try:
                        s = bytes.fromhex(part[1:-1].decode("ascii"))
                    except ValueError:
                        continue
                else:
                    s = part[1:-1]
                s = s.replace(rb"\(", b"(").replace(rb"\)", b")").replace(rb"\\", b"\\")
                try:
                    chunks.append(s.decode("utf-8"))
                except UnicodeDecodeError:
                    try:
                        chunks.append(s.decode("gbk"))
                    except UnicodeDecodeError:
                        chunks.append(s.decode("latin-1"))
    return "\n".join(chunks)


def main() -> None:
    for pdf_path in sys.argv[1:]:
        text = extract_text(Path(pdf_path))
        out = Path(pdf_path).with_suffix(".txt")
        out.write_text(text, encoding="utf-8")
        print(f"{pdf_path}: {len(text)} chars -> {out}")


if __name__ == "__main__":
    main()
