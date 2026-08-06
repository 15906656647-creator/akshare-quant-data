"""Offline manual authoritative dataset import for Stage 8.

Two auditable data contracts are supported:

- ``authoritative_limit_rules`` (``data/manual/stage8/limit_rules``)
- ``authoritative_security_status_history``
  (``data/manual/stage8/security_status``)

Each dataset directory contains a ``dataset.yml`` manifest (source registry,
review status and coverage window) plus a records CSV.  Validation is fully
offline and fail-closed: format, fields, source grade, SHA-256, intervals,
conflicts and coverage must all pass before any output may be published.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .config import load_universe
from .limit_rules import (
    LimitRule,
    SecurityStatus,
    REVIEW_MODES,
    WAIVER_DOCUMENT,
    resolve_limit_rule,
    resolve_security_status,
    validate_rule_intervals,
    validate_status_intervals,
)
from .paths import project_root


DATASET_MANIFEST_FILE = "dataset.yml"
RULES_DATASET_NAME = "authoritative_limit_rules"
STATUS_DATASET_NAME = "authoritative_security_status_history"
RULES_RECORD_FILE = "limit_rules.csv"
STATUS_RECORD_FILE = "security_status_history.csv"
SOURCE_DIR = "sources"

EXCHANGES = {"SH", "SZ", "BJ"}
BOARDS = {"main", "growth", "star", "bse"}
RULE_TYPES = {"price_limit", "st_price_limit", "ipo_first_day", "no_limit"}
ST_STATUS_VALUES = {"NON_ST", "ST", "*ST", "OTHER"}
LISTING_STATUS_VALUES = {"LISTED", "SUSPENDED", "DELISTED"}
REVIEW_STATUSES = {
    "approved", "rejected", "pending", "approved_with_waiver"
}
GRADES = {"A", "B", "C"}
WAIVER_FIELDS = (
    "review_mode",
    "waiver_reason",
    "waiver_approver",
    "waiver_at",
    "waiver_document",
)

REQUIRED_MANIFEST_KEYS = {
    "dataset_name",
    "dataset_version",
    "schema_version",
    "generated_at",
    "as_of_date",
    "coverage_start",
    "coverage_end",
    "review_status",
    "reviewed_at",
    "sources",
}

RULES_REQUIRED_COLUMNS = [
    "market", "exchange", "board", "security_type", "rule_type",
    "limit_ratio", "effective_from", "effective_to", "source_name",
    "source_document_id", "source_document_date", "source_reference",
    "retrieved_at", "raw_file", "source_sha256", "review_status",
    "notes",
]
RULES_OPTIONAL_COLUMNS = [
    "record_id", "symbol", "limit_down_ratio", "tick_size",
    "price_precision", "rounding_rule", "rule_version", "verified_at",
    "reviewer", "review_mode", "waiver_reason", "waiver_approver", "waiver_at",
    "waiver_document",
]

STATUS_REQUIRED_COLUMNS = [
    "symbol", "exchange", "board", "status_type", "status_value",
    "effective_from", "effective_to", "announcement_date", "source_name",
    "source_document_id", "source_reference", "retrieved_at", "raw_file",
    "source_sha256", "review_status", "notes",
]
STATUS_OPTIONAL_COLUMNS = [
    "record_id", "listing_date", "delisting_date", "status_version",
    "reviewer", "review_mode", "waiver_reason", "waiver_approver", "waiver_at",
    "waiver_document",
]

FORMER_NAME_INFERENCE_TOKENS = (
    "stock_info_change_name",
    "sina_former_name",
    "新浪曾用名",
    "曾用名列表",
)

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _empty_result(*, kind: str, run_id: str, status: str) -> dict[str, Any]:
    return {
        "dataset": (
            RULES_DATASET_NAME if kind == "rules" else STATUS_DATASET_NAME
        ),
        "kind": kind,
        "run_id": run_id,
        "valid": False,
        "status": status,
        "manifest": None,
        "records": [],
        "record_count": 0,
        "verified_record_count": 0,
        "stages": [],
        "errors": [],
        "warnings": [],
        "source_files": [],
        "source_hashes": {},
        "date_coverage": {"start": "", "end": ""},
        "review_status": "",
        "review_mode": "",
        "verified_by_dual_review": False,
        "waiver_reason": "",
        "waiver_approver": "",
        "waiver_at": "",
        "waiver_document": "",
        "dataset_version": "",
    }


def _parse_date(value: str, field: str) -> date | None:
    if not value:
        return None
    if not DATE_RE.match(value):
        raise ValueError(f"{field} must be ISO date YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid date") from exc


def _parse_datetime(value: str, field: str) -> None:
    if not value:
        raise ValueError(f"{field} must not be empty")
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO datetime") from exc


def _parse_aware_datetime(value: str, field: str) -> None:
    if not value:
        raise ValueError(f"{field} must not be empty")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            f"{field} must be an ISO datetime with timezone"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone offset")


def _validate_waiver_fields(
    *,
    review_status: str,
    review_mode: str,
    waiver_reason: str,
    waiver_approver: str,
    waiver_at: str,
    waiver_document: str,
    prefix: str,
    errors: list[str],
) -> None:
    if review_status == "approved":
        if review_mode and review_mode != "dual_review":
            errors.append(f"{prefix}.review_mode_must_be_dual_review:{review_mode}")
        return
    if review_status != "approved_with_waiver":
        return
    if review_mode != "waiver":
        errors.append(f"{prefix}.review_mode_must_be_waiver:{review_mode}")
    for field, value in (
        ("waiver_reason", waiver_reason),
        ("waiver_approver", waiver_approver),
        ("waiver_at", waiver_at),
        ("waiver_document", waiver_document),
    ):
        if not value:
            errors.append(f"{prefix}.{field}_required")
    if waiver_document and waiver_document != WAIVER_DOCUMENT:
        errors.append(
            f"{prefix}.waiver_document_must_be:{WAIVER_DOCUMENT}"
        )
    if waiver_document == WAIVER_DOCUMENT and not (
        project_root() / WAIVER_DOCUMENT
    ).is_file():
        errors.append(f"{prefix}.waiver_document_missing:{WAIVER_DOCUMENT}")
    if waiver_at:
        try:
            _parse_aware_datetime(waiver_at, f"{prefix}.waiver_at")
        except ValueError as exc:
            errors.append(str(exc))


def _row_label(row: dict[str, str], index: int) -> str:
    record_id = str(row.get("record_id") or "").strip()
    return f"row{index + 1}:{record_id}" if record_id else f"row{index + 1}"


def _default_window(as_of_date: date) -> tuple[date, date]:
    root = project_root()
    metrics = yaml.safe_load(
        (root / "config/metric_definition.yml").read_text(encoding="utf-8")
    )
    days = int(
        metrics["data_ranges"]["limit_event"]["lookback_natural_days"]
    )
    return as_of_date - timedelta(days=days), as_of_date


def _date_range(start: date, end: date) -> list[date]:
    days = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _read_records(path: Path, errors: list[str]) -> pd.DataFrame | None:
    if not path.is_file():
        errors.append(f"records_file_missing:{path.name}")
        return None
    last: Exception | None = None
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            frame = pd.read_csv(
                path,
                dtype=str,
                keep_default_na=False,
                encoding=encoding,
            )
            frame.columns = [str(column) for column in frame.columns]
            return frame
        except (UnicodeDecodeError, pd.errors.ParserError, OSError,
                ValueError) as exc:
            last = exc
    errors.append(
        f"records_csv_unreadable:{type(last).__name__}:{last}"
    )
    return None


def _load_manifest(
    path: Path, errors: list[str]
) -> dict[str, Any] | None:
    if not path.is_file():
        errors.append(f"dataset_manifest_missing:{path.name}")
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        errors.append(f"dataset_manifest_unreadable:{type(exc).__name__}:{exc}")
        return None
    if not isinstance(payload, dict):
        errors.append("dataset_manifest_root_not_mapping")
        return None
    return payload


def _validate_manifest(
    payload: dict[str, Any],
    *,
    kind: str,
    dataset_dir: Path,
    as_of_date: date,
    coverage_start: date,
    coverage_end: date,
    errors: list[str],
) -> None:
    missing = sorted(REQUIRED_MANIFEST_KEYS.difference(payload))
    if missing:
        errors.append(f"dataset_manifest_missing_keys:{missing}")
        return
    expected_name = (
        RULES_DATASET_NAME if kind == "rules" else STATUS_DATASET_NAME
    )
    if payload["dataset_name"] != expected_name:
        errors.append(
            f"dataset_name_mismatch:{payload['dataset_name']}!=expected:{expected_name}"
        )
    for key in (
        "dataset_version", "schema_version", "generated_at", "as_of_date",
        "coverage_start", "coverage_end", "review_status", "reviewed_at",
    ):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"dataset_manifest.{key}_required")
    review_status = str(payload.get("review_status") or "").strip()
    review_mode = str(payload.get("review_mode") or "").strip()
    if review_status not in REVIEW_STATUSES:
        errors.append(
            f"dataset_manifest_review_status_invalid:{review_status}"
        )
    elif review_status == "approved":
        reviewer = str(payload.get("reviewer") or "").strip()
        if not reviewer:
            errors.append("dataset_manifest.reviewer_required")
        _validate_waiver_fields(
            review_status=review_status,
            review_mode=review_mode,
            waiver_reason=str(payload.get("waiver_reason") or "").strip(),
            waiver_approver=str(payload.get("waiver_approver") or "").strip(),
            waiver_at=str(payload.get("waiver_at") or "").strip(),
            waiver_document=str(payload.get("waiver_document") or "").strip(),
            prefix="dataset_manifest",
            errors=errors,
        )
    elif review_status == "approved_with_waiver":
        _validate_waiver_fields(
            review_status=review_status,
            review_mode=review_mode,
            waiver_reason=str(payload.get("waiver_reason") or "").strip(),
            waiver_approver=str(payload.get("waiver_approver") or "").strip(),
            waiver_at=str(payload.get("waiver_at") or "").strip(),
            waiver_document=str(payload.get("waiver_document") or "").strip(),
            prefix="dataset_manifest",
            errors=errors,
        )
    else:
        errors.append("dataset_manifest_review_not_approved")
    if payload.get("as_of_date") != as_of_date.isoformat():
        errors.append(
            f"dataset_as_of_date_mismatch:{payload.get('as_of_date')}!=expected:{as_of_date.isoformat()}"
        )
    manifest_start = payload.get("coverage_start")
    manifest_end = payload.get("coverage_end")
    try:
        parsed_start = _parse_date(str(manifest_start or ""), "coverage_start")
        parsed_end = _parse_date(str(manifest_end or ""), "coverage_end")
    except ValueError as exc:
        errors.append(str(exc))
        parsed_start = parsed_end = None
    if parsed_start is not None and parsed_end is not None:
        if parsed_start > parsed_end:
            errors.append("dataset_manifest_coverage_inverted")
        if parsed_start > coverage_start or parsed_end < coverage_end:
            errors.append(
                "dataset_coverage_does_not_cover_analysis_window:"
                f"{parsed_start}..{parsed_end}!=required:{coverage_start}..{coverage_end}"
            )
    sources = payload.get("sources")
    if not isinstance(sources, list) or not sources:
        errors.append("dataset_manifest_sources_required")
        return
    seen_files: set[str] = set()
    for index, source in enumerate(sources):
        prefix = f"dataset_manifest.sources[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{prefix}_not_mapping")
            continue
        for key in (
            "file", "document_id", "document_date", "source_name",
            "reference", "retrieved_at", "grade", "sha256",
        ):
            value = source.get(key)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}.{key}_required")
        grade = source.get("grade")
        if grade not in GRADES:
            errors.append(f"{prefix}.grade_invalid:{grade}")
        elif grade != "A":
            errors.append(f"{prefix}.grade_not_authoritative:{grade}")
        digest = str(source.get("sha256") or "").lower()
        if digest and not SHA256_RE.match(digest):
            errors.append(f"{prefix}.sha256_invalid")
        raw_file = source.get("file")
        if isinstance(raw_file, str) and raw_file:
            if raw_file in seen_files:
                errors.append(f"{prefix}.duplicate_source_file:{raw_file}")
            seen_files.add(raw_file)
            if not _safe_source_path(dataset_dir, raw_file):
                errors.append(f"{prefix}.unsafe_source_path:{raw_file}")
        try:
            _parse_date(str(source.get("document_date") or ""), f"{prefix}.document_date")
            _parse_datetime(
                str(source.get("retrieved_at") or ""), f"{prefix}.retrieved_at"
            )
        except ValueError as exc:
            errors.append(str(exc))


def _safe_source_path(dataset_dir: Path, raw_file: str) -> bool:
    candidate = Path(raw_file)
    parts = candidate.parts
    return (
        bool(parts)
        and parts[0] == SOURCE_DIR
        and ".." not in parts
        and not candidate.is_absolute()
    )


def _registry(dataset_dir: Path, manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for source in manifest.get("sources", []):
        if not isinstance(source, dict):
            continue
        raw_file = source.get("file")
        if isinstance(raw_file, str) and raw_file:
            result[raw_file] = {
                "sha256": str(source.get("sha256") or "").lower(),
                "grade": str(source.get("grade") or ""),
            }
    return result


def _validate_columns(
    frame: pd.DataFrame,
    *,
    required: list[str],
    optional: list[str],
    errors: list[str],
) -> None:
    allowed = set(required).union(optional)
    actual = list(frame.columns)
    missing = [column for column in required if column not in actual]
    unknown = sorted(set(actual).difference(allowed))
    if missing:
        errors.append(f"records_csv_missing_columns:{missing}")
    if unknown:
        errors.append(f"records_csv_unknown_columns:{unknown}")


def _validate_rule_fields(
    rows: list[dict[str, str]],
    *,
    as_of_date: date,
    errors: list[str],
) -> None:
    for index, row in enumerate(rows):
        label = _row_label(row, index)
        market = str(row.get("market") or "").strip()
        exchange = str(row.get("exchange") or "").strip()
        board = str(row.get("board") or "").strip()
        security_type = str(row.get("security_type") or "").strip()
        rule_type = str(row.get("rule_type") or "").strip()
        ratio_text = str(row.get("limit_ratio") or "").strip()
        down_text = str(row.get("limit_down_ratio") or "").strip()
        review_status = str(row.get("review_status") or "").strip()
        reviewer = str(row.get("reviewer") or "").strip()
        review_mode = str(row.get("review_mode") or "").strip()
        waiver_reason = str(row.get("waiver_reason") or "").strip()
        waiver_approver = str(row.get("waiver_approver") or "").strip()
        waiver_at = str(row.get("waiver_at") or "").strip()
        waiver_document = str(row.get("waiver_document") or "").strip()
        symbol = str(row.get("symbol") or "").strip()
        if market not in EXCHANGES:
            errors.append(f"{label}.market_invalid:{market}")
        if exchange not in EXCHANGES:
            errors.append(f"{label}.exchange_invalid:{exchange}")
        elif market and market != exchange:
            errors.append(f"{label}.market_exchange_mismatch")
        if board not in BOARDS:
            errors.append(f"{label}.board_invalid:{board}")
        if not re.fullmatch(r"[A-Z0-9_]+", security_type):
            errors.append(f"{label}.security_type_invalid:{security_type}")
        if rule_type not in RULE_TYPES:
            errors.append(f"{label}.rule_type_invalid:{rule_type}")
        if rule_type == "no_limit" and ratio_text:
            errors.append(f"{label}.no_limit_ratio_forbidden")
        if rule_type in {"price_limit", "st_price_limit", "ipo_first_day"}:
            if not ratio_text:
                errors.append(f"{label}.limit_ratio_required")
            else:
                try:
                    ratio = Decimal(ratio_text)
                    if not Decimal("0") < ratio < Decimal("1"):
                        errors.append(f"{label}.limit_ratio_out_of_range")
                except InvalidOperation:
                    errors.append(f"{label}.limit_ratio_invalid")
            if down_text:
                try:
                    down = Decimal(down_text)
                    if not Decimal("0") < down < Decimal("1"):
                        errors.append(f"{label}.limit_down_ratio_out_of_range")
                except InvalidOperation:
                    errors.append(f"{label}.limit_down_ratio_invalid")
        if rule_type == "ipo_first_day" and not symbol:
            errors.append(f"{label}.ipo_rule_requires_symbol")
        if symbol and (len(symbol) != 6 or not symbol.isdigit()):
            errors.append(f"{label}.symbol_invalid:{symbol}")
        for field in (
            "effective_from", "source_name",
            "source_document_id", "source_document_date", "source_reference",
            "retrieved_at", "raw_file", "source_sha256",
        ):
            if not str(row.get(field) or "").strip():
                errors.append(f"{label}.{field}_required")
        if review_status not in REVIEW_STATUSES:
            errors.append(f"{label}.review_status_invalid:{review_status}")
        elif review_status in {"approved", "approved_with_waiver"}:
            _validate_waiver_fields(
                review_status=review_status,
                review_mode=review_mode,
                waiver_reason=waiver_reason,
                waiver_approver=waiver_approver,
                waiver_at=waiver_at,
                waiver_document=waiver_document,
                prefix=label,
                errors=errors,
            )
            if review_status == "approved" and not reviewer:
                errors.append(f"{label}.reviewer_required")
        else:
            errors.append(f"{label}.review_not_approved")
        try:
            start = _parse_date(
                str(row.get("effective_from") or ""), f"{label}.effective_from"
            )
            end = _parse_date(
                str(row.get("effective_to") or ""), f"{label}.effective_to"
            )
            _parse_date(
                str(row.get("source_document_date") or ""),
                f"{label}.source_document_date",
            )
            _parse_datetime(
                str(row.get("retrieved_at") or ""), f"{label}.retrieved_at"
            )
        except ValueError as exc:
            errors.append(str(exc))
            start = end = None
        if start is not None and end is not None and start > end:
            errors.append(f"{label}.effective_interval_inverted")
        digest = str(row.get("source_sha256") or "").lower()
        if digest and not SHA256_RE.match(digest):
            errors.append(f"{label}.source_sha256_invalid")
        if not _safe_source_path(Path("."), str(row.get("raw_file") or "")):
            errors.append(f"{label}.unsafe_raw_file")


def _validate_status_fields(
    rows: list[dict[str, str]],
    *,
    as_of_date: date,
    errors: list[str],
) -> None:
    for index, row in enumerate(rows):
        label = _row_label(row, index)
        symbol = str(row.get("symbol") or "").strip()
        exchange = str(row.get("exchange") or "").strip()
        board = str(row.get("board") or "").strip()
        status_type = str(row.get("status_type") or "").strip()
        status_value = str(row.get("status_value") or "").strip()
        review_status = str(row.get("review_status") or "").strip()
        reviewer = str(row.get("reviewer") or "").strip()
        review_mode = str(row.get("review_mode") or "").strip()
        waiver_reason = str(row.get("waiver_reason") or "").strip()
        waiver_approver = str(row.get("waiver_approver") or "").strip()
        waiver_at = str(row.get("waiver_at") or "").strip()
        waiver_document = str(row.get("waiver_document") or "").strip()
        if len(symbol) != 6 or not symbol.isdigit():
            errors.append(f"{label}.symbol_invalid:{symbol}")
        if exchange not in EXCHANGES:
            errors.append(f"{label}.exchange_invalid:{exchange}")
        if board not in BOARDS:
            errors.append(f"{label}.board_invalid:{board}")
        if status_type not in {"ST", "LISTING"}:
            errors.append(f"{label}.status_type_invalid:{status_type}")
        else:
            allowed = (
                ST_STATUS_VALUES
                if status_type == "ST"
                else LISTING_STATUS_VALUES
            )
            if status_value not in allowed:
                errors.append(
                    f"{label}.status_value_invalid:{status_value}"
                )
        for field in (
            "effective_from", "announcement_date",
            "source_name", "source_document_id", "source_reference",
            "retrieved_at", "raw_file", "source_sha256",
        ):
            if not str(row.get(field) or "").strip():
                errors.append(f"{label}.{field}_required")
        if review_status not in REVIEW_STATUSES:
            errors.append(f"{label}.review_status_invalid:{review_status}")
        elif review_status in {"approved", "approved_with_waiver"}:
            _validate_waiver_fields(
                review_status=review_status,
                review_mode=review_mode,
                waiver_reason=waiver_reason,
                waiver_approver=waiver_approver,
                waiver_at=waiver_at,
                waiver_document=waiver_document,
                prefix=label,
                errors=errors,
            )
            if review_status == "approved" and not reviewer:
                errors.append(f"{label}.reviewer_required")
        else:
            errors.append(f"{label}.review_not_approved")
        try:
            start = _parse_date(
                str(row.get("effective_from") or ""), f"{label}.effective_from"
            )
            end = _parse_date(
                str(row.get("effective_to") or ""), f"{label}.effective_to"
            )
            announcement = _parse_date(
                str(row.get("announcement_date") or ""),
                f"{label}.announcement_date",
            )
            _parse_datetime(
                str(row.get("retrieved_at") or ""), f"{label}.retrieved_at"
            )
        except ValueError as exc:
            errors.append(str(exc))
            start = end = announcement = None
        if start is not None and end is not None and start > end:
            errors.append(f"{label}.effective_interval_inverted")
        if announcement is not None and announcement > as_of_date:
            errors.append(
                f"{label}.announcement_after_as_of_date:"
                f"{announcement.isoformat()}>:{as_of_date.isoformat()}"
            )
        digest = str(row.get("source_sha256") or "").lower()
        if digest and not SHA256_RE.match(digest):
            errors.append(f"{label}.source_sha256_invalid")
        if not _safe_source_path(
            Path("."),
            str(row.get("raw_file") or ""),
        ):
            errors.append(f"{label}.unsafe_raw_file")


def _validate_source_registry(
    *,
    rows: list[dict[str, str]],
    registry: dict[str, dict[str, str]],
    errors: list[str],
) -> None:
    for index, row in enumerate(rows):
        label = _row_label(row, index)
        raw_file = str(row.get("raw_file") or "").strip()
        if raw_file not in registry:
            errors.append(f"{label}.raw_file_not_registered:{raw_file}")
            continue
        entry = registry[raw_file]
        if entry["grade"] != "A":
            errors.append(
                f"{label}.source_grade_not_authoritative:{raw_file}:{entry['grade']}"
            )
        combined = " ".join(
            str(row.get(field) or "")
            for field in (
                "source_name", "source_document_id", "source_reference",
                "notes",
            )
        ).lower()
        if any(token.lower() in combined for token in FORMER_NAME_INFERENCE_TOKENS):
            errors.append(
                f"{label}.former_name_inference_not_authoritative:{raw_file}"
            )


def _validate_hashes(
    *,
    dataset_dir: Path,
    rows: list[dict[str, str]],
    registry: dict[str, dict[str, str]],
    errors: list[str],
) -> None:
    for raw_file, entry in sorted(registry.items()):
        path = dataset_dir / raw_file
        if not path.is_file():
            errors.append(f"source_file_missing:{raw_file}")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != entry["sha256"]:
            errors.append(
                f"source_sha256_mismatch:{raw_file}:expected={entry['sha256']}"
            )
    for index, row in enumerate(rows):
        label = _row_label(row, index)
        raw_file = str(row.get("raw_file") or "").strip()
        expected = str(row.get("source_sha256") or "").lower()
        entry = registry.get(raw_file)
        if entry is None:
            continue
        if entry["sha256"] != expected:
            errors.append(
                f"{label}.record_hash_mismatch:{raw_file}:"
                f"record={expected}:registry={entry['sha256']}"
            )


def _internal_rules(rows: list[dict[str, str]], manifest: dict[str, Any]) -> list[LimitRule]:
    return [
        LimitRule(
            exchange=row["exchange"],
            board=row["board"],
            is_st=row["rule_type"] == "st_price_limit",
            effective_start=_parse_date(row["effective_from"], "effective_from"),
            effective_end=_parse_date(row["effective_to"], "effective_to"),
            limit_up_ratio=(
                Decimal(row["limit_ratio"])
                if row["limit_ratio"] and row["rule_type"] != "no_limit"
                else None
            ),
            limit_down_ratio=(
                Decimal(row.get("limit_down_ratio") or row["limit_ratio"])
                if (row.get("limit_down_ratio") or row["limit_ratio"])
                and row["rule_type"] != "no_limit"
                else None
            ),
            no_limit_flag=row["rule_type"] == "no_limit",
            tick_size=Decimal(row.get("tick_size") or "0.01"),
            price_precision=int(row.get("price_precision") or 2),
            rounding_rule=row.get("rounding_rule") or "half_up",
            rule_version=(
                row.get("rule_version")
                or f"{manifest['dataset_version']}-rule"
            ),
            source_reference=row["source_reference"],
            source_name=row["source_name"],
            verified_at=_parse_date(
                row.get("verified_at") or manifest["reviewed_at"],
                "verified_at",
            ),
            evidence_status=(
                "verified"
                if row["review_status"] in {"approved", "approved_with_waiver"}
                else "unverified"
            ),
            symbol=row.get("symbol") or None,
            security_type=row["security_type"],
            source_published_at=_parse_date(
                row["source_document_date"], "source_document_date"
            ),
            source_hash=row["source_sha256"],
            data_version=manifest["dataset_version"],
            record_id=row.get("record_id") or None,
            raw_file=row["raw_file"],
            source_document_id=row["source_document_id"],
            reviewer=row["reviewer"],
            notes=row.get("notes") or "",
            retrieved_at=row["retrieved_at"],
            review_status=row["review_status"],
            review_mode=row.get("review_mode") or None,
            waiver_reason=row.get("waiver_reason") or None,
            waiver_approver=row.get("waiver_approver") or None,
            waiver_at=row.get("waiver_at") or None,
            waiver_document=row.get("waiver_document") or None,
        )
        for row in rows
    ]


def _internal_statuses(
    rows: list[dict[str, str]], manifest: dict[str, Any]
) -> list[SecurityStatus]:
    result: list[SecurityStatus] = []
    for row in rows:
        status_type = row["status_type"]
        is_st = (
            row["status_value"] != "NON_ST"
            if status_type == "ST"
            else None
        )
        result.append(SecurityStatus(
            symbol=row["symbol"],
            effective_start=_parse_date(row["effective_from"], "effective_from"),
            effective_end=_parse_date(row["effective_to"], "effective_to"),
            exchange=row["exchange"],
            board=row["board"],
            is_st=is_st,
            listing_status=(
                "unresolved"
                if status_type == "ST"
                else row["status_value"].lower()
            ),
            listing_date=_parse_date(
                row.get("listing_date") or "", "listing_date"
            ),
            delisting_date=_parse_date(
                row.get("delisting_date") or "", "delisting_date"
            ),
            no_limit_reason=None,
            source_reference=row["source_reference"],
            status_version=(
                row.get("status_version")
                or f"{manifest['dataset_version']}-status"
            ),
            evidence_status=(
                "verified"
                if row["review_status"] in {"approved", "approved_with_waiver"}
                else "unverified"
            ),
            special_treatment_type=(
                None
                if status_type == "LISTING"
                else (
                    "none"
                    if row["status_value"] == "NON_ST"
                    else row["status_value"]
                )
            ),
            source_name=row["source_name"],
            source_published_at=_parse_date(
                row["announcement_date"], "announcement_date"
            ),
            source_hash=row["source_sha256"],
            data_version=manifest["dataset_version"],
            record_id=row.get("record_id") or None,
            status_type=status_type,
            status_value=row["status_value"],
            announcement_date=_parse_date(
                row["announcement_date"], "announcement_date"
            ),
            raw_file=row["raw_file"],
            source_document_id=row["source_document_id"],
            reviewer=row["reviewer"],
            notes=row.get("notes") or "",
            retrieved_at=row["retrieved_at"],
            review_status=row["review_status"],
            review_mode=row.get("review_mode") or None,
            waiver_reason=row.get("waiver_reason") or None,
            waiver_approver=row.get("waiver_approver") or None,
            waiver_at=row.get("waiver_at") or None,
            waiver_document=row.get("waiver_document") or None,
        ))
    return result


def _validate_rule_coverage(
    rules: list[LimitRule],
    *,
    coverage_start: date,
    coverage_end: date,
    errors: list[str],
) -> None:
    board_rules = [rule for rule in rules if rule.symbol is None]
    keys = sorted(
        {
            (rule.exchange, rule.board, rule.security_type or "A_SHARE")
            for rule in board_rules
        }
    )
    if not keys:
        errors.append("coverage_no_board_level_rules")
        return
    for day in _date_range(coverage_start, coverage_end):
        for exchange, board, security_type in keys:
            for rule_type, is_st in (
                ("price_limit", False),
                ("st_price_limit", True),
            ):
                matches = [
                    rule
                    for rule in board_rules
                    if rule.exchange == exchange
                    and rule.board == board
                    and (rule.security_type or "A_SHARE") == security_type
                    and rule.is_st == is_st
                    and rule.applies(day)
                ]
                if len(matches) != 1:
                    errors.append(
                        f"coverage_rules:{exchange}:{board}:{security_type}:"
                        f"{rule_type}:{day.isoformat()}:found={len(matches)}"
                    )
                    if len(errors) >= 50:
                        return


def _validate_status_coverage(
    statuses: list[SecurityStatus],
    *,
    coverage_start: date,
    coverage_end: date,
    errors: list[str],
) -> None:
    universe = load_universe()
    expected = {item.symbol: item.exchange for item in universe.stocks}
    unknown = sorted({status.symbol for status in statuses}.difference(expected))
    if unknown:
        errors.append(f"status_symbol_outside_universe:{unknown}")
    for day in _date_range(coverage_start, coverage_end):
        for symbol, exchange in sorted(expected.items()):
            for status_type in ("ST", "LISTING"):
                matches = [
                    status
                    for status in statuses
                    if status.symbol == symbol
                    and status.status_type == status_type
                    and status.applies(day)
                ]
                if len(matches) != 1:
                    errors.append(
                        f"coverage_status:{symbol}:{status_type}:"
                        f"{day.isoformat()}:found={len(matches)}"
                    )
            if len(errors) >= 50:
                return


def _stage15_sample_symbols() -> list[str]:
    root = project_root()
    path = root / "config/stage15.yml"
    if not path.is_file():
        return []
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        symbols = payload["cross_validation"]["symbols"]
    except (TypeError, KeyError):
        return []
    return [str(item).zfill(6) for item in symbols]


def _cross_validation_event_dates(
    path: Path | None,
) -> tuple[list[tuple[str, date]] | None, list[str]]:
    if path is None or not path.is_file():
        return None, []
    try:
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    except (OSError, pd.errors.ParserError, ValueError) as exc:
        return None, [
            f"cross_validation_unreadable:{type(exc).__name__}:{exc}"
        ]
    rows: list[tuple[str, date]] = []
    for record in frame.to_dict("records"):
        if (
            str(record.get("check_item") or "") != "recent_limit_up_day"
            or str(record.get("verification_status") or "") != "REVIEW"
        ):
            continue
        observed = str(record.get("observed_value") or "").strip()
        symbol = str(record.get("symbol") or "").zfill(6)
        try:
            rows.append((symbol, datetime.strptime(observed, "%Y-%m-%d").date()))
        except ValueError:
            rows.append((symbol, datetime.strptime(observed[:10], "%Y-%m-%d").date()))
    return rows, []


def _validate_combined_coverage(
    rules: list[LimitRule],
    statuses: list[SecurityStatus],
    *,
    coverage_start: date,
    coverage_end: date,
    cross_validation_csv: Path | None,
    errors: list[str],
    warnings: list[str],
) -> None:
    universe = load_universe()
    symbols = [item.symbol for item in universe.stocks]
    sample = _stage15_sample_symbols()
    for symbol in sorted(set(symbols + sample)):
        for day in _date_range(coverage_start, coverage_end):
            try:
                status = resolve_security_status(statuses, symbol, day)
                resolve_limit_rule(rules, status, day)
            except Exception as exc:  # noqa: BLE001 - fail-closed boundary
                errors.append(
                    f"coverage_combined:{symbol}:{day.isoformat()}:"
                    f"{type(exc).__name__}:{exc}"
                )
            if len(errors) >= 100:
                return
    if sample:
        warnings.append(
            "s15_14_sample_symbols_covered:"
            + ",".join(sorted(set(sample)))
        )
    event_rows, event_errors = _cross_validation_event_dates(cross_validation_csv)
    errors.extend(event_errors)
    if event_rows is None:
        warnings.append(
            "s15_14_event_dates_not_checked:cross_validation.csv_unavailable"
        )
        return
    for symbol, day in event_rows:
        try:
            status = resolve_security_status(statuses, symbol, day)
            resolve_limit_rule(rules, status, day)
        except Exception as exc:  # noqa: BLE001 - fail-closed boundary
            errors.append(
                f"coverage_event_date:{symbol}:{day.isoformat()}:"
                f"{type(exc).__name__}:{exc}"
            )
        if len(errors) >= 100:
            return


def validate_manual_dataset(
    *,
    kind: str,
    dataset_dir: Path,
    as_of_date: date,
    coverage_start: date | None = None,
    coverage_end: date | None = None,
    run_id: str,
) -> dict[str, Any]:
    """Validate one authoritative dataset through all fail-closed stages."""
    if kind not in {"rules", "status"}:
        raise ValueError("kind must be 'rules' or 'status'")
    if coverage_start is None or coverage_end is None:
        coverage_start, coverage_end = _default_window(as_of_date)
    result = _empty_result(kind=kind, run_id=run_id, status="BLOCKED")
    result["as_of_date"] = as_of_date.isoformat()
    result["coverage_start"] = coverage_start.isoformat()
    result["coverage_end"] = coverage_end.isoformat()
    dataset_dir = Path(dataset_dir)
    stages: dict[str, list[str]] = {
        "format": [],
        "fields": [],
        "source": [],
        "hash": [],
        "interval": [],
        "conflict": [],
        "coverage": [],
    }
    if not dataset_dir.is_dir():
        stages["format"].append(f"dataset_dir_missing:{dataset_dir}")
        result["stages"] = _stage_rows(stages)
        result["errors"] = sorted(
            error for errors in stages.values() for error in errors
        )
        result["status"] = "FAILED"
        return result

    manifest = _load_manifest(dataset_dir / DATASET_MANIFEST_FILE, stages["format"])
    record_file = (
        RULES_RECORD_FILE if kind == "rules" else STATUS_RECORD_FILE
    )
    frame = _read_records(dataset_dir / record_file, stages["format"])
    if manifest is not None:
        _validate_manifest(
            manifest,
            kind=kind,
            dataset_dir=dataset_dir,
            as_of_date=as_of_date,
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            errors=stages["format"],
        )
    required = (
        RULES_REQUIRED_COLUMNS if kind == "rules" else STATUS_REQUIRED_COLUMNS
    )
    optional = (
        RULES_OPTIONAL_COLUMNS if kind == "rules" else STATUS_OPTIONAL_COLUMNS
    )
    rows: list[dict[str, str]] = []
    if frame is not None:
        _validate_columns(
            frame, required=required, optional=optional, errors=stages["format"]
        )
        rows = [
            {str(key): str(value).strip() for key, value in record.items()}
            for record in frame.to_dict("records")
        ]
        seen_ids: set[str] = set()
        for index, row in enumerate(rows):
            record_id = str(row.get("record_id") or "").strip()
            if record_id:
                if record_id in seen_ids:
                    stages["format"].append(
                        f"duplicate_record_id:{record_id}"
                    )
                seen_ids.add(record_id)
    result["manifest"] = manifest
    result["records"] = rows
    result["record_count"] = len(rows)
    if not rows:
        stages["format"].append("records_csv_empty")

    if manifest is not None and rows:
        if kind == "rules":
            _validate_rule_fields(
                rows, as_of_date=as_of_date, errors=stages["fields"]
            )
        else:
            _validate_status_fields(
                rows, as_of_date=as_of_date, errors=stages["fields"]
            )
        registry = _registry(dataset_dir, manifest)
        _validate_source_registry(
            rows=rows,
            registry=registry,
            errors=stages["source"],
        )
        _validate_hashes(
            dataset_dir=dataset_dir,
            rows=rows,
            registry=registry,
            errors=stages["hash"],
        )
        if not any(stages[stage] for stage in ("fields", "format")):
            try:
                internal = (
                    _internal_rules(rows, manifest)
                    if kind == "rules"
                    else _internal_statuses(rows, manifest)
                )
                if kind == "rules":
                    validate_rule_intervals(internal)
                    _validate_rule_coverage(
                        internal,
                        coverage_start=coverage_start,
                        coverage_end=coverage_end,
                        errors=stages["coverage"],
                    )
                else:
                    validate_status_intervals(internal)
                    _validate_status_coverage(
                        internal,
                        coverage_start=coverage_start,
                        coverage_end=coverage_end,
                        errors=stages["coverage"],
                    )
            except ValueError as exc:
                stages["conflict"].append(str(exc))
        elif any(stages["fields"]):
            stages["conflict"].append(
                "conflict_checks_skipped_until_field_validation_passes"
            )
    result["stages"] = _stage_rows(stages)
    result["errors"] = sorted(
        error for errors in stages.values() for error in errors
    )
    result["valid"] = not result["errors"]
    if result["valid"] and manifest is not None:
        result["status"] = "READY"
        result["review_status"] = manifest["review_status"]
        result["review_mode"] = (
            manifest.get("review_mode")
            or (
                "dual_review"
                if manifest["review_status"] == "approved"
                else "waiver"
            )
        )
        result["verified_by_dual_review"] = (
            manifest["review_status"] == "approved"
        )
        result["waiver_reason"] = manifest.get("waiver_reason") or ""
        result["waiver_approver"] = manifest.get("waiver_approver") or ""
        result["waiver_at"] = manifest.get("waiver_at") or ""
        result["waiver_document"] = manifest.get("waiver_document") or ""
        result["dataset_version"] = manifest["dataset_version"]
        result["verified_record_count"] = len(rows)
        result["source_files"] = sorted(
            str(source.get("file"))
            for source in manifest.get("sources", [])
            if isinstance(source, dict) and source.get("file")
        )
        result["source_hashes"] = {
            str(source.get("file")): str(source.get("sha256") or "").lower()
            for source in manifest.get("sources", [])
            if isinstance(source, dict) and source.get("file")
        }
        result["date_coverage"] = {
            "start": manifest["coverage_start"],
            "end": manifest["coverage_end"],
        }
    elif any(stages["format"]):
        result["status"] = "FAILED"
    return result


def _stage_rows(stages: dict[str, list[str]]) -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "status": "FAIL" if errors else "PASS",
            "errors": sorted(set(errors)),
        }
        for name, errors in stages.items()
    ]


def validate_combined_datasets(
    *,
    rules_dir: Path,
    status_dir: Path,
    as_of_date: date,
    coverage_start: date | None = None,
    coverage_end: date | None = None,
    run_id: str,
    cross_validation_csv: Path | None = None,
) -> dict[str, Any]:
    """Validate rules and status datasets together, including cross coverage."""
    if coverage_start is None or coverage_end is None:
        coverage_start, coverage_end = _default_window(as_of_date)
    rules_result = validate_manual_dataset(
        kind="rules",
        dataset_dir=rules_dir,
        as_of_date=as_of_date,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        run_id=run_id,
    )
    status_result = validate_manual_dataset(
        kind="status",
        dataset_dir=status_dir,
        as_of_date=as_of_date,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        run_id=run_id,
    )
    errors = list(rules_result["errors"]) + list(status_result["errors"])
    warnings = list(rules_result["warnings"]) + list(status_result["warnings"])
    combined: dict[str, Any] = {
        "dataset": "authoritative_stage8_combined",
        "kind": "combined",
        "run_id": run_id,
        "as_of_date": as_of_date.isoformat(),
        "coverage_start": coverage_start.isoformat(),
        "coverage_end": coverage_end.isoformat(),
        "valid": bool(rules_result["valid"] and status_result["valid"]),
        "status": (
            "READY"
            if rules_result["valid"] and status_result["valid"]
            else (
                "FAILED"
                if "FAILED" in {rules_result["status"], status_result["status"]}
                else "BLOCKED"
            )
        ),
        "components": {
            "rules": rules_result,
            "security_status_history": status_result,
        },
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
    }
    if not combined["valid"]:
        combined["stages"] = []
        return combined
    rules = _internal_rules(rules_result["records"], rules_result["manifest"])
    statuses = _internal_statuses(
        status_result["records"], status_result["manifest"]
    )
    cross_errors: list[str] = []
    cross_warnings: list[str] = []
    _validate_combined_coverage(
        rules,
        statuses,
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        cross_validation_csv=cross_validation_csv,
        errors=cross_errors,
        warnings=cross_warnings,
    )
    combined["errors"] = sorted(set(combined["errors"] + cross_errors))
    combined["warnings"] = sorted(set(combined["warnings"] + cross_warnings))
    combined["valid"] = not combined["errors"]
    combined["status"] = "READY" if combined["valid"] else "BLOCKED"
    combined["stages"] = [
        {
            "name": "combined_coverage",
            "status": "PASS" if combined["valid"] else "FAIL",
            "errors": sorted(set(cross_errors)),
        }
    ]
    return combined


def _component_manifest(
    *, kind: str, validated: dict[str, Any]
) -> dict[str, Any]:
    manifest = validated["manifest"]
    dataset_name = (
        RULES_DATASET_NAME if kind == "rules" else STATUS_DATASET_NAME
    )
    return {
        "dataset_version": manifest["dataset_version"],
        "generated_at": manifest["generated_at"],
        "as_of_date": validated["as_of_date"],
        "source_files": validated["source_files"],
        "source_hashes": validated["source_hashes"],
        "record_counts": {
            dataset_name: validated["record_count"],
        },
        "date_coverage": {
            "start": validated["coverage_start"],
            "end": validated["coverage_end"],
        },
        "review_status": manifest["review_status"],
        "review_mode": (
            manifest.get("review_mode")
            or (
                "dual_review"
                if manifest["review_status"] == "approved"
                else "waiver"
            )
        ),
        "verified_by_dual_review": manifest["review_status"] == "approved",
        "waiver_reason": manifest.get("waiver_reason") or "",
        "waiver_approver": manifest.get("waiver_approver") or "",
        "waiver_at": manifest.get("waiver_at") or "",
        "waiver_document": manifest.get("waiver_document") or "",
        "run_id": validated["run_id"],
    }


def build_component_payload(
    *, kind: str, validated: dict[str, Any]
) -> dict[str, Any]:
    """Map validated manual records into a Stage 8 component config payload."""
    manifest = validated["manifest"]
    dataset_manifest = _component_manifest(kind=kind, validated=validated)
    if kind == "rules":
        records = [
            {
                "exchange": row["exchange"],
                "board": row["board"],
                "is_st": row["rule_type"] == "st_price_limit",
                "effective_start": row["effective_from"],
                "effective_end": row["effective_to"] or None,
                "limit_up_ratio": (
                    float(Decimal(row["limit_ratio"]))
                    if row["limit_ratio"]
                    and row["rule_type"] != "no_limit"
                    else None
                ),
                "limit_down_ratio": (
                    float(Decimal(row.get("limit_down_ratio") or row["limit_ratio"]))
                    if (row.get("limit_down_ratio") or row["limit_ratio"])
                    and row["rule_type"] != "no_limit"
                    else None
                ),
                "no_limit_flag": row["rule_type"] == "no_limit",
                "tick_size": float(Decimal(row.get("tick_size") or "0.01")),
                "price_precision": int(row.get("price_precision") or 2),
                "rounding_rule": row.get("rounding_rule") or "half_up",
                "rule_version": (
                    row.get("rule_version")
                    or f"{manifest['dataset_version']}-rule"
                ),
                "source_reference": row["source_reference"],
                "source_name": row["source_name"],
                "verified_at": (
                    row.get("verified_at") or manifest["reviewed_at"]
                ),
                "evidence_status": (
                    "verified"
                    if row["review_status"]
                    in {"approved", "approved_with_waiver"}
                    else "unverified"
                ),
                "symbol": row.get("symbol") or None,
                "security_type": row["security_type"],
                "source_published_at": row["source_document_date"],
                "source_hash": row["source_sha256"],
                "data_version": manifest["dataset_version"],
                "record_id": (
                    row.get("record_id")
                    or f"{manifest['dataset_version']}-rule-{index + 1:04d}"
                ),
                "raw_file": row["raw_file"],
                "source_document_id": row["source_document_id"],
                "reviewer": row["reviewer"],
                "notes": row.get("notes") or "",
                "retrieved_at": row["retrieved_at"],
                "review_status": row["review_status"],
                "review_mode": (
                    row.get("review_mode")
                    or (
                        "dual_review"
                        if row["review_status"] == "approved"
                        else "waiver"
                    )
                ),
                "waiver_reason": row.get("waiver_reason") or "",
                "waiver_approver": row.get("waiver_approver") or "",
                "waiver_at": row.get("waiver_at") or "",
                "waiver_document": row.get("waiver_document") or "",
            }
            for index, row in enumerate(validated["records"])
        ]
        return {
            "rule_records": records,
            "dataset_manifest": dataset_manifest,
        }
    records = []
    for index, row in enumerate(validated["records"]):
        status_type = row["status_type"]
        records.append(
            {
                "symbol": row["symbol"],
                "effective_start": row["effective_from"],
                "effective_end": row["effective_to"] or None,
                "exchange": row["exchange"],
                "board": row["board"],
                "is_st": (
                    row["status_value"] != "NON_ST"
                    if status_type == "ST"
                    else None
                ),
                "listing_status": (
                    "unresolved"
                    if status_type == "ST"
                    else row["status_value"].lower()
                ),
                "listing_date": row.get("listing_date") or None,
                "delisting_date": row.get("delisting_date") or None,
                "no_limit_reason": None,
                "source_reference": row["source_reference"],
                "status_version": (
                    row.get("status_version")
                    or f"{manifest['dataset_version']}-status"
                ),
                "evidence_status": (
                    "verified"
                    if row["review_status"]
                    in {"approved", "approved_with_waiver"}
                    else "unverified"
                ),
                "special_treatment_type": (
                    None
                    if status_type == "LISTING"
                    else (
                        "none"
                        if row["status_value"] == "NON_ST"
                        else row["status_value"]
                    )
                ),
                "source_name": row["source_name"],
                "source_published_at": row["announcement_date"],
                "source_hash": row["source_sha256"],
                "data_version": manifest["dataset_version"],
                "record_id": (
                    row.get("record_id")
                    or f"{manifest['dataset_version']}-status-{index + 1:04d}"
                ),
                "status_type": status_type,
                "status_value": row["status_value"],
                "announcement_date": row["announcement_date"],
                "raw_file": row["raw_file"],
                "source_document_id": row["source_document_id"],
                "reviewer": row["reviewer"],
                "notes": row.get("notes") or "",
                "retrieved_at": row["retrieved_at"],
                "review_status": row["review_status"],
                "review_mode": (
                    row.get("review_mode")
                    or (
                        "dual_review"
                        if row["review_status"] == "approved"
                        else "waiver"
                    )
                ),
                "waiver_reason": row.get("waiver_reason") or "",
                "waiver_approver": row.get("waiver_approver") or "",
                "waiver_at": row.get("waiver_at") or "",
                "waiver_document": row.get("waiver_document") or "",
            }
        )
    return {
        "security_status_records": records,
        "dataset_manifest": dataset_manifest,
    }


def build_merged_payload(
    *,
    rules_result: dict[str, Any],
    status_result: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    """Combine validated components into one runnable Stage 8 config."""
    rules_payload = build_component_payload(
        kind="rules", validated=rules_result
    )
    status_payload = build_component_payload(
        kind="status", validated=status_result
    )
    rules_manifest = rules_payload["dataset_manifest"]
    status_manifest = status_payload["dataset_manifest"]
    statuses = {
        rules_manifest["review_status"],
        status_manifest["review_status"],
    }
    if statuses == {"approved"}:
        merged_review_status = "approved"
    elif statuses <= {"approved", "approved_with_waiver"}:
        merged_review_status = "approved_with_waiver"
    else:
        merged_review_status = "rejected"
    waiver_source = (
        rules_manifest
        if rules_manifest["review_status"] == "approved_with_waiver"
        else status_manifest
    )
    merged_manifest = {
        "dataset_version": (
            f"{rules_manifest['dataset_version']}+"
            f"{status_manifest['dataset_version']}"
        ),
        "generated_at": max(
            rules_manifest["generated_at"], status_manifest["generated_at"]
        ),
        "as_of_date": rules_manifest["as_of_date"],
        "source_files": sorted(
            set(rules_manifest["source_files"]).union(
                status_manifest["source_files"]
            )
        ),
        "source_hashes": {
            **rules_manifest["source_hashes"],
            **status_manifest["source_hashes"],
        },
        "record_counts": {
            **rules_manifest["record_counts"],
            **status_manifest["record_counts"],
        },
        "date_coverage": {
            "start": min(
                rules_manifest["date_coverage"]["start"],
                status_manifest["date_coverage"]["start"],
            ),
            "end": max(
                rules_manifest["date_coverage"]["end"],
                status_manifest["date_coverage"]["end"],
            ),
        },
        "review_status": merged_review_status,
        "review_mode": (
            "dual_review"
            if merged_review_status == "approved"
            else "waiver"
        ),
        "verified_by_dual_review": merged_review_status == "approved",
        "waiver_reason": waiver_source.get("waiver_reason") or "",
        "waiver_approver": waiver_source.get("waiver_approver") or "",
        "waiver_at": waiver_source.get("waiver_at") or "",
        "waiver_document": waiver_source.get("waiver_document") or "",
        "run_id": run_id,
    }
    return {
        "schema_version": "1.0.0",
        "price_adjust_type": "raw",
        "rounding_rules": {"supported": ["half_up", "half_even"]},
        "formal_evidence_status": "verified",
        "formal_quality_status": "pass",
        "unresolved_policy": "block_formal_annual_statistics",
        "rule_records": rules_payload["rule_records"],
        "security_status_records": status_payload["security_status_records"],
        "source_notes": {
            "limit_pool_usage": "cross_validation_only",
            "gap_proxy_usage": "candidate_feature_only_not_formal_event",
        },
        "dataset_manifest": merged_manifest,
    }


def provenance_report(validated: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": validated["run_id"],
        "dataset": validated["dataset"],
        "as_of_date": validated["as_of_date"],
        "coverage_start": validated["coverage_start"],
        "coverage_end": validated["coverage_end"],
        "dataset_version": validated["dataset_version"],
        "review_status": validated["review_status"],
        "record_count": validated["record_count"],
        "verified_record_count": validated["verified_record_count"],
        "source_files": validated["source_files"],
        "source_hashes": validated["source_hashes"],
        "date_coverage": validated["date_coverage"],
        "reviewer": validated["manifest"]["reviewer"]
        if validated.get("manifest")
        else "",
        "review_mode": validated["review_mode"],
        "verified_by_dual_review": validated["verified_by_dual_review"],
        "waiver_reason": validated["waiver_reason"],
        "waiver_approver": validated["waiver_approver"],
        "waiver_at": validated["waiver_at"],
        "waiver_document": validated["waiver_document"],
        "reviewed_at": validated["manifest"]["reviewed_at"]
        if validated.get("manifest")
        else "",
        "generated_at": validated["manifest"]["generated_at"]
        if validated.get("manifest")
        else "",
    }
