"""Strict configuration for Stage 18.3 fundamental Clean standardization."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .config import ConfigError


EXPECTED_CATEGORIES = (
    "financial_abstract",
    "financial_indicator",
    "balance_sheet",
    "income_statement",
    "cash_flow_statement",
    "valuation_snapshot",
)


@dataclass(frozen=True)
class MetricMapping:
    market: str
    category: str
    source_field: str
    canonical_name: str
    canonical_unit: str


@dataclass(frozen=True)
class Stage183Config:
    schema_version: str
    model_version: str
    source_run_id: str
    required_status: str
    authorized: bool
    source_run_path: Path
    source_manifest_path: Path
    expected_dataset_count: int
    expected_security_count: int
    expected_a_shares: int
    expected_h_shares: int
    as_of_date: date
    asset_role: str
    clean_schema_version: str
    categories: tuple[str, ...]
    variant_priority: tuple[str, ...]
    duplicate_rtol: float
    duplicate_atol: float
    a_share_default_currency: str
    mapping_path: Path
    required_core_fields: tuple[str, ...]
    mappings: tuple[MetricMapping, ...]
    clean_root: Path
    reports_root: Path
    raw_root: Path


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"Stage 18.3 {name} must be a mapping")
    return value


def _exact(value: dict[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise ConfigError(
            f"Stage 18.3 {name} keys differ; missing={sorted(expected-set(value))}, "
            f"unknown={sorted(set(value)-expected)}"
        )


def _load_metric_mappings(path: Path) -> tuple[MetricMapping, ...]:
    try:
        root = _mapping(yaml.safe_load(path.read_text(encoding="utf-8")), "metric mapping root")
    except FileNotFoundError as exc:
        raise ConfigError(f"Stage 18.3 metric mapping not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Stage 18.3 metric mapping YAML error: {exc}") from exc
    _exact(root, {"schema_version", "mapping_version", "mappings"}, "metric mapping root")
    if not isinstance(root["mappings"], list) or not root["mappings"]:
        raise ConfigError("Stage 18.3 metric mappings must be a non-empty list")
    result = []
    keys = set()
    for index, value in enumerate(root["mappings"]):
        row = _mapping(value, f"mappings[{index}]")
        _exact(
            row,
            {"market", "category", "source_field", "canonical_name", "canonical_unit"},
            f"mappings[{index}]",
        )
        item = MetricMapping(*(str(row[key]) for key in (
            "market", "category", "source_field", "canonical_name", "canonical_unit"
        )))
        if item.market not in {"A", "HK"} or item.category not in EXPECTED_CATEGORIES:
            raise ConfigError(f"Stage 18.3 mapping scope is invalid at row {index}")
        key = (item.market, item.category, item.source_field)
        if key in keys:
            raise ConfigError(f"Stage 18.3 duplicate mapping key: {key}")
        keys.add(key)
        result.append(item)
    return tuple(result)


def load_stage18_3_config(path: str | Path) -> Stage183Config:
    config_path = Path(path)
    try:
        root = _mapping(yaml.safe_load(config_path.read_text(encoding="utf-8")), "root")
    except FileNotFoundError as exc:
        raise ConfigError(f"Stage 18.3 config not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Stage 18.3 YAML parse error: {exc}") from exc
    _exact(root, {
        "schema_version", "stage", "substage", "model_version", "upstream",
        "stage18_3", "governance", "mapping", "storage",
    }, "root")
    if root["stage"] != 18 or str(root["substage"]) != "18.3":
        raise ConfigError("Stage 18.3 config identifies the wrong stage")
    upstream = _mapping(root["upstream"], "upstream")
    _exact(upstream, {
        "stage18_2_run_id", "required_status", "stage18_3_authorized_required",
        "stage18_2_run_path", "stage18_2_manifest_path", "expected_dataset_count",
        "expected_security_count", "expected_a_share_count", "expected_h_share_count",
    }, "upstream")
    stage = _mapping(root["stage18_3"], "stage18_3")
    _exact(stage, {
        "analysis_as_of_date", "asset_role", "writes_clean", "writes_database",
        "writes_features", "writes_stage19", "schema_version", "categories",
    }, "stage18_3")
    governance = _mapping(root["governance"], "governance")
    _exact(governance, {
        "missing_announcement_policy", "missing_update_policy",
        "future_announcement_policy", "future_update_policy", "snapshot_policy",
        "hk_variant_priority", "duplicate_numeric_rtol", "duplicate_numeric_atol",
        "a_share_default_currency",
    }, "governance")
    mapping = _mapping(root["mapping"], "mapping")
    _exact(mapping, {"path", "required_core_fields"}, "mapping")
    storage = _mapping(root["storage"], "storage")
    _exact(storage, {"clean_root", "reports_root", "stage18_2_raw_root"}, "storage")
    if upstream["required_status"] != "PASS" or upstream["stage18_3_authorized_required"] is not True:
        raise ConfigError("Stage 18.3 requires a PASS and authorized Stage 18.2")
    counts = tuple(int(upstream[key]) for key in (
        "expected_dataset_count", "expected_security_count",
        "expected_a_share_count", "expected_h_share_count",
    ))
    if counts != (175, 23, 16, 7):
        raise ConfigError("Stage 18.3 upstream scope must be 175 datasets and 23 securities")
    if not (
        stage["writes_clean"] is True
        and stage["writes_database"] is False
        and stage["writes_features"] is False
        and stage["writes_stage19"] is False
        and stage["asset_role"] == "fundamental_clean"
    ):
        raise ConfigError("Stage 18.3 write boundaries differ")
    categories = tuple(str(item) for item in stage["categories"])
    if categories != EXPECTED_CATEGORIES:
        raise ConfigError("Stage 18.3 categories differ from the six-category canonical schema")
    required_policies = (
        "not_pit_eligible", "not_pit_eligible", "not_pit_eligible",
        "not_pit_eligible", "preserve_observed_time_not_baseline",
    )
    observed_policies = tuple(str(governance[key]) for key in (
        "missing_announcement_policy", "missing_update_policy",
        "future_announcement_policy", "future_update_policy", "snapshot_policy",
    ))
    if observed_policies != required_policies:
        raise ConfigError("Stage 18.3 time-governance policies differ")
    variant_priority = tuple(str(item) for item in governance["hk_variant_priority"])
    if variant_priority != ("report_period", "annual"):
        raise ConfigError("Stage 18.3 HK variant priority differs")
    try:
        as_of = date.fromisoformat(str(stage["analysis_as_of_date"]))
    except ValueError as exc:
        raise ConfigError("Stage 18.3 analysis date must be YYYY-MM-DD") from exc
    mapping_path = Path(mapping["path"])
    mappings = _load_metric_mappings(mapping_path)
    required = tuple(str(item) for item in mapping["required_core_fields"])
    observed_core = {item.canonical_name for item in mappings}
    missing_core = sorted(set(required) - observed_core)
    if missing_core:
        raise ConfigError(f"Stage 18.3 key mappings missing: {missing_core}")
    rtol = float(governance["duplicate_numeric_rtol"])
    atol = float(governance["duplicate_numeric_atol"])
    if rtol < 0 or atol < 0:
        raise ConfigError("Stage 18.3 duplicate tolerances must be non-negative")
    return Stage183Config(
        schema_version=str(root["schema_version"]), model_version=str(root["model_version"]),
        source_run_id=str(upstream["stage18_2_run_id"]),
        required_status=str(upstream["required_status"]), authorized=True,
        source_run_path=Path(upstream["stage18_2_run_path"]),
        source_manifest_path=Path(upstream["stage18_2_manifest_path"]),
        expected_dataset_count=175, expected_security_count=23,
        expected_a_shares=16, expected_h_shares=7, as_of_date=as_of,
        asset_role=str(stage["asset_role"]), clean_schema_version=str(stage["schema_version"]),
        categories=categories, variant_priority=variant_priority,
        duplicate_rtol=rtol, duplicate_atol=atol,
        a_share_default_currency=str(governance["a_share_default_currency"]),
        mapping_path=mapping_path, required_core_fields=required, mappings=mappings,
        clean_root=Path(storage["clean_root"]), reports_root=Path(storage["reports_root"]),
        raw_root=Path(storage["stage18_2_raw_root"]),
    )
