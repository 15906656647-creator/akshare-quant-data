from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(r"E:\大学\实习\嘉驰国际\AKShare 量化金融数据")
RUN_DIR = ROOT / "reports" / "stage8_security_status_source_collection" / "20260806_143005"
SOURCE_ROOT = ROOT / "data" / "manual" / "stage8" / "security_status" / "sources"

SYMBOLS = [
    "000100", "002067", "002129", "002230", "002361", "002600",
    "300274", "300433", "600231", "600438", "600763", "601012",
    "601500", "601636", "603259", "603799",
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_json_or_jsonp(path: Path) -> object:
    text = path.read_text(encoding="utf-8-sig")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        left = text.find("(")
        right = text.rfind(")")
        return json.loads(text[left + 1 : right])


results: dict[str, object] = {}
errors: list[str] = []

with (RUN_DIR / "download_manifest.csv").open(encoding="utf-8") as f:
    rows = list(csv.DictReader(f))

checked = 0
for row in rows:
    path = ROOT / row["file"]
    if not path.exists():
        errors.append(f"missing:{row['file']}")
        continue
    actual = sha256_file(path)
    if actual != row["sha256"]:
        errors.append(f"hash_mismatch:{row['file']}")
    if row["source_kind"] == "company_announcement_pdf":
        if path.read_bytes()[:5] != b"%PDF-":
            errors.append(f"not_pdf:{row['file']}")
    elif row["file"].endswith(".json"):
        try:
            parse_json_or_jsonp(path)
        except Exception as exc:
            errors.append(f"bad_json:{row['file']}:{exc}")
    checked += 1

results["download_manifest_rows"] = len(rows)
results["download_checks_passed"] = checked
results["errors"] = errors

sz_risk = parse_json_or_jsonp(SOURCE_ROOT / "SZ" / "szse_risk_warning_plate_2026-08-06.json")
sz_risk_codes = [str(item["zqdm"]) for tab in sz_risk for item in tab.get("data", [])]
sse_risk = parse_json_or_jsonp(SOURCE_ROOT / "SH" / "sse_risk_warning_plate_2026-08-06.json")
sse_risk_codes = [str(item["INSTRUMENT_ID"]) for item in sse_risk.get("result", [])]
sz_absent = [s for s in SYMBOLS if s.startswith(("0", "3")) and s not in sz_risk_codes]
sh_absent = [s for s in SYMBOLS if s.startswith("6") and s not in sse_risk_codes]
results["sz_risk_plate_absent"] = sz_absent
results["sse_risk_plate_absent"] = sh_absent
results["risk_plate_absent_all"] = len(sz_absent) == 8 and len(sh_absent) == 8

stock_list_ok = []
for symbol in SYMBOLS:
    prefix = "SZ" if symbol.startswith(("0", "3")) else "SH"
    stem = "szse" if prefix == "SZ" else "sse"
    path = SOURCE_ROOT / prefix / symbol / f"{stem}_stock_list_{symbol}_2026-08-06.json"
    try:
        data = parse_json_or_jsonp(path)
        if prefix == "SZ":
            item = data[0]["data"][0]
            ok = item["agdm"] == symbol and item.get("agssrq")
        else:
            item = data["result"][0]
            ok = item["A_STOCK_CODE"] == symbol and item.get("LIST_DATE") and item.get("DELIST_DATE") == "-"
        stock_list_ok.append({"symbol": symbol, "ok": bool(ok), "name_short": str(item.get("agjc") or item.get("SEC_NAME_CN") or "")})
    except Exception as exc:
        stock_list_ok.append({"symbol": symbol, "ok": False, "error": str(exc)})
results["stock_list_ok"] = stock_list_ok
results["stock_list_ok_count"] = sum(1 for x in stock_list_ok if x["ok"])

ann_counts: dict[str, int] = {}
for symbol in SYMBOLS:
    prefix = "SZ" if symbol.startswith(("0", "3")) else "SH"
    total = 0
    for path in sorted((SOURCE_ROOT / prefix / symbol).glob(f"*_all_p*.json")):
        data = parse_json_or_jsonp(path)
        if prefix == "SZ":
            total += len(data.get("data", []))
        else:
            for group in data.get("result", []):
                total += len(group) if isinstance(group, list) else 1
    ann_counts[symbol] = total
results["all_announcement_fetched_counts"] = ann_counts
results["all_announcement_fetched_nonzero"] = all(v > 0 for v in ann_counts.values())

(RUN_DIR / "collection_validation.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(results, ensure_ascii=False, indent=2))
