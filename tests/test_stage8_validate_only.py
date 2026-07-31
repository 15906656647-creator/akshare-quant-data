from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest
import yaml

from akshare_data_test.stage8_build import validate_stage8_inputs


ROOT = Path(__file__).resolve().parents[1]
START = pd.Timestamp("2026-01-01")
END = pd.Timestamp("2026-01-31")


def _config(path: Path) -> Path:
    content = {
        "schema_version": "1.0.0",
        "price_adjust_type": "raw",
        "rounding_rules": {"supported": ["half_up"]},
        "formal_evidence_status": "verified",
        "formal_quality_status": "pass",
        "unresolved_policy": "block_formal_annual_statistics",
        "rule_records": [{
            "exchange": "SZ", "board": "main", "is_st": False,
            "effective_start": "2020-01-01", "effective_end": None,
            "limit_up_ratio": 0.1, "limit_down_ratio": 0.1,
            "no_limit_flag": False, "tick_size": 0.01,
            "price_precision": 2, "rounding_rule": "half_up",
            "rule_version": "fixture-rule", "source_reference": "fixture://rule",
            "source_name": "fixture", "verified_at": "2026-01-01",
            "evidence_status": "verified",
        }],
        "security_status_records": [{
            "symbol": "000001", "effective_start": "2020-01-01",
            "effective_end": None, "exchange": "SZ", "board": "main",
            "is_st": False, "listing_status": "listed",
            "listing_date": "1991-01-01", "delisting_date": None,
            "no_limit_reason": None, "source_reference": "fixture://status",
            "status_version": "fixture-status", "evidence_status": "verified",
        }],
    }
    path.write_text(
        yaml.safe_dump(content, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _database(
    path: Path,
    *,
    route: str = "raw",
    date: str = "2026-01-05",
    omit: str | None = None,
) -> Path:
    columns = [
        "symbol VARCHAR", "exchange VARCHAR", "trade_date DATE",
        "adjust_type VARCHAR", "open DOUBLE", "high DOUBLE", "low DOUBLE",
        "close DOUBLE", "volume_share DOUBLE",
    ]
    columns = [item for item in columns if not item.startswith(f"{omit} ")]
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            "CREATE TABLE fact_stock_daily(" + ", ".join(columns) + ")"
        )
        names = [item.split()[0] for item in columns]
        values = {
            "symbol": "'000001'", "exchange": "'SZ'",
            "trade_date": f"DATE '{date}'", "adjust_type": f"'{route}'",
            "open": "10", "high": "10", "low": "10", "close": "10",
            "volume_share": "100",
        }
        connection.execute(
            "INSERT INTO fact_stock_daily("
            + ", ".join(names)
            + ") VALUES ("
            + ", ".join(values[name] for name in names)
            + ")"
        )
    return path


def _validate(config: Path, source: Path, output: Path):
    return validate_stage8_inputs(
        config_path=config,
        source_database=source,
        output_database=output,
        start_date=START,
        end_date=END,
    )


def test_validate_only_rejects_empty_and_corrupt_database(tmp_path):
    config = _config(tmp_path / "stage8.yml")
    empty = tmp_path / "empty.duckdb"
    empty.touch()
    corrupt = tmp_path / "corrupt.duckdb"
    corrupt.write_bytes(b"not a duckdb database")
    assert _validate(config, empty, tmp_path / "out1.duckdb")["status"] == "FAILED"
    result = _validate(config, corrupt, tmp_path / "out2.duckdb")
    assert result["status"] == "FAILED"
    assert any("source_database_unreadable" in item for item in result["errors"])


def test_validate_only_rejects_missing_table_and_required_field(tmp_path):
    config = _config(tmp_path / "stage8.yml")
    no_table = tmp_path / "no-table.duckdb"
    with duckdb.connect(str(no_table)):
        pass
    missing = _database(tmp_path / "missing.duckdb", omit="close")
    assert "source_daily_table_missing" in _validate(
        config, no_table, tmp_path / "out1.duckdb"
    )["errors"]
    result = _validate(config, missing, tmp_path / "out2.duckdb")
    assert any("source_columns_missing:close" in item for item in result["errors"])


def test_validate_only_rejects_adjusted_routes_and_empty_date_range(tmp_path):
    config = _config(tmp_path / "stage8.yml")
    for route in ("qfq", "hfq"):
        result = _validate(
            config,
            _database(tmp_path / f"{route}.duckdb", route=route),
            tmp_path / f"{route}-out.duckdb",
        )
        assert result["status"] == "FAILED"
        assert "input_price_route_not_raw" in result["errors"]
    outside = _database(tmp_path / "outside.duckdb", date="2025-01-05")
    result = _validate(config, outside, tmp_path / "outside-out.duckdb")
    assert result["status"] == "BLOCKED"
    assert "no_rows_in_requested_date_range" in result["blockers"]


def test_validate_only_protects_stage7_output_path(tmp_path):
    result = _validate(
        _config(tmp_path / "stage8.yml"),
        _database(tmp_path / "source.duckdb"),
        tmp_path / "akshare_features_stage7.duckdb",
    )
    assert result["status"] == "FAILED"
    assert "output_database_is_protected_stage7_database" in result["errors"]


def test_valid_preflight_is_ready_and_has_no_write_side_effect(tmp_path):
    config = _config(tmp_path / "stage8.yml")
    source = _database(tmp_path / "source.duckdb")
    output = tmp_path / "new-dir" / "stage8.duckdb"
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    result = _validate(config, source, output)
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    assert result["status"] == "READY"
    assert result["input_table"] == "main.fact_stock_daily"
    assert result["raw_row_count"] == 1
    assert before == after
    assert not output.exists()
    assert not output.parent.exists()


def test_verified_rule_with_yaml_null_source_fails_before_output_write(tmp_path):
    config = _config(tmp_path / "stage8.yml")
    content = yaml.safe_load(config.read_text(encoding="utf-8"))
    content["rule_records"][0]["source_reference"] = None
    config.write_text(
        yaml.safe_dump(content, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    source = _database(tmp_path / "source.duckdb")
    output = tmp_path / "stage8.duckdb"

    result = _validate(config, source, output)

    assert result["status"] == "FAILED"
    assert any("source_reference must be a non-empty string" in error for error in result["errors"])
    assert not output.exists()


@pytest.mark.parametrize(
    "mutation,expected_error",
    [
        ({"source_name": None}, "source_name must be a non-empty string"),
        ({"source_reference": None}, "source_reference must be a non-empty string"),
        ({"source_name": "", "source_reference": "   "}, "non-empty string"),
        ({"verified_at": None}, "verified rules require"),
        ({"source_name": 7}, "source_name must be a non-empty string"),
        ({"source_reference": ["fixture"]}, "source_reference must be a non-empty string"),
        ({"source_name": {"value": "fixture"}}, "source_name must be a non-empty string"),
        ({"is_st": "false"}, "is_st must be a YAML boolean"),
        ({"source_referance": "typo"}, "Unknown rule fields"),
    ],
)
def test_invalid_verified_yaml_matrix_fails_before_any_output(
    tmp_path, mutation, expected_error
):
    config = _config(tmp_path / "stage8.yml")
    content = yaml.safe_load(config.read_text(encoding="utf-8"))
    content["rule_records"][0].update(mutation)
    config.write_text(
        yaml.safe_dump(content, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    source = _database(tmp_path / "source.duckdb")
    output = tmp_path / "output" / "stage8.duckdb"

    result = _validate(config, source, output)

    assert result["status"] == "FAILED"
    assert any(expected_error in error for error in result["errors"])
    assert not output.exists()
    assert not output.parent.exists()
    assert not (tmp_path / "reports").exists()


@pytest.mark.parametrize("field", ["source_name", "source_reference"])
def test_missing_verified_yaml_source_field_fails_before_any_output(tmp_path, field):
    config = _config(tmp_path / "stage8.yml")
    content = yaml.safe_load(config.read_text(encoding="utf-8"))
    del content["rule_records"][0][field]
    config.write_text(
        yaml.safe_dump(content, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    source = _database(tmp_path / "source.duckdb")
    output = tmp_path / "stage8.duckdb"

    result = _validate(config, source, output)

    assert result["status"] == "FAILED"
    assert any(field in error for error in result["errors"])
    assert not output.exists()


def test_cli_traceback_requires_explicit_debug():
    base = [
        sys.executable, "run_pipeline.py", "analyze-limit-events",
        "--as-of-date", "not-a-date", "--validate-only",
    ]
    normal = subprocess.run(
        base, cwd=ROOT, capture_output=True, text=True, check=False
    )
    debug = subprocess.run(
        [*base, "--debug"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert normal.returncode == debug.returncode == 1
    assert "Stage 8 error:" in normal.stderr
    assert "Traceback" not in normal.stdout + normal.stderr
    assert "Traceback" in debug.stderr


def test_cli_ready_status_is_json_and_creates_no_output(tmp_path):
    config = _config(tmp_path / "stage8.yml")
    source = _database(tmp_path / "source.duckdb")
    output = tmp_path / "stage8.duckdb"
    result = subprocess.run(
        [
            sys.executable, "run_pipeline.py", "analyze-limit-events",
            "--as-of-date", "2026-01-31", "--start-date", "2026-01-01",
            "--validate-only", "--config", str(config),
            "--source-database", str(source), "--output-database", str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "READY"
    assert not output.exists()
