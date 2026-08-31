# -*- coding: utf-8 -*-
"""Sync official source URLs and real retrieved_at into both rule CSVs."""

import csv
import hashlib
from pathlib import Path

ROOT = Path.cwd()
BASE = ROOT / "data/manual/stage8/limit_rules"
CSV_FILES = [BASE / "authoritative_limit_rules.csv", BASE / "limit_rules.csv"]

SOURCE_META = {
    "sources/szse_trading_rules_2023.pdf": {
        "source_reference": "https://docs.static.szse.cn/www/lawrules/rule/repeal/rules/W020230217564423808793.pdf",
        "retrieved_at": "2026-08-06T11:07:03+08:00",
        "note_tokens": ["精确官方附件URL待补录", "待人工复核确认"],
        "note_append": "官方附件URL已于2026-08-06重新下载核验；已登记URL曾返回404，改用官方页面附件URL",
    },
    "sources/szse_trading_rules_2026.pdf": {
        "source_reference": "https://docs.static.szse.cn/www/lawrules/rule/allrules/bussiness/W020260424690713155663.pdf",
        "retrieved_at": "2026-08-06T11:07:03+08:00",
        "note_tokens": ["精确官方附件URL待补录"],
        "note_append": "官方附件URL已于2026-08-06重新下载核验",
    },
    "sources/sse_trading_rules_2023.docx": {
        "source_reference": "https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/10824490/files/dcbe58edb194451d93f19b1f7dd8fb4c.docx",
        "retrieved_at": "2026-08-06T11:07:01+08:00",
        "note_tokens": ["精确官方附件URL待补录"],
        "note_append": "官方附件URL已于2026-08-06重新下载核验",
    },
    "sources/sse_trading_rules_2026.docx": {
        "source_reference": "https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/10816492/files/704204728fe74fff89de4f16efda4791.docx",
        "retrieved_at": "2026-08-06T11:07:02+08:00",
        "note_tokens": ["精确官方附件URL待补录"],
        "note_append": "官方附件URL已于2026-08-06重新下载核验",
    },
}


def clean_notes(notes: str, raw_file: str) -> str:
    meta = SOURCE_META[raw_file]
    cleaned = notes
    for token in meta["note_tokens"]:
        cleaned = cleaned.replace(token, "").replace("；；", "；").strip("； ")
    cleaned = cleaned.rstrip("； ")
    if meta["note_append"] not in cleaned:
        cleaned = (cleaned + "；" + meta["note_append"]).strip("； ")
    return cleaned


def main() -> None:
    rows = []
    with CSV_FILES[0].open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = list(reader.fieldnames or [])
    for row in rows:
        raw = row["raw_file"]
        meta = SOURCE_META[raw]
        row["source_reference"] = meta["source_reference"]
        row["retrieved_at"] = meta["retrieved_at"]
        row["notes"] = clean_notes(row["notes"], raw)
    for path in CSV_FILES:
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    digests = [hashlib.sha256(path.read_bytes()).hexdigest() for path in CSV_FILES]
    print("identical:", digests[0] == digests[1])
    print("row_count:", len(rows))


if __name__ == "__main__":
    main()
