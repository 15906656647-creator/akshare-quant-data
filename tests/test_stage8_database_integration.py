from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd
import yaml

from akshare_data_test.stage8_build import analyze_stage8
from akshare_data_test.quality.limit_event_checks import run_stage8_post_write_checks
from akshare_data_test.stage8_analysis import FORMAL_SUMMARY_COLUMNS
from akshare_data_test.storage.limit_event_repository import (
    EVENT_COLUMNS,
    read_stage8_counts,
)


ROOT = Path(__file__).resolve().parents[1]


def _fixture_config() -> dict:
    return {
        "schema_version": "1.0.0",
        "price_adjust_type": "raw",
        "rounding_rules": {"supported": ["half_up"]},
        "formal_evidence_status": "verified",
        "formal_quality_status": "pass",
        "unresolved_policy": "block_formal_annual_statistics",
        "rule_records": [{
            "exchange": "SZ", "board": "main", "is_st": False,
            "effective_start": "2026-01-01", "effective_end": None,
            "limit_up_ratio": 0.1, "limit_down_ratio": 0.1,
            "no_limit_flag": False, "tick_size": 0.01,
            "price_precision": 2, "rounding_rule": "half_up",
            "rule_version": "fixture-rule", "source_reference": "fixture://rule",
            "source_name": "fixture", "verified_at": "2026-01-01",
            "evidence_status": "verified",
        }],
        "security_status_records": [{
            "symbol": "000001", "effective_start": "2026-01-01",
            "effective_end": None, "exchange": "SZ", "board": "main",
            "is_st": False, "listing_status": "listed",
            "listing_date": "1991-01-01", "delisting_date": None,
            "no_limit_reason": None, "source_reference": "fixture://status",
            "status_version": "fixture-status", "evidence_status": "verified",
        }],
    }


def test_full_stage8_pipeline_is_offline_idempotent_and_report_consistent(tmp_path):
    source = tmp_path / "source.duckdb"
    output = tmp_path / "stage8.duckdb"
    config_path = tmp_path / "stage8.yml"
    (tmp_path / "sql").mkdir()
    (tmp_path / "config").mkdir()
    shutil.copyfile(ROOT / "sql/stage8_schema.sql", tmp_path / "sql/stage8_schema.sql")
    shutil.copyfile(
        ROOT / "config/metric_definition.yml",
        tmp_path / "config/metric_definition.yml",
    )
    with duckdb.connect(str(source)) as connection:
        connection.execute(
            "CREATE TABLE fact_stock_daily("
            "symbol VARCHAR, exchange VARCHAR, trade_date DATE, adjust_type VARCHAR, "
            "open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume_share DOUBLE)"
        )
        connection.execute(
            "INSERT INTO fact_stock_daily VALUES "
            "('000001','SZ',DATE '2025-12-31','raw',9.09,9.09,9.09,9.09,100),"
            "('000001','SZ',DATE '2026-01-02','raw',10,10,10,10,100),"
            "('000001','SZ',DATE '2026-01-05','raw',11,11,11,11,100)"
        )
    config = {
        "schema_version": "1.0.0",
        "price_adjust_type": "raw",
        "rounding_rules": {"supported": ["half_up", "half_even"]},
        "formal_evidence_status": "verified",
        "formal_quality_status": "pass",
        "unresolved_policy": "block_formal_annual_statistics",
        "rule_records": [{
            "exchange": "SZ", "board": "main", "is_st": False,
            "effective_start": "2026-01-01", "effective_end": None,
            "limit_up_ratio": 0.1, "limit_down_ratio": 0.1,
            "no_limit_flag": False, "tick_size": 0.01,
            "price_precision": 2, "rounding_rule": "half_up",
            "rule_version": "fixture-rule", "source_reference": "fixture://rule",
            "source_name": "fixture", "verified_at": "2026-01-01",
            "evidence_status": "verified",
        }],
        "security_status_records": [{
            "symbol": "000001", "effective_start": "2026-01-01",
            "effective_end": None, "exchange": "SZ", "board": "main",
            "is_st": False, "listing_status": "listed",
            "listing_date": "1991-01-01", "delisting_date": None,
            "no_limit_reason": None, "source_reference": "fixture://status",
            "status_version": "fixture-status", "evidence_status": "verified",
        }],
    }
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    kwargs = dict(
        root=tmp_path,
        config_path=config_path,
        source_database=source,
        output_database=output,
        as_of_date=pd.Timestamp("2026-01-05"),
        start_date=pd.Timestamp("2026-01-01"),
        run_id="integration-run",
    )
    first, first_code = analyze_stage8(**kwargs)
    second, second_code = analyze_stage8(**kwargs)
    assert first_code == second_code == 0
    assert first["status"] == second["status"] == "PASS"
    assert first["formal_event_count"] == 2
    assert read_stage8_counts(output) == {
        "observations": 2, "formal_events": 2, "summaries": 1,
    }
    report = json.loads((tmp_path / "reports/stage8_run.json").read_text(encoding="utf-8"))
    assert report["formal_event_count"] == read_stage8_counts(output)["formal_events"]
    assert report["price_adjust_type"] == "raw"
    assert report["quality_checks_total"] >= 12
    assert report["run_id"] == "integration-run"
    assert report["run_status"] == "PASS"
    assert report["publication_status"] == "formal"
    assert report["output_type"] == "fixture"
    assert report["window_start"] == "2026-01-01"
    assert report["window_end"] == "2026-01-05"
    assert report["code_version"]
    assert len(report["config_hash"]) == 64
    sample = pd.read_csv(tmp_path / "reports/stage8_event_sample.csv")
    assert list(sample.columns) == EVENT_COLUMNS
    quality_csv = pd.read_csv(tmp_path / "reports/stage8_data_quality.csv")
    assert set(quality_csv["run_id"]) == {"integration-run"}
    assert len(quality_csv) == len(report["quality_results"])
    markdown = (tmp_path / "reports/stage8_validation.md").read_text(
        encoding="utf-8"
    )
    assert "`integration-run`" in markdown
    with duckdb.connect(str(output), read_only=True) as connection:
        database_quality = connection.execute(
            "SELECT count(*) FROM quality.stage8_quality_result "
            "WHERE run_id = 'integration-run'"
        ).fetchone()[0]
        manifest_json = connection.execute(
            "SELECT manifest_json FROM audit.stage8_run "
            "WHERE run_id = 'integration-run'"
        ).fetchone()[0]
    assert database_quality == len(quality_csv)
    assert json.loads(manifest_json)["run_id"] == report["run_id"]


def test_blocked_run_nulls_formal_results_across_database_and_reports(tmp_path):
    source = tmp_path / "source.duckdb"
    output = tmp_path / "stage8.duckdb"
    config_path = tmp_path / "stage8.yml"
    (tmp_path / "sql").mkdir()
    (tmp_path / "config").mkdir()
    shutil.copyfile(ROOT / "sql/stage8_schema.sql", tmp_path / "sql/stage8_schema.sql")
    shutil.copyfile(
        ROOT / "config/metric_definition.yml",
        tmp_path / "config/metric_definition.yml",
    )
    with duckdb.connect(str(source)) as connection:
        connection.execute(
            "CREATE TABLE fact_stock_daily("
            "symbol VARCHAR, exchange VARCHAR, trade_date DATE, adjust_type VARCHAR, "
            "open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume_share DOUBLE)"
        )
        connection.execute(
            "INSERT INTO fact_stock_daily VALUES "
            "('000001','SZ',DATE '2025-12-31','raw',10,10,10,10,100),"
            "('000001','SZ',DATE '2026-01-02','raw',11,11,11,11,100),"
            "('000001','SZ',DATE '2026-01-05','raw',11,11,11,11,0),"
            "('000001','SZ',DATE '2026-01-06','raw',12,12,12,12,100)"
        )
    config = {
        "schema_version": "1.0.0",
        "price_adjust_type": "raw",
        "rounding_rules": {"supported": ["half_up"]},
        "formal_evidence_status": "verified",
        "formal_quality_status": "pass",
        "unresolved_policy": "block_formal_annual_statistics",
        "rule_records": [{
            "exchange": "SZ", "board": "main", "is_st": False,
            "effective_start": "2026-01-01", "effective_end": None,
            "limit_up_ratio": 0.1, "limit_down_ratio": 0.1,
            "no_limit_flag": False, "tick_size": 0.01,
            "price_precision": 2, "rounding_rule": "half_up",
            "rule_version": "fixture-rule", "source_reference": "fixture://rule",
            "source_name": "fixture", "verified_at": "2026-01-01",
            "evidence_status": "verified",
        }],
        "security_status_records": [{
            "symbol": "000001", "effective_start": "2026-01-01",
            "effective_end": None, "exchange": "SZ", "board": "main",
            "is_st": False, "listing_status": "listed",
            "listing_date": "1991-01-01", "delisting_date": None,
            "no_limit_reason": None, "source_reference": "fixture://status",
            "status_version": "fixture-status", "evidence_status": "verified",
        }],
    }
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    report, exit_code = analyze_stage8(
        root=tmp_path,
        config_path=config_path,
        source_database=source,
        output_database=output,
        as_of_date=pd.Timestamp("2026-01-06"),
        start_date=pd.Timestamp("2026-01-01"),
        run_id="blocked-integration-run",
    )

    assert exit_code == 2
    assert report["publication_status"] == "blocked"
    assert report["formal_event_count"] is None
    assert report["detected_formal_event_count"] is None
    json_report = json.loads(
        (tmp_path / "reports/stage8_run.json").read_text(encoding="utf-8")
    )
    assert json_report["formal_event_count"] is None
    assert json_report["detected_formal_event_count"] is None
    assert all(
        row[field] is None
        for row in json_report["annual_summary"]
        for field in FORMAL_SUMMARY_COLUMNS
    )
    annual_csv = pd.read_csv(tmp_path / "reports/stage8_annual_event_summary.csv")
    assert annual_csv[FORMAL_SUMMARY_COLUMNS].isna().all().all()
    assert annual_csv["publication_status"].eq("blocked").all()
    markdown = (tmp_path / "reports/stage8_validation.md").read_text(encoding="utf-8")
    assert "not_calculated" in markdown
    assert all(
        f"{field}: not_calculated" in markdown
        for field in FORMAL_SUMMARY_COLUMNS
    )

    with duckdb.connect(str(output)) as connection:
        summary_row = connection.execute(
            "SELECT limit_up_count, limit_down_count, "
            "avg_next_open_return_after_limit_up, "
            "avg_next_close_return_after_limit_up, "
            "avg_forward_3d_return_after_limit_up, "
            "avg_forward_5d_return_after_limit_up, "
            "avg_forward_10d_return_after_limit_up, next_day_gap_up_ratio, "
            "continued_limit_ratio, formal_event_count, "
            "publication_status FROM analysis.limit_event_annual_summary "
            "WHERE run_id = 'blocked-integration-run'"
        ).fetchone()
        audit_row = connection.execute(
            "SELECT formal_event_count, publication_status "
            "FROM audit.stage8_run WHERE run_id = 'blocked-integration-run'"
        ).fetchone()
        consistency_status = connection.execute(
            "SELECT status FROM quality.stage8_quality_result "
            "WHERE run_id = 'blocked-integration-run' "
            "AND check_name = 'database_report_consistent'"
        ).fetchone()[0]
        connection.execute(
            "UPDATE analysis.limit_event_annual_summary SET formal_event_count = 0 "
            "WHERE run_id = 'blocked-integration-run'"
        )
    assert all(value is None for value in summary_row[:-1])
    assert summary_row[-1] == "blocked"
    assert audit_row == (None, "blocked")
    assert consistency_status == "PASS"

    tamper_check = run_stage8_post_write_checks(
        output,
        run_id="blocked-integration-run",
        expected_event_rows=3,
        expected_summary_rows=1,
        expected_formal_events=1,
        expected_publication_status="blocked",
        expected_report_formal_event_count=None,
        checked_at=pd.Timestamp("2026-01-07", tz="UTC"),
    )
    assert tamper_check.loc[
        tamper_check["check_name"].eq("database_report_consistent"), "status"
    ].item() == "FAIL"


def test_pipeline_rejects_official_limits_with_null_source_field(tmp_path):
    source = tmp_path / "source.duckdb"
    output = tmp_path / "stage8.duckdb"
    config_path = tmp_path / "stage8.yml"
    (tmp_path / "sql").mkdir()
    (tmp_path / "config").mkdir()
    shutil.copyfile(ROOT / "sql/stage8_schema.sql", tmp_path / "sql/stage8_schema.sql")
    shutil.copyfile(
        ROOT / "config/metric_definition.yml",
        tmp_path / "config/metric_definition.yml",
    )
    config_path.write_text(
        yaml.safe_dump(_fixture_config(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    with duckdb.connect(str(source)) as connection:
        connection.execute(
            "CREATE TABLE fact_stock_daily("
            "symbol VARCHAR, exchange VARCHAR, trade_date DATE, adjust_type VARCHAR, "
            "open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume_share DOUBLE, "
            "limit_up_price DOUBLE, limit_down_price DOUBLE, "
            "official_limit_source_name VARCHAR, "
            "official_limit_source_reference VARCHAR, "
            "official_limit_source_version VARCHAR, "
            "official_limit_evidence_status VARCHAR, "
            "official_limit_verified_at TIMESTAMP, official_limit_fetched_at TIMESTAMP, "
            "official_limit_symbol VARCHAR, official_limit_trade_date DATE)"
        )
        connection.execute(
            "INSERT INTO fact_stock_daily VALUES "
            "('000001','SZ',DATE '2025-12-31','raw',10,10,10,10,100,"
            "NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL),"
            "('000001','SZ',DATE '2026-01-02','raw',10.8,10.8,10.8,10.8,100,"
            "10.8,9.2,'fixture',NULL,'v1','verified',"
            "TIMESTAMP '2026-01-01',TIMESTAMP '2026-01-01','000001',DATE '2026-01-02')"
        )

    report, exit_code = analyze_stage8(
        root=tmp_path,
        config_path=config_path,
        source_database=source,
        output_database=output,
        as_of_date=pd.Timestamp("2026-01-02"),
        start_date=pd.Timestamp("2026-01-01"),
        run_id="missing-official-source-run",
    )

    assert exit_code == 0
    assert report["formal_event_count"] == 0
    with duckdb.connect(str(output), read_only=True) as connection:
        event = connection.execute(
            "SELECT event_type, detection_method, official_limit_rejection_reason "
            "FROM analysis.fact_limit_event "
            "WHERE run_id = 'missing-official-source-run'"
        ).fetchone()
    assert event == (
        "none",
        "theoretical_decimal",
        "official_limit_unverified",
    )


def _run_orchestrated_fixture(
    root: Path,
    *,
    rows: list[tuple],
    run_id: str,
    config: dict | None = None,
):
    (root / "sql").mkdir()
    (root / "config").mkdir()
    shutil.copyfile(ROOT / "sql/stage8_schema.sql", root / "sql/stage8_schema.sql")
    shutil.copyfile(
        ROOT / "config/metric_definition.yml",
        root / "config/metric_definition.yml",
    )
    config_path = root / "stage8.yml"
    config_path.write_text(
        yaml.safe_dump(config or _fixture_config(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    source = root / "source.duckdb"
    output = root / "stage8.duckdb"
    with duckdb.connect(str(source)) as connection:
        connection.execute(
            "CREATE TABLE fact_stock_daily("
            "symbol VARCHAR, exchange VARCHAR, trade_date DATE, adjust_type VARCHAR, "
            "open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume_share DOUBLE)"
        )
        connection.executemany(
            "INSERT INTO fact_stock_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
        )
    report, exit_code = analyze_stage8(
        root=root,
        config_path=config_path,
        source_database=source,
        output_database=output,
        as_of_date=pd.Timestamp("2026-01-10"),
        start_date=pd.Timestamp("2026-01-01"),
        run_id=run_id,
    )
    return report, exit_code, output


def test_pure_mutual_exclusion_conflict_is_blocked_end_to_end(tmp_path):
    config = _fixture_config()
    config["rule_records"][0].update(tick_size=5, price_precision=0)
    report, exit_code, output = _run_orchestrated_fixture(
        tmp_path,
        run_id="pure-conflict",
        config=config,
        rows=[
            ("000001", "SZ", "2025-12-31", "raw", 10, 10, 10, 10, 100),
            ("000001", "SZ", "2026-01-02", "raw", 10, 10, 10, 10, 100),
        ],
    )
    assert exit_code == 2
    assert report["run_status"] == "BLOCKED"
    assert report["publication_status"] == "blocked"
    assert report["formal_event_count"] is None
    assert all(
        row[field] is None
        for row in report["annual_summary"]
        for field in FORMAL_SUMMARY_COLUMNS
    )
    with duckdb.connect(str(output), read_only=True) as connection:
        assert connection.execute(
            "SELECT event_type, evidence_status, quality_status "
            "FROM analysis.fact_limit_event WHERE run_id='pure-conflict'"
        ).fetchone() == ("unresolved", "unresolved", "failed")
        assert connection.execute(
            "SELECT count(*) FROM analysis.v_formal_limit_event "
            "WHERE run_id='pure-conflict'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT status FROM quality.stage8_quality_result "
            "WHERE run_id='pure-conflict' "
            "AND check_name='formal_event_mutual_exclusion'"
        ).fetchone()[0] == "FAIL"


def test_formal_zero_event_run_is_distinct_from_not_calculated(tmp_path):
    report, exit_code, output = _run_orchestrated_fixture(
        tmp_path,
        run_id="formal-zero",
        rows=[
            ("000001", "SZ", "2025-12-31", "raw", 10, 10, 10, 10, 100),
            ("000001", "SZ", "2026-01-02", "raw", 10.5, 10.5, 10.5, 10.5, 100),
        ],
    )
    assert exit_code == 0
    assert report["run_status"] == "PASS"
    assert report["publication_status"] == "formal"
    assert report["formal_event_count"] == 0
    row = report["annual_summary"][0]
    assert row["limit_up_count"] == row["limit_down_count"] == 0
    assert row["formal_event_count"] == 0
    for field in FORMAL_SUMMARY_COLUMNS:
        if field not in {"limit_up_count", "limit_down_count", "formal_event_count"}:
            assert row[field] is None
    with duckdb.connect(str(output), read_only=True) as connection:
        assert connection.execute(
            "SELECT publication_status, formal_event_count "
            "FROM analysis.limit_event_annual_summary WHERE run_id='formal-zero'"
        ).fetchone() == ("formal", 0)


def test_report_side_tampering_is_detected_across_all_artifacts(tmp_path):
    config = _fixture_config()
    config["rule_records"][0].update(tick_size=5, price_precision=0)
    report, _, output = _run_orchestrated_fixture(
        tmp_path,
        run_id="artifact-tamper",
        config=config,
        rows=[
            ("000001", "SZ", "2025-12-31", "raw", 10, 10, 10, 10, 100),
            ("000001", "SZ", "2026-01-02", "raw", 10, 10, 10, 10, 100),
        ],
    )
    reports = tmp_path / "reports"

    def check(database: Path, report_dir: Path) -> str:
        quality = run_stage8_post_write_checks(
            database,
            run_id="artifact-tamper",
            expected_event_rows=1,
            expected_summary_rows=1,
            expected_formal_events=0,
            expected_publication_status="blocked",
            expected_report_formal_event_count=None,
            checked_at=pd.Timestamp("2026-01-11", tz="UTC"),
            reports_dir=report_dir,
        )
        return quality.loc[
            quality["check_name"].eq("database_report_consistent"), "status"
        ].item()

    assert check(output, reports) == "PASS"

    def json_mutation(path: Path, field: str, value: object) -> None:
        data = json.loads(path.read_text(encoding="utf-8"))
        data[field] = value
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    mutations = {
        "json_formal_count": lambda d: json_mutation(
            d / "stage8_run.json", "formal_event_count", 1
        ),
        "json_publication": lambda d: json_mutation(
            d / "stage8_run.json", "publication_status", "formal"
        ),
        "json_run_id": lambda d: json_mutation(
            d / "stage8_run.json", "run_id", "wrong-run"
        ),
        "csv_formal_count": lambda d: _tamper_csv(
            d / "stage8_annual_event_summary.csv", "formal_event_count", 1
        ),
        "csv_return": lambda d: _tamper_csv(
            d / "stage8_annual_event_summary.csv",
            "avg_next_close_return_after_limit_up",
            0.0909,
        ),
        "csv_ratio": lambda d: _tamper_csv(
            d / "stage8_annual_event_summary.csv", "next_day_gap_up_ratio", 1.0
        ),
        "quality_run_id": lambda d: _tamper_csv(
            d / "stage8_data_quality.csv", "run_id", "wrong-run"
        ),
        "markdown_run_id": lambda d: (d / "stage8_validation.md").write_text(
            (d / "stage8_validation.md")
            .read_text(encoding="utf-8")
            .replace("artifact-tamper", "wrong-run"),
            encoding="utf-8",
        ),
    }
    for name, mutate in mutations.items():
        case_reports = tmp_path / name
        shutil.copytree(reports, case_reports)
        mutate(case_reports)
        assert check(output, case_reports) == "FAIL", name


def test_blocked_conflict_cli_is_nonzero_and_uses_only_temp_artifacts(tmp_path):
    config = _fixture_config()
    config["rule_records"][0].update(tick_size=5, price_precision=0)
    _, _, _ = _run_orchestrated_fixture(
        tmp_path,
        run_id="prepare-cli-source",
        config=config,
        rows=[
            ("000001", "SZ", "2025-12-31", "raw", 10, 10, 10, 10, 100),
            ("000001", "SZ", "2026-01-02", "raw", 10, 10, 10, 10, 100),
        ],
    )
    shutil.copytree(ROOT / "src", tmp_path / "src")
    shutil.copyfile(ROOT / "run_pipeline.py", tmp_path / "run_pipeline.py")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(tmp_path / "src")
    result = subprocess.run(
        [
            sys.executable,
            "run_pipeline.py",
            "analyze-limit-events",
            "--config",
            str(tmp_path / "stage8.yml"),
            "--source-database",
            str(tmp_path / "source.duckdb"),
            "--output-database",
            str(tmp_path / "cli-stage8.duckdb"),
            "--as-of-date",
            "2026-01-10",
            "--start-date",
            "2026-01-01",
            "--run-id",
            "cli-conflict",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Stage 8 limit-event analysis: BLOCKED" in result.stdout
    assert "publication_status: blocked" in result.stdout
    assert "formal_events: None" in result.stdout
    manifest = json.loads(
        (tmp_path / "reports/stage8_run.json").read_text(encoding="utf-8")
    )
    assert manifest["run_id"] == "cli-conflict"
    assert manifest["formal_event_count"] is None


def _tamper_csv(path: Path, field: str, value: object) -> None:
    frame = pd.read_csv(path)
    frame.loc[0, field] = value
    frame.to_csv(path, index=False)
