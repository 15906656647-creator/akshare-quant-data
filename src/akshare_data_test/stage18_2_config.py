"""Strict Stage 18.2 formal fundamental Raw collection configuration."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .config import ConfigError


@dataclass(frozen=True)
class CollectionSpec:
    category: str
    interface: str
    provider: str
    variants: tuple[str, ...]


@dataclass(frozen=True)
class Stage182Config:
    schema_version: str
    model_version: str
    stage17_run_id: str
    stage18_1_run_id: str
    stage18_1_status: str
    stage18_2_authorized: bool
    stage18_1_run_path: Path
    stage18_1_manifest_path: Path
    expected_a_shares: int
    expected_h_shares: int
    as_of_date: date
    asset_role: str
    snapshot_policy: str
    eligible_for_as_of_analysis: bool
    collections: dict[str, tuple[CollectionSpec, ...]]
    max_attempts: int
    retry_delay_seconds: float
    request_timeout_seconds: float
    stage18_config_path: Path
    raw_root: Path
    reports_root: Path


EXPECTED_COLLECTIONS = {
    "A": (
        ("financial_abstract", "stock_financial_abstract", "Sina", ("default",)),
        ("financial_indicator", "stock_financial_analysis_indicator", "Sina", ("default",)),
        ("balance_sheet", "stock_balance_sheet_by_report_em", "EastmoneyDataCenter", ("report",)),
        ("income_statement", "stock_profit_sheet_by_report_em", "EastmoneyDataCenter", ("report",)),
        ("cash_flow_statement", "stock_cash_flow_sheet_by_report_em", "EastmoneyDataCenter", ("report",)),
        ("valuation_snapshot", "stock_zh_valuation_comparison_em", "EastmoneyDataCenter", ("valuation_comparison",)),
        ("valuation_snapshot", "stock_zh_scale_comparison_em", "EastmoneyDataCenter", ("scale_comparison",)),
    ),
    "HK": (
        ("financial_indicator", "stock_financial_hk_analysis_indicator_em", "EastmoneyDataCenter", ("annual", "report_period")),
        ("balance_sheet", "stock_financial_hk_report_em", "EastmoneyDataCenter", ("annual", "report_period")),
        ("income_statement", "stock_financial_hk_report_em", "EastmoneyDataCenter", ("annual", "report_period")),
        ("cash_flow_statement", "stock_financial_hk_report_em", "EastmoneyDataCenter", ("annual", "report_period")),
        ("valuation_snapshot", "stock_hk_financial_indicator_em", "EastmoneyDataCenter", ("current",)),
    ),
}


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"Stage 18.2 {field} must be a mapping")
    return value


def _exact(value: dict[str, Any], expected: set[str], field: str) -> None:
    if set(value) != expected:
        raise ConfigError(
            f"Stage 18.2 {field} keys differ; missing={sorted(expected-set(value))}, "
            f"unknown={sorted(set(value)-expected)}"
        )


def _collection_rows(value: Any, market: str) -> tuple[CollectionSpec, ...]:
    if not isinstance(value, list):
        raise ConfigError(f"Stage 18.2 collections.{market} must be a list")
    rows = []
    for index, item in enumerate(value):
        row = _mapping(item, f"collections.{market}[{index}]")
        _exact(row, {"category", "interface", "provider", "variants"}, f"collections.{market}[{index}]")
        rows.append(CollectionSpec(
            str(row["category"]), str(row["interface"]), str(row["provider"]),
            tuple(str(x) for x in row["variants"]),
        ))
    observed = tuple((x.category, x.interface, x.provider, x.variants) for x in rows)
    if observed != EXPECTED_COLLECTIONS[market]:
        raise ConfigError(f"Stage 18.2 collections.{market} differs from Stage 18.1 PASS matrix")
    return tuple(rows)


def load_stage18_2_config(path: str | Path) -> Stage182Config:
    config_path = Path(path)
    try:
        root = _mapping(yaml.safe_load(config_path.read_text(encoding="utf-8")), "root")
    except FileNotFoundError as exc:
        raise ConfigError(f"Stage 18.2 config not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Stage 18.2 YAML parse error: {exc}") from exc
    _exact(root, {
        "schema_version", "stage", "substage", "model_version", "upstream",
        "analysis", "collections", "runtime", "storage",
    }, "root")
    if root["stage"] != 18 or str(root["substage"]) != "18.2":
        raise ConfigError("Stage 18.2 config identifies the wrong stage")
    upstream = _mapping(root["upstream"], "upstream")
    _exact(upstream, {
        "stage17_run_id", "stage18_1_run_id", "stage18_1_status_required",
        "stage18_2_authorized_required", "stage18_1_run_path",
        "stage18_1_manifest_path", "expected_a_share_count", "expected_h_share_count",
    }, "upstream")
    analysis = _mapping(root["analysis"], "analysis")
    _exact(analysis, {
        "as_of_date", "asset_role", "snapshot_policy", "eligible_for_as_of_date_analysis",
    }, "analysis")
    collections = _mapping(root["collections"], "collections")
    _exact(collections, {"A", "HK"}, "collections")
    runtime = _mapping(root["runtime"], "runtime")
    _exact(runtime, {"max_attempts", "retry_delay_seconds", "request_timeout_seconds"}, "runtime")
    storage = _mapping(root["storage"], "storage")
    _exact(storage, {"stage18_config_path", "raw_root", "reports_root"}, "storage")
    if upstream["stage18_1_status_required"] != "PASS" or upstream["stage18_2_authorized_required"] is not True:
        raise ConfigError("Stage 18.2 requires PASS/authorized Stage 18.1")
    if int(upstream["expected_a_share_count"]) != 16 or int(upstream["expected_h_share_count"]) != 7:
        raise ConfigError("Stage 18.2 scope must be 16 A shares and 7 H shares")
    if analysis["asset_role"] != "fundamental_raw":
        raise ConfigError("Stage 18.2 asset_role must be fundamental_raw")
    if analysis["snapshot_policy"] != "current_snapshot_not_baseline":
        raise ConfigError("Stage 18.2 snapshot policy differs")
    if analysis["eligible_for_as_of_date_analysis"] is not False:
        raise ConfigError("Stage 18.2 current snapshots cannot be baseline-eligible")
    attempts = int(runtime["max_attempts"])
    timeout = float(runtime["request_timeout_seconds"])
    if attempts < 1 or attempts > 3 or timeout <= 0:
        raise ConfigError("Stage 18.2 retry/timeout settings are invalid")
    try:
        as_of = date.fromisoformat(str(analysis["as_of_date"]))
    except ValueError as exc:
        raise ConfigError("Stage 18.2 analysis.as_of_date must be YYYY-MM-DD") from exc
    return Stage182Config(
        schema_version=str(root["schema_version"]), model_version=str(root["model_version"]),
        stage17_run_id=str(upstream["stage17_run_id"]),
        stage18_1_run_id=str(upstream["stage18_1_run_id"]),
        stage18_1_status=str(upstream["stage18_1_status_required"]),
        stage18_2_authorized=True,
        stage18_1_run_path=Path(upstream["stage18_1_run_path"]),
        stage18_1_manifest_path=Path(upstream["stage18_1_manifest_path"]),
        expected_a_shares=16, expected_h_shares=7, as_of_date=as_of,
        asset_role=str(analysis["asset_role"]),
        snapshot_policy=str(analysis["snapshot_policy"]),
        eligible_for_as_of_analysis=False,
        collections={market: _collection_rows(collections[market], market) for market in ("A", "HK")},
        max_attempts=attempts, retry_delay_seconds=float(runtime["retry_delay_seconds"]),
        request_timeout_seconds=timeout, stage18_config_path=Path(storage["stage18_config_path"]),
        raw_root=Path(storage["raw_root"]), reports_root=Path(storage["reports_root"]),
    )
