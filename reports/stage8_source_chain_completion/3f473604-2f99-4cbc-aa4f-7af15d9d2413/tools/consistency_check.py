# -*- coding: utf-8 -*-
"""Consistency review after source-chain completion."""

import csv
import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path.cwd()
BASE = ROOT / "data/manual/stage8/limit_rules"
RUN_DIR = ROOT / "reports/stage8_source_chain_completion/3f473604-2f99-4cbc-aa4f-7af15d9d2413"
CSV_A = BASE / "authoritative_limit_rules.csv"
CSV_B = BASE / "limit_rules.csv"
ALLOWED_URL_PREFIXES = (
    "https://www.sse.com.cn/",
    "https://www.szse.cn/",
    "https://docs.static.szse.cn/",
)
COVERAGE_START = date(2025, 7, 27)
COVERAGE_END = date(2026, 7, 27)


def parse_date(value: str) -> date:
    return date.fromisoformat(value)


def main() -> None:
    errors: list[str] = []
    manifest = yaml.safe_load((BASE / "dataset.yml").read_text(encoding="utf-8"))
    registry = {
        src["file"]: src for src in manifest["sources"] if isinstance(src, dict)
    }

    digest_a = hashlib.sha256(CSV_A.read_bytes()).hexdigest()
    digest_b = hashlib.sha256(CSV_B.read_bytes()).hexdigest()
    if digest_a != digest_b:
        errors.append("csv_sha_mismatch")

    with CSV_A.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 12:
        errors.append(f"row_count={len(rows)}")
    groups: dict[tuple[str, str, str], list[dict]] = {}
    for row in rows:
        key = (row["exchange"], row["board"], row["rule_type"])
        groups.setdefault(key, []).append(row)
    if len(groups) != 6 or any(len(v) != 2 for v in groups.values()):
        errors.append(f"group_structure={ {k: len(v) for k, v in groups.items()} }")

    expected_ratios = {
        "draft-szse-main-st-2026": "0.10",
        "draft-szse-growth-st-2026": "0.20",
        "draft-sse-main-st-2026": "0.10",
    }
    for row in rows:
        rid = row["record_id"]
        if rid in expected_ratios and row["limit_ratio"] != expected_ratios[rid]:
            errors.append(f"ratio_modified:{rid}:{row['limit_ratio']}")
        if row["review_status"] != "pending":
            errors.append(f"review_status_not_pending:{rid}")
        if row["reviewer"] or row["verified_at"]:
            errors.append(f"reviewer_or_verified_at_nonempty:{rid}")
        raw = row["raw_file"]
        path = BASE / raw
        if not path.is_file():
            errors.append(f"raw_file_missing:{raw}")
        else:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != row["source_sha256"].lower():
                errors.append(f"source_sha256_mismatch:{rid}:{raw}")
        if raw not in registry:
            errors.append(f"raw_not_in_dataset_manifest:{raw}")
        else:
            source = registry[raw]
            if source.get("sha256", "").lower() != row["source_sha256"].lower():
                errors.append(f"manifest_hash_mismatch:{rid}:{raw}")
            if source.get("reference") != row["source_reference"]:
                errors.append(f"source_reference_mismatch:{rid}:{raw}")
            if source.get("retrieved_at") != row["retrieved_at"]:
                errors.append(f"retrieved_at_mismatch:{rid}:{raw}")
        if not row["retrieved_at"]:
            errors.append(f"retrieved_at_empty:{rid}")
        if "2026-08-06T00:00:00" in row["retrieved_at"]:
            errors.append(f"placeholder_retrieved_at:{rid}")
        if not row["source_reference"].startswith(ALLOWED_URL_PREFIXES):
            errors.append(f"non_official_url:{rid}:{row['source_reference']}")
        if "example.invalid" in json.dumps(row, ensure_ascii=False):
            errors.append(f"example_content:{rid}")

    for key, interval_rows in groups.items():
        ordered = sorted(interval_rows, key=lambda r: parse_date(r["effective_from"]))
        starts = [parse_date(r["effective_from"]) for r in ordered]
        ends = [parse_date(r["effective_to"]) for r in ordered]
        if starts[0] != COVERAGE_START or ends[-1] != COVERAGE_END:
            errors.append(f"coverage_boundary:{key}")
        for prev_end, next_start in zip(ends, starts[1:]):
            if prev_end >= next_start:
                errors.append(f"coverage_overlap:{key}:{prev_end}:{next_start}")
            if prev_end + timedelta(days=1) != next_start:
                errors.append(f"coverage_gap:{key}:{prev_end}:{next_start}")

    result = {
        "run_id": "3f473604-2f99-4cbc-aa4f-7af15d9d2413",
        "csv_identical": digest_a == digest_b,
        "row_count": len(rows),
        "group_count": len(groups),
        "date_coverage": "COMPLETE" if not any("coverage_" in e for e in errors) else "INCOMPLETE",
        "all_hashes_match": not any("sha256" in e or "manifest_hash" in e for e in errors),
        "all_references_official": not any("non_official_url" in e for e in errors),
        "all_retrieved_at_real": not any("retrieved_at_empty" in e or "placeholder" in e for e in errors),
        "review_status_pending": not any("review_status_not_pending" in e for e in errors),
        "reviewer_verified_at_empty": not any("reviewer_or_verified_at_nonempty" in e for e in errors),
        "rules_matrix_unchanged": not any("ratio_modified" in e for e in errors),
        "errors": sorted(set(errors)),
        "pass": not errors,
    }
    (RUN_DIR / "consistency_check.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
