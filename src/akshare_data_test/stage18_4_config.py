"""Strict configuration loader for Stage 18.4 DuckDB persistence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .config import ConfigError


EXPECTED_CATEGORIES = (
    "financial_abstract", "financial_indicator", "balance_sheet",
    "income_statement", "cash_flow_statement", "valuation_snapshot",
)
EXPECTED_TABLES = {
    "financial_abstract": "fact_financial_abstract",
    "financial_indicator": "fact_financial_indicator",
    "balance_sheet": "fact_balance_sheet",
    "income_statement": "fact_income_statement",
    "cash_flow_statement": "fact_cash_flow_statement",
    "valuation_snapshot": "fact_valuation_snapshot",
}
EXPECTED_ROWS = {
    "financial_abstract": 79917,
    "financial_indicator": 78482,
    "balance_sheet": 124211,
    "income_statement": 76720,
    "cash_flow_statement": 109656,
    "valuation_snapshot": 23,
}


@dataclass(frozen=True)
class Stage184Config:
    schema_version: str
    model_version: str
    source_run_id: str
    source_stage18_2_run_id: str
    source_run_path: Path
    source_manifest_path: Path
    clean_run_root: Path
    as_of_date: date
    tables: dict[str, str]
    expected_rows: dict[str, int]
    expected_history_rows: int
    expected_total_rows: int
    expected_security_count: int
    expected_a_shares: int
    expected_h_shares: int
    sample_rows: int
    database_root: Path
    database_filename: str
    reports_root: Path


def _map(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"Stage 18.4 {name} must be a mapping")
    return value


def _exact(value: dict[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise ConfigError(
            f"Stage 18.4 {name} keys differ; missing={sorted(expected-set(value))}, "
            f"unknown={sorted(set(value)-expected)}"
        )


def load_stage18_4_config(path: str | Path) -> Stage184Config:
    config_path = Path(path)
    try:
        root = _map(yaml.safe_load(config_path.read_text(encoding="utf-8")), "root")
    except FileNotFoundError as exc:
        raise ConfigError(f"Stage 18.4 config not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Stage 18.4 YAML parse error: {exc}") from exc
    _exact(root, {"schema_version", "stage", "substage", "model_version", "upstream", "stage18_4", "tables", "validation", "storage"}, "root")
    if root["stage"] != 18 or str(root["substage"]) != "18.4":
        raise ConfigError("Stage 18.4 config identifies the wrong stage")
    upstream = _map(root["upstream"], "upstream")
    _exact(upstream, {"stage18_3_run_id", "required_status", "stage18_4_authorized_required", "stage18_4_started_required", "stage18_2_run_id", "stage18_3_run_path", "stage18_3_manifest_path", "clean_run_root"}, "upstream")
    if upstream["required_status"] != "PASS" or upstream["stage18_4_authorized_required"] is not True or upstream["stage18_4_started_required"] is not False:
        raise ConfigError("Stage 18.4 requires an authorized, not-yet-started PASS Stage 18.3")
    stage = _map(root["stage18_4"], "stage18_4")
    _exact(stage, {"analysis_as_of_date", "asset_role", "writes_database", "writes_clean", "writes_features", "writes_stage19", "checkpoint_after_commit", "read_only_after_acceptance", "hive_partitioning"}, "stage18_4")
    if not (stage["asset_role"] == "fundamental_database" and stage["writes_database"] is True and stage["writes_clean"] is False and stage["writes_features"] is False and stage["writes_stage19"] is False and stage["checkpoint_after_commit"] is True and stage["read_only_after_acceptance"] is True and stage["hive_partitioning"] is False):
        raise ConfigError("Stage 18.4 write or persistence boundaries differ")
    table_cfg = _map(root["tables"], "tables")
    if tuple(table_cfg) != EXPECTED_CATEGORIES:
        raise ConfigError("Stage 18.4 table categories differ")
    tables: dict[str, str] = {}
    rows: dict[str, int] = {}
    for category in EXPECTED_CATEGORIES:
        item = _map(table_cfg[category], f"tables.{category}")
        _exact(item, {"name", "expected_rows"}, f"tables.{category}")
        tables[category] = str(item["name"])
        rows[category] = int(item["expected_rows"])
    if tables != EXPECTED_TABLES or rows != EXPECTED_ROWS:
        raise ConfigError("Stage 18.4 table names or frozen row counts differ")
    validation = _map(root["validation"], "validation")
    _exact(validation, {"expected_history_rows", "expected_total_rows", "expected_security_count", "expected_a_share_count", "expected_h_share_count", "deterministic_sample_rows", "require_zero_canonical_key_duplicates", "require_all_valuation_ineligible"}, "validation")
    counts = tuple(int(validation[key]) for key in ("expected_history_rows", "expected_total_rows", "expected_security_count", "expected_a_share_count", "expected_h_share_count"))
    if counts != (468986, 469009, 23, 16, 7) or validation["require_zero_canonical_key_duplicates"] is not True or validation["require_all_valuation_ineligible"] is not True:
        raise ConfigError("Stage 18.4 validation gates differ")
    storage = _map(root["storage"], "storage")
    _exact(storage, {"database_root", "database_filename", "reports_root"}, "storage")
    try:
        as_of = date.fromisoformat(str(stage["analysis_as_of_date"]))
    except ValueError as exc:
        raise ConfigError("Stage 18.4 analysis date must be YYYY-MM-DD") from exc
    return Stage184Config(
        schema_version=str(root["schema_version"]), model_version=str(root["model_version"]),
        source_run_id=str(upstream["stage18_3_run_id"]), source_stage18_2_run_id=str(upstream["stage18_2_run_id"]),
        source_run_path=Path(upstream["stage18_3_run_path"]), source_manifest_path=Path(upstream["stage18_3_manifest_path"]),
        clean_run_root=Path(upstream["clean_run_root"]), as_of_date=as_of,
        tables=tables, expected_rows=rows, expected_history_rows=468986, expected_total_rows=469009,
        expected_security_count=23, expected_a_shares=16, expected_h_shares=7,
        sample_rows=int(validation["deterministic_sample_rows"]), database_root=Path(storage["database_root"]),
        database_filename=str(storage["database_filename"]), reports_root=Path(storage["reports_root"]),
    )
