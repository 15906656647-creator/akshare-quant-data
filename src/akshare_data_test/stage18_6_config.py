"""Strict configuration for Stage 18.6 final acceptance and exit freeze."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .config import ConfigError


STAGE_KEYS = ("stage18_1", "stage18_2", "stage18_3", "stage18_4", "stage18_5")


@dataclass(frozen=True)
class Stage186Config:
    schema_version: str
    model_version: str
    run_ids: dict[str, str]
    database_path: Path
    database_sha256: str
    feature_path: Path
    feature_sha256: str
    as_of_date: date
    expected_security_count: int
    expected_feature_count: int
    expected_feature_units: int
    expected_pass: int
    expected_unavailable: int
    allowed_reasons: dict[str, int]
    reports_root: Path


def _map(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"Stage 18.6 {name} must be a mapping")
    return value


def _exact(value: dict[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise ConfigError(f"Stage 18.6 {name} keys differ; missing={sorted(expected-set(value))}, unknown={sorted(set(value)-expected)}")


def load_stage18_6_config(path: str | Path) -> Stage186Config:
    config_path = Path(path)
    try:
        root = _map(yaml.safe_load(config_path.read_text(encoding="utf-8")), "root")
    except FileNotFoundError as exc:
        raise ConfigError(f"Stage 18.6 config not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Stage 18.6 YAML parse error: {exc}") from exc
    _exact(root, {"schema_version", "stage", "substage", "model_version", "upstream_runs", "formal_assets", "acceptance", "boundaries", "storage"}, "root")
    if root["stage"] != 18 or str(root["substage"]) != "18.6":
        raise ConfigError("Stage 18.6 config identifies the wrong stage")
    upstream = _map(root["upstream_runs"], "upstream_runs")
    _exact(upstream, set(STAGE_KEYS) | {"required_status", "stage18_6_authorized_required", "stage18_6_started_required"}, "upstream_runs")
    if upstream["required_status"] != "PASS" or upstream["stage18_6_authorized_required"] is not True or upstream["stage18_6_started_required"] is not False:
        raise ConfigError("Stage 18.6 requires an authorized, not-yet-started PASS Stage 18.5")
    assets = _map(root["formal_assets"], "formal_assets")
    _exact(assets, {"database_path", "database_sha256", "feature_path", "feature_sha256"}, "formal_assets")
    acceptance = _map(root["acceptance"], "acceptance")
    _exact(acceptance, {"analysis_as_of_date", "expected_security_count", "expected_feature_count", "expected_feature_units", "expected_pass", "expected_unavailable", "expected_fail", "expected_blocked", "allowed_unavailable_reasons", "expected_future_data_usage", "expected_announcement_inference", "expected_valuation_leakage", "expected_period_mismatch", "current_valuation_eligible"}, "acceptance")
    counts = tuple(int(acceptance[key]) for key in ("expected_security_count", "expected_feature_count", "expected_feature_units", "expected_pass", "expected_unavailable", "expected_fail", "expected_blocked"))
    if counts != (23, 12, 276, 170, 106, 0, 0):
        raise ConfigError("Stage 18.6 frozen coverage counts differ")
    reasons = {str(key): int(value) for key, value in _map(acceptance["allowed_unavailable_reasons"], "allowed_unavailable_reasons").items()}
    if reasons != {"NO_PIT_ELIGIBLE_INPUT": 49, "NO_COMMON_PIT_REPORT_PERIOD": 21, "ANNUAL_OR_PRIOR_BALANCE_UNAVAILABLE": 36}:
        raise ConfigError("Stage 18.6 unavailable reason contract differs")
    gates = tuple(acceptance[key] for key in ("expected_future_data_usage", "expected_announcement_inference", "expected_valuation_leakage", "expected_period_mismatch", "current_valuation_eligible"))
    if gates != (0, 0, 0, 0, False):
        raise ConfigError("Stage 18.6 time/valuation gates differ")
    boundaries = _map(root["boundaries"], "boundaries")
    _exact(boundaries, {"writes_database", "writes_raw", "writes_clean", "writes_features", "writes_stage19", "stage19_started"}, "boundaries")
    if any(boundaries.values()):
        raise ConfigError("Stage 18.6 must not write upstream assets or start Stage 19")
    storage = _map(root["storage"], "storage")
    _exact(storage, {"reports_root"}, "storage")
    try: as_of = date.fromisoformat(str(acceptance["analysis_as_of_date"]))
    except ValueError as exc: raise ConfigError("Stage 18.6 analysis date must be YYYY-MM-DD") from exc
    for key in ("database_sha256", "feature_sha256"):
        if len(str(assets[key])) != 64: raise ConfigError(f"Stage 18.6 {key} is invalid")
    return Stage186Config(
        schema_version=str(root["schema_version"]), model_version=str(root["model_version"]),
        run_ids={key: str(upstream[key]) for key in STAGE_KEYS},
        database_path=Path(assets["database_path"]), database_sha256=str(assets["database_sha256"]),
        feature_path=Path(assets["feature_path"]), feature_sha256=str(assets["feature_sha256"]),
        as_of_date=as_of, expected_security_count=23, expected_feature_count=12,
        expected_feature_units=276, expected_pass=170, expected_unavailable=106,
        allowed_reasons=reasons, reports_root=Path(storage["reports_root"]),
    )
