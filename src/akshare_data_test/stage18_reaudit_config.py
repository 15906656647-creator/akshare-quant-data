"""Strict configuration for the Stage 18.1.3 full capability re-audit."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .config import ConfigError


@dataclass(frozen=True)
class SelectedValuation:
    kind: str
    provider: str
    interfaces: tuple[str, ...]
    required_fields: tuple[str, ...]


@dataclass(frozen=True)
class Stage18ReauditConfig:
    schema_version: str
    model_version: str
    stage18_config_path: Path
    valuation_run_id: str
    valuation_status: str
    valuation_run_path: Path
    valuation_manifest_path: Path
    frozen_run_id: str
    frozen_evidence_path: Path
    as_of_date: date
    asset_role: str
    valuation: dict[str, SelectedValuation]
    frozen_interfaces: tuple[str, ...]
    max_attempts: int
    retry_delay_seconds: float
    request_timeout_seconds: float
    raw_root: Path
    reports_root: Path


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"Stage 18.1.3 {field} must be a mapping")
    return value


def _exact(value: dict[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ConfigError(
            f"Stage 18.1.3 {field} keys differ; "
            f"missing={sorted(expected-set(value))}, unknown={sorted(set(value)-expected)}"
        )


def _selection(value: Any, market: str) -> SelectedValuation:
    row = _mapping(value, f"valuation.{market}")
    _exact(row, {"type", "provider", "interfaces", "required_fields"}, f"valuation.{market}")
    interfaces = tuple(str(item) for item in row["interfaces"])
    fields = tuple(str(item) for item in row["required_fields"])
    expected_kind = "composite" if market == "A" else "single"
    expected_interfaces = (
        ("stock_zh_valuation_comparison_em", "stock_zh_scale_comparison_em")
        if market == "A" else ("stock_hk_financial_indicator_em",)
    )
    expected_fields = (
        ("symbol", "pe", "pb", "total_market_cap", "floating_market_cap", "snapshot_time")
        if market == "A" else ("symbol", "pe", "pb", "total_market_cap", "snapshot_time")
    )
    if row["type"] != expected_kind or interfaces != expected_interfaces or fields != expected_fields:
        raise ConfigError(f"Stage 18.1.3 selected valuation capability differs for {market}")
    if row["provider"] != "EastmoneyDataCenter":
        raise ConfigError("Stage 18.1.3 selected provider must match the audited provider")
    return SelectedValuation(expected_kind, str(row["provider"]), interfaces, fields)


def load_stage18_reaudit_config(path: str | Path) -> Stage18ReauditConfig:
    config_path = Path(path)
    try:
        root = _mapping(yaml.safe_load(config_path.read_text(encoding="utf-8")), "root")
    except FileNotFoundError as exc:
        raise ConfigError(f"Stage 18.1.3 config not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Stage 18.1.3 YAML parse error: {exc}") from exc
    _exact(root, {
        "schema_version", "stage", "substage", "model_version", "upstream",
        "analysis", "valuation", "runtime", "storage",
    }, "root")
    if root["stage"] != 18 or str(root["substage"]) != "18.1.3":
        raise ConfigError("Stage 18.1.3 config identifies the wrong stage")
    upstream = _mapping(root["upstream"], "upstream")
    _exact(upstream, {
        "stage18_config_path", "valuation_audit_run_id",
        "valuation_audit_status_required", "valuation_audit_run_path",
        "valuation_audit_manifest_path", "frozen_failure_evidence_run_id",
        "frozen_failure_evidence_path",
    }, "upstream")
    analysis = _mapping(root["analysis"], "analysis")
    _exact(analysis, {
        "as_of_date", "asset_role", "audit_only",
        "eligible_for_stage18_2_ingestion",
    }, "analysis")
    valuation = _mapping(root["valuation"], "valuation")
    _exact(valuation, {"A", "HK", "frozen_rejected_interfaces"}, "valuation")
    runtime = _mapping(root["runtime"], "runtime")
    _exact(runtime, {"max_attempts", "retry_delay_seconds", "request_timeout_seconds"}, "runtime")
    storage = _mapping(root["storage"], "storage")
    _exact(storage, {"raw_root", "reports_root"}, "storage")
    if upstream["valuation_audit_status_required"] != "PASS":
        raise ConfigError("Stage 18.1.3 requires a PASS Stage 18.1.2 audit")
    if analysis["asset_role"] != "interface_audit" or analysis["audit_only"] is not True:
        raise ConfigError("Stage 18.1.3 assets must be interface_audit/audit_only")
    if analysis["eligible_for_stage18_2_ingestion"] is not False:
        raise ConfigError("Stage 18.1.3 assets must be ingestion-ineligible")
    frozen = tuple(str(item) for item in valuation["frozen_rejected_interfaces"])
    if frozen != ("stock_zh_a_spot_em", "stock_hk_spot_em"):
        raise ConfigError("Stage 18.1.3 frozen rejected interfaces differ")
    attempts = int(runtime["max_attempts"])
    timeout = float(runtime["request_timeout_seconds"])
    if attempts < 1 or attempts > 3 or timeout <= 0:
        raise ConfigError("Stage 18.1.3 retry/timeout settings are invalid")
    try:
        as_of = date.fromisoformat(str(analysis["as_of_date"]))
    except ValueError as exc:
        raise ConfigError("Stage 18.1.3 analysis.as_of_date must be YYYY-MM-DD") from exc
    return Stage18ReauditConfig(
        schema_version=str(root["schema_version"]), model_version=str(root["model_version"]),
        stage18_config_path=Path(upstream["stage18_config_path"]),
        valuation_run_id=str(upstream["valuation_audit_run_id"]),
        valuation_status=str(upstream["valuation_audit_status_required"]),
        valuation_run_path=Path(upstream["valuation_audit_run_path"]),
        valuation_manifest_path=Path(upstream["valuation_audit_manifest_path"]),
        frozen_run_id=str(upstream["frozen_failure_evidence_run_id"]),
        frozen_evidence_path=Path(upstream["frozen_failure_evidence_path"]),
        as_of_date=as_of, asset_role=str(analysis["asset_role"]),
        valuation={market: _selection(valuation[market], market) for market in ("A", "HK")},
        frozen_interfaces=frozen, max_attempts=attempts,
        retry_delay_seconds=float(runtime["retry_delay_seconds"]),
        request_timeout_seconds=timeout, raw_root=Path(storage["raw_root"]),
        reports_root=Path(storage["reports_root"]),
    )
