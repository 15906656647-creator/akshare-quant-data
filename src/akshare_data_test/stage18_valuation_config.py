"""Strict configuration for Stage 18.1.2 valuation-provider auditing."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .config import ConfigError


@dataclass(frozen=True)
class ProviderSpec:
    interface: str
    provider: str
    mode: str


@dataclass(frozen=True)
class Stage18ValuationConfig:
    schema_version: str
    model_version: str
    stage18_config_path: Path
    upstream_run_id: str
    upstream_status: str
    upstream_evidence_path: Path
    frozen_failed_interfaces: tuple[str, ...]
    as_of_date: date
    asset_role: str
    audit_only: bool
    eligible_for_ingestion: bool
    required_capabilities: dict[str, tuple[str, ...]]
    optional_capabilities: dict[str, tuple[str, ...]]
    registry: dict[str, tuple[ProviderSpec, ...]]
    scan_keywords: tuple[str, ...]
    max_attempts: int
    retry_delay_seconds: float
    request_timeout_seconds: float
    raw_root: Path
    reports_root: Path


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"Stage 18.1.2 {field} must be a mapping")
    return value


def _exact(value: dict[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ConfigError(
            f"Stage 18.1.2 {field} keys differ; "
            f"missing={sorted(expected-set(value))}, unknown={sorted(set(value)-expected)}"
        )


def _providers(value: Any, market: str) -> tuple[ProviderSpec, ...]:
    if not isinstance(value, list) or not value:
        raise ConfigError(f"Stage 18.1.2 registry.{market} must be a non-empty list")
    result = []
    for index, item in enumerate(value):
        row = _mapping(item, f"registry.{market}[{index}]")
        _exact(row, {"interface", "provider", "mode"}, f"registry.{market}[{index}]")
        if row["mode"] not in {"shared_snapshot", "symbol_snapshot", "metric_series"}:
            raise ConfigError(f"Unsupported Stage 18.1.2 provider mode: {row['mode']}")
        result.append(ProviderSpec(str(row["interface"]), str(row["provider"]), str(row["mode"])))
    if len({item.interface for item in result}) != len(result):
        raise ConfigError(f"Duplicate Stage 18.1.2 interface in registry.{market}")
    return tuple(result)


def load_stage18_valuation_config(path: str | Path) -> Stage18ValuationConfig:
    config_path = Path(path)
    try:
        root = _mapping(yaml.safe_load(config_path.read_text(encoding="utf-8")), "root")
    except FileNotFoundError as exc:
        raise ConfigError(f"Stage 18.1.2 config not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Stage 18.1.2 YAML parse error: {exc}") from exc
    _exact(root, {
        "schema_version", "stage", "substage", "model_version", "upstream",
        "analysis", "registry", "runtime", "storage",
    }, "root")
    if root["stage"] != 18 or str(root["substage"]) != "18.1.2":
        raise ConfigError("Stage 18.1.2 config identifies the wrong stage")
    upstream = _mapping(root["upstream"], "upstream")
    _exact(upstream, {
        "stage18_config_path", "stage18_1_1_run_id", "stage18_1_1_status_required",
        "stage18_1_1_evidence_path", "frozen_failed_interfaces",
    }, "upstream")
    analysis = _mapping(root["analysis"], "analysis")
    _exact(analysis, {
        "as_of_date", "asset_role", "audit_only", "eligible_for_stage18_2_ingestion",
        "required_capabilities", "optional_capabilities",
    }, "analysis")
    registry = _mapping(root["registry"], "registry")
    _exact(registry, {"A", "HK", "auto_scan_keywords"}, "registry")
    runtime = _mapping(root["runtime"], "runtime")
    _exact(runtime, {"max_attempts", "retry_delay_seconds", "request_timeout_seconds"}, "runtime")
    storage = _mapping(root["storage"], "storage")
    _exact(storage, {"raw_root", "reports_root"}, "storage")
    if upstream["stage18_1_1_status_required"] != "BLOCKED":
        raise ConfigError("Stage 18.1.2 must preserve the Stage 18.1.1 BLOCKED fact")
    if tuple(upstream["frozen_failed_interfaces"]) != (
        "stock_zh_a_spot_em", "stock_hk_spot_em",
    ):
        raise ConfigError("Stage 18.1.2 frozen failed interfaces differ")
    if analysis["asset_role"] != "valuation_provider_audit":
        raise ConfigError("Stage 18.1.2 asset_role must be valuation_provider_audit")
    if analysis["audit_only"] is not True or analysis["eligible_for_stage18_2_ingestion"] is not False:
        raise ConfigError("Stage 18.1.2 evidence must be audit-only and ingestion-ineligible")
    requirements = _mapping(analysis["required_capabilities"], "required_capabilities")
    optional = _mapping(analysis["optional_capabilities"], "optional_capabilities")
    _exact(requirements, {"A", "HK"}, "required_capabilities")
    _exact(optional, {"A", "HK"}, "optional_capabilities")
    attempts = int(runtime["max_attempts"])
    timeout = float(runtime["request_timeout_seconds"])
    if attempts < 1 or attempts > 3 or timeout <= 0:
        raise ConfigError("Stage 18.1.2 retry/timeout settings are invalid")
    try:
        as_of = date.fromisoformat(str(analysis["as_of_date"]))
    except ValueError as exc:
        raise ConfigError("Stage 18.1.2 analysis.as_of_date must be YYYY-MM-DD") from exc
    return Stage18ValuationConfig(
        schema_version=str(root["schema_version"]), model_version=str(root["model_version"]),
        stage18_config_path=Path(upstream["stage18_config_path"]),
        upstream_run_id=str(upstream["stage18_1_1_run_id"]),
        upstream_status=str(upstream["stage18_1_1_status_required"]),
        upstream_evidence_path=Path(upstream["stage18_1_1_evidence_path"]),
        frozen_failed_interfaces=tuple(str(x) for x in upstream["frozen_failed_interfaces"]),
        as_of_date=as_of, asset_role=str(analysis["asset_role"]),
        audit_only=True, eligible_for_ingestion=False,
        required_capabilities={m: tuple(str(x) for x in requirements[m]) for m in ("A", "HK")},
        optional_capabilities={m: tuple(str(x) for x in optional[m]) for m in ("A", "HK")},
        registry={m: _providers(registry[m], m) for m in ("A", "HK")},
        scan_keywords=tuple(str(x).casefold() for x in registry["auto_scan_keywords"]),
        max_attempts=attempts, retry_delay_seconds=float(runtime["retry_delay_seconds"]),
        request_timeout_seconds=timeout, raw_root=Path(storage["raw_root"]),
        reports_root=Path(storage["reports_root"]),
    )
