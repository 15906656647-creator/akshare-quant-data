"""Strict configuration loader for the Stage 18.1 interface audit."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .config import ConfigError


@dataclass(frozen=True)
class Stage18Config:
    upstream_run_id: str
    upstream_status: str
    upstream_authorized: bool
    expected_daily_pass: int
    expected_a_shares: int
    expected_h_shares: int
    as_of_date: date
    snapshot_policy: str
    a_sample_count: int
    h_sample_count: int
    selection_policy: str
    max_attempts: int
    retry_delay_seconds: float
    request_timeout_seconds: float
    stage17_reports_root: Path
    stage17_raw_root: Path
    raw_root: Path
    reports_root: Path
    schema_version: str
    model_version: str


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"Stage 18 {field} must be a mapping")
    return value


def _exact_keys(value: dict[str, Any], expected: set[str], field: str) -> None:
    actual = set(value)
    if actual != expected:
        raise ConfigError(
            f"Stage 18 {field} keys differ; missing={sorted(expected-actual)}, "
            f"unknown={sorted(actual-expected)}"
        )


def _date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ConfigError(f"Stage 18 {field} must be YYYY-MM-DD") from exc


def load_stage18_config(path: str | Path) -> Stage18Config:
    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Stage 18 config not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Stage 18 YAML parse error: {exc}") from exc
    root = _mapping(raw, "root")
    _exact_keys(
        root,
        {
            "schema_version", "stage", "substage", "model_version", "upstream",
            "analysis", "samples", "runtime", "storage",
        },
        "root",
    )
    if root["stage"] != 18 or str(root["substage"]) != "18.1":
        raise ConfigError("Stage 18 config must identify stage 18, substage 18.1")

    upstream = _mapping(root["upstream"], "upstream")
    _exact_keys(upstream, {
        "stage17_run_id", "stage17_status_required",
        "stage18_authorized_required", "expected_daily_quality_pass_count",
        "expected_a_share_count", "expected_h_share_count",
    }, "upstream")
    analysis = _mapping(root["analysis"], "analysis")
    _exact_keys(analysis, {"as_of_date", "current_snapshot_policy"}, "analysis")
    samples = _mapping(root["samples"], "samples")
    _exact_keys(samples, {"a_share_count", "h_share_count", "selection_policy"}, "samples")
    runtime = _mapping(root["runtime"], "runtime")
    _exact_keys(runtime, {
        "max_attempts", "retry_delay_seconds", "request_timeout_seconds",
    }, "runtime")
    storage = _mapping(root["storage"], "storage")
    _exact_keys(storage, {
        "stage17_reports_root", "stage17_raw_root", "raw_root", "reports_root",
    }, "storage")

    if upstream["stage17_status_required"] != "PASS":
        raise ConfigError("Stage 18 upstream status must be PASS")
    if upstream["stage18_authorized_required"] is not True:
        raise ConfigError("Stage 18 authorization requirement must be true")
    if analysis["current_snapshot_policy"] != "audit_only":
        raise ConfigError("Stage 18.1 current snapshots must be audit_only")
    if samples["selection_policy"] != "exchange_listing_extremes_v1":
        raise ConfigError("Unsupported Stage 18.1 sample selection policy")
    if int(samples["a_share_count"]) != 3 or int(samples["h_share_count"]) != 2:
        raise ConfigError("Stage 18.1 sample counts must be 3 A shares and 2 H shares")
    attempts = int(runtime["max_attempts"])
    if attempts < 1 or attempts > 3:
        raise ConfigError("Stage 18.1 max_attempts must be between 1 and 3")

    return Stage18Config(
        upstream_run_id=str(upstream["stage17_run_id"]),
        upstream_status=str(upstream["stage17_status_required"]),
        upstream_authorized=bool(upstream["stage18_authorized_required"]),
        expected_daily_pass=int(upstream["expected_daily_quality_pass_count"]),
        expected_a_shares=int(upstream["expected_a_share_count"]),
        expected_h_shares=int(upstream["expected_h_share_count"]),
        as_of_date=_date(analysis["as_of_date"], "analysis.as_of_date"),
        snapshot_policy=str(analysis["current_snapshot_policy"]),
        a_sample_count=int(samples["a_share_count"]),
        h_sample_count=int(samples["h_share_count"]),
        selection_policy=str(samples["selection_policy"]),
        max_attempts=attempts,
        retry_delay_seconds=float(runtime["retry_delay_seconds"]),
        request_timeout_seconds=float(runtime["request_timeout_seconds"]),
        stage17_reports_root=Path(storage["stage17_reports_root"]),
        stage17_raw_root=Path(storage["stage17_raw_root"]),
        raw_root=Path(storage["raw_root"]),
        reports_root=Path(storage["reports_root"]),
        schema_version=str(root["schema_version"]),
        model_version=str(root["model_version"]),
    )
