"""Strict Stage 18.5 PIT feature configuration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .config import ConfigError


FEATURE_NAMES = (
    "revenue", "net_profit", "total_assets", "total_equity",
    "operating_cash_flow", "revenue_yoy", "net_profit_yoy", "net_margin",
    "roa", "roe", "debt_to_asset", "ocf_to_net_profit",
)


@dataclass(frozen=True)
class Stage185Config:
    schema_version: str
    model_version: str
    source_run_id: str
    source_run_path: Path
    source_manifest_path: Path
    database_path: Path
    database_sha256: str
    as_of_date: date
    feature_names: tuple[str, ...]
    expected_security_count: int
    expected_a_shares: int
    expected_h_shares: int
    feature_root: Path
    reports_root: Path


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"Stage 18.5 {name} must be a mapping")
    return value


def _exact(value: dict[str, Any], keys: set[str], name: str) -> None:
    if set(value) != keys:
        raise ConfigError(f"Stage 18.5 {name} keys differ; missing={sorted(keys-set(value))}, unknown={sorted(set(value)-keys)}")


def load_stage18_5_config(path: str | Path) -> Stage185Config:
    config_path = Path(path)
    try:
        root = _mapping(yaml.safe_load(config_path.read_text(encoding="utf-8")), "root")
    except FileNotFoundError as exc:
        raise ConfigError(f"Stage 18.5 config not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Stage 18.5 YAML parse error: {exc}") from exc
    _exact(root, {"schema_version", "stage", "substage", "model_version", "upstream", "stage18_5", "scope", "governance", "storage"}, "root")
    if root["stage"] != 18 or str(root["substage"]) != "18.5":
        raise ConfigError("Stage 18.5 config identifies the wrong stage")
    upstream = _mapping(root["upstream"], "upstream")
    _exact(upstream, {"stage18_4_run_id", "required_status", "stage18_5_authorized_required", "stage18_5_started_required", "stage18_4_run_path", "stage18_4_manifest_path", "database_path", "database_sha256"}, "upstream")
    if upstream["required_status"] != "PASS" or upstream["stage18_5_authorized_required"] is not True or upstream["stage18_5_started_required"] is not False:
        raise ConfigError("Stage 18.5 requires an authorized, not-yet-started PASS Stage 18.4")
    stage = _mapping(root["stage18_5"], "stage18_5")
    _exact(stage, {"analysis_as_of_date", "asset_role", "input_mode", "pit_status_required", "eligible_flag_required", "writes_features", "writes_database", "writes_clean", "writes_stage19", "valuation_snapshot_allowed", "announcement_date_inference_allowed", "currency_conversion_allowed"}, "stage18_5")
    expected_stage = ("fundamental_feature", "read_only", "PIT_ELIGIBLE", True, True, False, False, False, False, False, False)
    observed_stage = tuple(stage[key] for key in ("asset_role", "input_mode", "pit_status_required", "eligible_flag_required", "writes_features", "writes_database", "writes_clean", "writes_stage19", "valuation_snapshot_allowed", "announcement_date_inference_allowed", "currency_conversion_allowed"))
    if observed_stage != expected_stage:
        raise ConfigError("Stage 18.5 PIT/write boundaries differ")
    scope = _mapping(root["scope"], "scope")
    _exact(scope, {"expected_security_count", "expected_a_share_count", "expected_h_share_count", "feature_names"}, "scope")
    counts = (int(scope["expected_security_count"]), int(scope["expected_a_share_count"]), int(scope["expected_h_share_count"]))
    if counts != (23, 16, 7) or tuple(scope["feature_names"]) != FEATURE_NAMES:
        raise ConfigError("Stage 18.5 security or feature scope differs")
    governance = _mapping(root["governance"], "governance")
    _exact(governance, {"unavailable_allowed", "comparable_period_rule", "annual_ratio_period", "ratio_denominator_zero_policy", "missing_input_policy", "mixed_currency_policy", "output_format"}, "governance")
    observed_governance = tuple(governance[key] for key in ("unavailable_allowed", "comparable_period_rule", "annual_ratio_period", "ratio_denominator_zero_policy", "missing_input_policy", "mixed_currency_policy", "output_format"))
    if observed_governance != (True, "same_fiscal_period_prior_year", "FY", "UNAVAILABLE", "UNAVAILABLE", "UNAVAILABLE", "long"):
        raise ConfigError("Stage 18.5 feature governance differs")
    storage = _mapping(root["storage"], "storage")
    _exact(storage, {"feature_root", "reports_root"}, "storage")
    try:
        as_of = date.fromisoformat(str(stage["analysis_as_of_date"]))
    except ValueError as exc:
        raise ConfigError("Stage 18.5 analysis date must be YYYY-MM-DD") from exc
    sha = str(upstream["database_sha256"])
    if len(sha) != 64:
        raise ConfigError("Stage 18.5 database SHA-256 is invalid")
    return Stage185Config(
        schema_version=str(root["schema_version"]), model_version=str(root["model_version"]),
        source_run_id=str(upstream["stage18_4_run_id"]), source_run_path=Path(upstream["stage18_4_run_path"]),
        source_manifest_path=Path(upstream["stage18_4_manifest_path"]), database_path=Path(upstream["database_path"]),
        database_sha256=sha, as_of_date=as_of, feature_names=FEATURE_NAMES,
        expected_security_count=23, expected_a_shares=16, expected_h_shares=7,
        feature_root=Path(storage["feature_root"]), reports_root=Path(storage["reports_root"]),
    )
