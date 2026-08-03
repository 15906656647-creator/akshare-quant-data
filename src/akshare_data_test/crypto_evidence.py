"""Append-only Raw evidence contract and strict offline verification for Stage 11."""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from collections import Counter
from datetime import date, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

import pandas as pd

from .assets import CryptoIdentityContract


REQUIRED_FILES = ("request.json", "response.json", "metadata.json", "manifest.json")
REQUIRED_MANIFEST_ROLES = {
    "request": "request.json",
    "response": "response.json",
    "metadata": "metadata.json",
}
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
RAW_PROJECTION_COLUMNS = [
    "raw_instrument", "data_provider", "raw_exchange", "instrument_type",
    "bar_interval", "confirmed", "trade_time", "open", "high", "low", "close",
    "volume", "quote_volume",
]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _schema_hash(columns: list[str]) -> str:
    payload = json.dumps(columns, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _manifest_entry(role: str, path: Path) -> dict[str, Any]:
    return {
        "role": role,
        "name": path.name,
        "sha256": _sha256(path),
        "size_bytes": path.stat().st_size,
    }


def _normalize_manifest_path(value: Any) -> str:
    """Return a Windows-case-insensitive relative manifest path or fail closed."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("path must be a non-empty string")
    raw = value.strip()
    windows = PureWindowsPath(raw)
    normalized_separators = raw.replace("\\", "/")
    if windows.is_absolute() or windows.drive or PurePosixPath(normalized_separators).is_absolute():
        raise ValueError("absolute paths are forbidden")
    raw_parts = normalized_separators.split("/")
    if ".." in raw_parts:
        raise ValueError("parent traversal is forbidden")
    parts = [part for part in raw_parts if part not in {"", "."}]
    if not parts:
        raise ValueError("path is empty after normalization")
    return "/".join(parts).casefold()


def _enumerate_raw_files(evidence_dir: Path) -> tuple[list[tuple[str, str]], list[str]]:
    """Enumerate ordinary files without following symlinks or reparse points."""
    files: list[tuple[str, str]] = []
    blockers: list[str] = []
    pending = [evidence_dir]
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda item: item.name.casefold())
        except OSError as exc:
            relative = directory.relative_to(evidence_dir).as_posix() or "."
            blockers.append(f"manifest_directory_unreadable: {relative}: {exc}")
            continue
        for entry in entries:
            path = Path(entry.path)
            relative = path.relative_to(evidence_dir).as_posix()
            try:
                metadata = entry.stat(follow_symlinks=False)
            except OSError as exc:
                blockers.append(f"manifest_file_unreadable: {relative}: {exc}")
                continue
            is_reparse = bool(getattr(metadata, "st_file_attributes", 0) & reparse_flag)
            if entry.is_symlink() or is_reparse:
                blockers.append(f"manifest_reparse_point_forbidden: {relative}")
            elif stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
            elif stat.S_ISREG(metadata.st_mode):
                try:
                    files.append((relative, _normalize_manifest_path(relative)))
                except ValueError as exc:
                    blockers.append(f"manifest_actual_path_invalid: {relative}: {exc}")
            else:
                blockers.append(f"manifest_non_regular_file: {relative}")
    return files, blockers


def raw_projection_hash(frame: pd.DataFrame) -> str:
    missing = sorted(set(RAW_PROJECTION_COLUMNS).difference(frame.columns))
    if missing:
        raise ValueError(f"Raw projection fields missing: {missing}")
    data = frame[RAW_PROJECTION_COLUMNS].copy()
    data["trade_time"] = pd.to_datetime(data["trade_time"], errors="raise", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    for name in ("open", "high", "low", "close", "volume", "quote_volume"):
        numeric = pd.to_numeric(data[name], errors="raise")
        data[name] = numeric.map(lambda value: format(float(value), ".12g"))
    data["confirmed"] = data["confirmed"].astype("string").str.lower().map({"true": "true", "1": "true", "false": "false", "0": "false"})
    data = data.sort_values("trade_time", kind="mergesort")
    payload = json.dumps(data.to_dict("records"), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return _safe(value.item())
    if value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def write_raw_evidence(
    evidence_dir: Path, *, run_id: str, provider: str, endpoint: str,
    request_parameters: dict[str, Any], response: pd.DataFrame,
    identity: CryptoIdentityContract, fetched_at: pd.Timestamp,
) -> dict[str, Any]:
    """Create one immutable evidence set; existing files are never overwritten."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    occupied = [name for name in REQUIRED_FILES if (evidence_dir / name).exists()]
    if occupied:
        raise FileExistsError(f"Raw evidence is append-only; files already exist: {occupied}")
    if response.empty:
        raise ValueError("Raw response must not be empty")
    columns = [str(name) for name in response.columns]
    request_payload = {
        "provider": provider, "endpoint": endpoint,
        "parameters": _safe(request_parameters),
        "requested_instrument": identity.requested_instrument,
        "instrument_type": identity.instrument_type,
        "bar_interval": identity.bar_interval,
    }
    response_payload = _safe(response.to_dict("records"))
    metadata = {
        "run_id": run_id, "provider": provider, "endpoint": endpoint,
        "request_parameters": _safe(request_parameters),
        "requested_instrument": identity.requested_instrument,
        "raw_instrument": identity.raw_instrument,
        "instrument_type": identity.instrument_type,
        "bar_interval": identity.bar_interval,
        "fetched_at": pd.Timestamp(fetched_at).isoformat(),
        "response_row_count": len(response), "columns": columns,
        "response_schema_hash": _schema_hash(columns),
    }
    (evidence_dir / "request.json").write_text(
        json.dumps(request_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (evidence_dir / "response.json").write_text(
        json.dumps(response_payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    (evidence_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    evidence_files = [
        _manifest_entry(role, evidence_dir / name)
        for role, name in REQUIRED_MANIFEST_ROLES.items()
    ]
    manifest = {
        **metadata,
        "response_content_sha256": _sha256(evidence_dir / "response.json"),
        "evidence_files": evidence_files,
    }
    (evidence_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def write_akshare_probe_evidence(
    evidence_dir: Path, *, run_id: str, response: pd.DataFrame,
    capability: dict[str, Any], akshare_version: str, fetched_at: pd.Timestamp,
) -> dict[str, Any]:
    """Preserve the complete, unfiltered AKShare capability response."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    if any((evidence_dir / name).exists() for name in REQUIRED_FILES):
        raise FileExistsError("AKShare Raw evidence is append-only")
    columns = [str(name) for name in response.columns]
    request = {
        "provider": "AKShare", "interface": "crypto_js_spot",
        "parameters": {}, "requested_instrument": "ETHUSDT",
        "exact_match_required": True,
    }
    records = _safe(response.to_dict("records"))
    metadata = {
        "run_id": run_id, "provider": "AKShare", "interface": "crypto_js_spot",
        "parameters": {}, "requested_instrument": "ETHUSDT",
        "fetched_at": pd.Timestamp(fetched_at).isoformat(),
        "akshare_version": akshare_version, "columns": columns,
        "response_row_count": len(response), "response_schema_hash": _schema_hash(columns),
        "capability": _safe(capability),
    }
    for name, payload in (("request.json", request), ("response.json", records), ("metadata.json", metadata)):
        (evidence_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
    manifest = {
        **metadata,
        "response_content_sha256": _sha256(evidence_dir / "response.json"),
        "evidence_files": [
            _manifest_entry(role, evidence_dir / name)
            for role, name in REQUIRED_MANIFEST_ROLES.items()
        ],
    }
    (evidence_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def validate_raw_evidence(
    evidence_dir: Path, *, run_id: str, expected: CryptoIdentityContract,
) -> dict[str, Any]:
    blockers: list[str] = []
    if not evidence_dir.is_dir():
        return {"status": "BLOCKED", "blocking_reasons": [f"Raw evidence directory missing: {evidence_dir}"]}
    for name in REQUIRED_FILES:
        path = evidence_dir / name
        if not path.is_file():
            blockers.append(f"Raw required file missing: {name}")
        elif path.stat().st_size == 0:
            blockers.append(f"Raw required file empty: {name}")
    if blockers:
        return {"status": "BLOCKED", "blocking_reasons": blockers}
    parsed: dict[str, Any] = {}
    for name in REQUIRED_FILES:
        try:
            parsed[name] = json.loads((evidence_dir / name).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            blockers.append(f"Raw {name} is not valid JSON: {exc}")
    if blockers:
        return {"status": "BLOCKED", "blocking_reasons": blockers}
    request, response = parsed["request.json"], parsed["response.json"]
    metadata, manifest = parsed["metadata.json"], parsed["manifest.json"]
    if not isinstance(request, dict) or not isinstance(metadata, dict) or not isinstance(manifest, dict):
        blockers.append("Raw request, metadata and manifest must be JSON objects")
    if not isinstance(response, list) or not response:
        blockers.append("Raw response must be a non-empty JSON array")
        response = []
    expected_values = {
        "provider": expected.data_provider,
        "requested_instrument": expected.requested_instrument,
        "raw_instrument": expected.raw_instrument,
        "instrument_type": expected.instrument_type,
        "bar_interval": expected.bar_interval,
    }
    for field, value in expected_values.items():
        for label, document in (("metadata", metadata), ("manifest", manifest)):
            if isinstance(document, dict) and document.get(field) != value:
                blockers.append(f"Raw {label} {field} mismatch: expected {value!r}")
    if isinstance(request, dict):
        for field in ("provider", "requested_instrument", "instrument_type", "bar_interval"):
            expected_value = expected_values[field]
            if request.get(field) != expected_value:
                blockers.append(f"Raw request {field} mismatch: expected {expected_value!r}")
    for label, document in (("metadata", metadata), ("manifest", manifest)):
        if isinstance(document, dict) and document.get("run_id") != run_id:
            blockers.append(f"Raw {label} run_id mismatch")
    columns = list(response[0].keys()) if response and isinstance(response[0], dict) else []
    if any(not isinstance(row, dict) or list(row.keys()) != columns for row in response):
        blockers.append("Raw response rows have inconsistent schemas")
    required_identity = {"raw_instrument", "data_provider", "raw_exchange", "instrument_type", "bar_interval"}
    if response and not required_identity.issubset(columns):
        blockers.append(f"Raw response identity fields missing: {sorted(required_identity.difference(columns))}")
    for row in response:
        for field, value in {
            "raw_instrument": expected.raw_instrument,
            "data_provider": expected.data_provider,
            "raw_exchange": expected.raw_exchange,
            "instrument_type": expected.instrument_type,
            "bar_interval": expected.bar_interval,
        }.items():
            if row.get(field) != value:
                blockers.append(f"Raw response {field} mismatch")
                break
    actual_count = len(response)
    actual_schema_hash = _schema_hash(columns)
    for label, document in (("metadata", metadata), ("manifest", manifest)):
        if isinstance(document, dict):
            if document.get("response_row_count") != actual_count:
                blockers.append(f"Raw {label} response_row_count mismatch")
            if document.get("columns") != columns:
                blockers.append(f"Raw {label} columns mismatch")
            if document.get("response_schema_hash") != actual_schema_hash:
                blockers.append(f"Raw {label} response_schema_hash mismatch")
            if not document.get("fetched_at"):
                blockers.append(f"Raw {label} fetched_at missing")
    closed_world: dict[str, Any] = {
        "check_name": "manifest_closed_world",
        "status": "FAIL",
        "error_code": "manifest_not_checked",
        "unlisted_files": [],
        "missing_files": [],
    }
    if isinstance(manifest, dict):
        response_hash = _sha256(evidence_dir / "response.json")
        if manifest.get("response_content_sha256") != response_hash:
            blockers.append("Raw response content hash mismatch")
        listed = manifest.get("evidence_files")
        if not isinstance(listed, list):
            blockers.append("raw_manifest_entries_invalid: evidence_files must be an array")
        else:
            role_values: list[str] = []
            normalized_paths: list[str] = []
            valid_paths: list[tuple[dict[str, Any], str]] = []
            for index, entry in enumerate(listed):
                if not isinstance(entry, dict):
                    blockers.append(f"raw_manifest_entry_invalid: entry {index} must be an object")
                    continue
                role = entry.get("role")
                name = entry.get("name")
                digest = entry.get("sha256")
                size = entry.get("size_bytes")
                if not isinstance(role, str) or not role.strip():
                    blockers.append(f"raw_manifest_entry_missing_field: entry {index} role")
                else:
                    role = role.strip().casefold()
                    role_values.append(role)
                    if role not in REQUIRED_MANIFEST_ROLES:
                        blockers.append(f"raw_manifest_unknown_role: {role}")
                if not isinstance(name, str) or not name.strip():
                    blockers.append(f"raw_manifest_entry_missing_field: entry {index} name")
                    normalized = None
                else:
                    try:
                        normalized = _normalize_manifest_path(name)
                        normalized_paths.append(normalized)
                        valid_paths.append((entry, normalized))
                    except ValueError as exc:
                        normalized = None
                        blockers.append(f"raw_manifest_invalid_path: entry {index}: {exc}")
                if not isinstance(digest, str) or SHA256_PATTERN.fullmatch(digest) is None:
                    blockers.append(f"raw_manifest_entry_invalid_hash: entry {index}")
                if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                    blockers.append(f"raw_manifest_entry_invalid_size: entry {index}")
                if isinstance(role, str) and role in REQUIRED_MANIFEST_ROLES and normalized is not None:
                    expected_path = REQUIRED_MANIFEST_ROLES[role].casefold()
                    if normalized != expected_path:
                        blockers.append(
                            f"raw_manifest_role_path_mismatch: {role} must reference {expected_path}"
                        )
            role_counts = Counter(role_values)
            for role in REQUIRED_MANIFEST_ROLES:
                if role_counts[role] == 0:
                    blockers.append(f"raw_manifest_missing_role: {role}")
                elif role_counts[role] > 1:
                    blockers.append(f"raw_manifest_duplicate_role: {role}")
            for normalized, count in Counter(normalized_paths).items():
                if count > 1:
                    blockers.append(f"raw_manifest_duplicate_path: {normalized}")
            actual_entries, enumeration_blockers = _enumerate_raw_files(evidence_dir)
            blockers.extend(enumeration_blockers)
            actual_counts = Counter(normalized for _, normalized in actual_entries)
            for normalized, count in actual_counts.items():
                if count > 1:
                    blockers.append(f"manifest_duplicate_actual_path: {normalized}")
            listed_files = set(normalized_paths)
            actual_files = set(actual_counts)
            expected_files = listed_files | {"manifest.json"}
            actual_display = {
                normalized: min(
                    original for original, candidate in actual_entries
                    if candidate == normalized
                )
                for normalized in actual_files
            }
            unlisted_files = sorted(
                (actual_display[name] for name in actual_files - expected_files),
                key=lambda value: (value.casefold(), value),
            )
            missing_files = sorted(expected_files - actual_files)
            if unlisted_files:
                blockers.extend(
                    f"manifest_unlisted_file: {name}" for name in unlisted_files
                )
            if missing_files:
                blockers.extend(
                    f"manifest_declared_file_missing: {name}" for name in missing_files
                )
            closed_world = {
                "check_name": "manifest_closed_world",
                "status": "PASS" if not (
                    unlisted_files or missing_files or enumeration_blockers
                    or any(count > 1 for count in actual_counts.values())
                ) else "FAIL",
                "error_code": "manifest_unlisted_file" if unlisted_files else (
                    "manifest_declared_file_missing" if missing_files else (
                        "manifest_file_type_invalid" if enumeration_blockers else None
                    )
                ),
                "unlisted_files": unlisted_files,
                "missing_files": missing_files,
            }
            root = evidence_dir.resolve()
            for entry, normalized in valid_paths:
                path = evidence_dir.joinpath(*normalized.split("/"))
                try:
                    resolved = path.resolve()
                    resolved.relative_to(root)
                except (OSError, ValueError):
                    blockers.append(f"raw_manifest_path_escape: {entry.get('name')}")
                    continue
                if path.is_symlink() or not path.is_file():
                    blockers.append(
                        f"raw_manifest_file_missing: Raw manifest file missing: {entry.get('name')}"
                    )
                    continue
                actual_size = path.stat().st_size
                if actual_size == 0:
                    blockers.append(f"raw_manifest_file_empty: {entry.get('name')}")
                if isinstance(entry.get("size_bytes"), int) and not isinstance(entry.get("size_bytes"), bool):
                    if entry["size_bytes"] != actual_size:
                        blockers.append(f"raw_manifest_file_size_mismatch: {entry.get('name')}")
                if isinstance(entry.get("sha256"), str) and SHA256_PATTERN.fullmatch(entry["sha256"]):
                    if _sha256(path).casefold() != entry["sha256"].casefold():
                        blockers.append(f"raw_manifest_file_hash_mismatch: {entry.get('name')}")
    projection_hash = None
    if response:
        try:
            projection_hash = raw_projection_hash(pd.DataFrame(response))
        except (KeyError, TypeError, ValueError) as exc:
            blockers.append(f"Raw projection invalid: {exc}")
    return {
        "status": "READY" if not blockers else "BLOCKED",
        "blocking_reasons": sorted(set(blockers)),
        "row_count": actual_count,
        "schema_hash": actual_schema_hash,
        "raw_projection_sha256": projection_hash,
        "manifest_closed_world": closed_world,
    }
