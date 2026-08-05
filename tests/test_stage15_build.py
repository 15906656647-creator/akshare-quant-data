from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from akshare_data_test.stage15_build import (
    PROTECTED_OUTPUT_NAMES,
    decide_stage15_status,
    run_stage15_quality_control,
    validate_stage15_inputs,
)


def _run(
    tmp_path: Path,
    *,
    input_database: Path,
    config_path: Path,
    run_id: str = "11111111-1111-4111-8111-111111111111",
    stage8_database: Path | None = None,
    baseline: Path | None = None,
):
    output = (
        tmp_path
        / "database"
        / "stage15"
        / run_id
        / "stage15_quality.duckdb"
    )
    reports = tmp_path / "reports" / "stage15"
    return run_stage15_quality_control(
        root=tmp_path,
        as_of_date=date(2026, 7, 27),
        config_path=config_path,
        input_database=input_database,
        output_database=output,
        reports_dir=reports,
        run_id=run_id,
        stage8_database=stage8_database,
        baseline_path=baseline,
        checked_at=pd.Timestamp("2026-07-27T12:00:00+08:00"),
    )


def test_quality_control_publishes_reports_and_database(
    tmp_path: Path, stage15_test_config: Path, stage15_synthetic_db: Path,
    stage15_elapsed_evidence: None,
):
    report, exit_code = _run(tmp_path, input_database=stage15_synthetic_db, config_path=stage15_test_config)
    assert exit_code == 0
    assert report["status"] == "PASS_WITH_UNAVAILABLE_ITEMS"
    assert report["unavailable_count"] == 6
    assert report["blocked_risk_count"] == 2
    run_id = report["run_id"]
    report_dir = tmp_path / "reports" / "stage15" / run_id
    for name in (
        "quality_check_results.csv",
        "cross_validation.csv",
        "cross_validation.md",
        "risk_log.csv",
        "risk_log.json",
        "quality_summary.json",
    ):
        assert (report_dir / name).is_file()
        assert (report_dir / name).stat().st_size > 0
    checks = pd.read_csv(report_dir / "quality_check_results.csv")
    assert not checks.empty
    risks = pd.read_csv(report_dir / "risk_log.csv")
    assert risks["status"].eq("blocked").any()
    assert risks["risk_id"].nunique() == len(risks)
    cross = pd.read_csv(report_dir / "cross_validation.csv")
    assert len(cross) == 21  # 3 symbols x 7 items
    database = tmp_path / "database" / "stage15" / run_id / "stage15_quality.duckdb"
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM quality.check_result").fetchone()[0] == len(checks)
        assert connection.execute("SELECT count(*) FROM quality.risk_log").fetchone()[0] == len(risks)
        assert connection.execute("SELECT count(*) FROM quality.cross_validation").fetchone()[0] == len(cross)
        assert (
            connection.execute("SELECT status FROM audit.stage15_run").fetchone()[0]
            == "PASS_WITH_UNAVAILABLE_ITEMS"
        )


def test_rerun_with_same_run_id_is_idempotent(
    tmp_path: Path, stage15_test_config: Path, stage15_synthetic_db: Path,
    stage15_elapsed_evidence: None,
):
    first, first_code = _run(tmp_path, input_database=stage15_synthetic_db, config_path=stage15_test_config)
    second, second_code = _run(tmp_path, input_database=stage15_synthetic_db, config_path=stage15_test_config)
    assert first_code == second_code == 0
    assert first["run_id"] == second["run_id"]
    run_id = first["run_id"]
    database = tmp_path / "database" / "stage15" / run_id / "stage15_quality.duckdb"
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM quality.check_result").fetchone()[0] > 0
        assert connection.execute(
            "SELECT count(*) FROM (SELECT run_id, check_name, count(*) c FROM quality.check_result GROUP BY 1, 2 HAVING c > 1)"
        ).fetchone()[0] == 0
    csv_path = tmp_path / "reports" / "stage15" / run_id / "quality_check_results.csv"
    assert csv_path.read_text(encoding="utf-8-sig").count("\n") == 1 + len(
        first["quality_checks"]
    )


def test_ohlc_failure_returns_exit_1(
    tmp_path: Path, stage15_test_config: Path, stage15_synthetic_db: Path,
):
    with duckdb.connect(str(stage15_synthetic_db)) as connection:
        connection.execute(
            "UPDATE fact_stock_daily SET high = 5.0 "
            "WHERE symbol = '002067' AND adjust_type = 'raw' AND trade_date = DATE '2026-07-27'"
        )
    report, exit_code = _run(tmp_path, input_database=stage15_synthetic_db, config_path=stage15_test_config)
    assert exit_code == 1
    assert report["status"] == "FAIL"
    run_id = report["run_id"]
    risks = pd.read_csv(tmp_path / "reports" / "stage15" / run_id / "risk_log.csv")
    assert risks["description"].astype(str).str.contains("ohlc_logic:raw").any()


def test_validate_only_ready(
    tmp_path: Path, stage15_test_config: Path, stage15_synthetic_db: Path,
):
    result = validate_stage15_inputs(
        root=tmp_path,
        config_path=stage15_test_config,
        input_database=stage15_synthetic_db,
        output_database=tmp_path / "out.duckdb",
        as_of_date=date(2026, 7, 27),
    )
    assert result["status"] == "READY"
    assert result["table_counts"]["fact_stock_daily"] == 64


def test_validate_only_missing_input_is_blocked(
    tmp_path: Path, stage15_test_config: Path,
):
    result = validate_stage15_inputs(
        root=tmp_path,
        config_path=stage15_test_config,
        input_database=tmp_path / "missing.duckdb",
        output_database=tmp_path / "out.duckdb",
        as_of_date=date(2026, 7, 27),
    )
    assert result["status"] == "BLOCKED"
    assert any("input database does not exist" in item for item in result["blocking_reasons"])


def test_validate_only_missing_explicit_stage8_is_blocked(
    tmp_path: Path, stage15_test_config: Path, stage15_synthetic_db: Path,
):
    result = validate_stage15_inputs(
        root=tmp_path,
        config_path=stage15_test_config,
        input_database=stage15_synthetic_db,
        output_database=tmp_path / "out.duckdb",
        as_of_date=date(2026, 7, 27),
        stage8_database=tmp_path / "missing_stage8.duckdb",
    )
    assert result["status"] == "BLOCKED"
    assert any("stage8 database does not exist" in item for item in result["blocking_reasons"])


def test_protected_output_rejected(
    tmp_path: Path, stage15_test_config: Path, stage15_synthetic_db: Path,
):
    result = validate_stage15_inputs(
        root=tmp_path,
        config_path=stage15_test_config,
        input_database=stage15_synthetic_db,
        output_database=tmp_path / list(PROTECTED_OUTPUT_NAMES)[0],
        as_of_date=date(2026, 7, 27),
    )
    assert result["status"] == "BLOCKED"
    assert any("output database is protected" in item for item in result["blocking_reasons"])


def test_chinese_path_utf8_support(
    tmp_path: Path, stage15_test_config: Path, stage15_synthetic_db: Path
):
    import shutil
    import yaml

    chinese_root = tmp_path / "中文 路径-阶段15"
    chinese_root.mkdir(parents=True)
    config_dir = chinese_root / "config"
    config_dir.mkdir()
    shutil.copy(stage15_test_config, config_dir / "stage15.yml")
    shutil.copy(ROOT_CONFIG_STAGE10, config_dir / "stage10.yml")
    input_database = chinese_root / "输入_stage5.duckdb"
    shutil.copy(stage15_synthetic_db, input_database)
    report, exit_code = run_stage15_quality_control(
        root=chinese_root,
        as_of_date=date(2026, 7, 27),
        config_path=config_dir / "stage15.yml",
        input_database=input_database,
        output_database=chinese_root / "质量.duckdb",
        reports_dir=chinese_root / "reports" / "stage15",
        run_id="22222222-2222-4222-8222-222222222222",
        checked_at=pd.Timestamp("2026-07-27T12:00:00+08:00"),
    )
    assert exit_code == 0
    assert report["status"] in {"PASS", "WARN", "PASS_WITH_UNAVAILABLE_ITEMS"}
    summary = json.loads(
        (chinese_root / "reports" / "stage15" / report["run_id"] / "quality_summary.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["status"] in {"PASS", "WARN", "PASS_WITH_UNAVAILABLE_ITEMS"}


def _empty_checks() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "run_id",
            "check_name",
            "category",
            "severity",
            "status",
            "observed_value",
            "expected_value",
            "interface_name",
            "message",
            "checked_at",
        ]
    )


def test_decide_stage15_status_precedence():
    checks = _empty_checks()
    cross = pd.DataFrame(
        [
            {
                "run_id": "r",
                "symbol": "002067",
                "check_item": "recent_limit_up_day",
                "observed_value": "unavailable",
                "source_table": "x",
                "as_of_date": pd.Timestamp("2026-07-27").date(),
                "verification_status": "UNAVAILABLE",
                "note": "blocked",
            }
        ]
    )
    risks = pd.DataFrame(
        [
            {
                "risk_id": "a",
                "detected_at": pd.Timestamp("2026-07-27T12:00:00+08:00"),
                "category": "blocked_input",
                "interface_name": "stage8",
                "symbol": "",
                "severity": "warning",
                "description": "no_authoritative_limit_rules",
                "impact": "x",
                "mitigation": "y",
                "status": "blocked",
            }
        ]
    )
    assert decide_stage15_status(checks=checks, cross=cross, risks=risks) == (
        "PASS_WITH_UNAVAILABLE_ITEMS"
    )
    clean_cross = cross.copy()
    clean_cross["verification_status"] = "REVIEW"
    clean_risks = risks.copy()
    clean_risks["status"] = "open"
    assert decide_stage15_status(
        checks=checks, cross=clean_cross, risks=clean_risks
    ) == "PASS"
    failed = checks.copy()
    failed = pd.concat(
        [
            failed,
            pd.DataFrame(
                [
                    {
                        "run_id": "r",
                        "check_name": "ohlc_logic:raw",
                        "category": "logic_error",
                        "severity": "error",
                        "status": "FAIL",
                        "observed_value": "1",
                        "expected_value": "0",
                        "interface_name": "",
                        "message": "bad",
                        "checked_at": pd.Timestamp("2026-07-27T12:00:00+08:00"),
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    assert decide_stage15_status(checks=failed, cross=cross, risks=risks) == "FAIL"
    warned = checks.copy()
    warned = pd.concat(
        [
            warned,
            pd.DataFrame(
                [
                    {
                        "run_id": "r",
                        "check_name": "elapsed",
                        "category": "performance",
                        "severity": "warning",
                        "status": "WARN",
                        "observed_value": "missing",
                        "expected_value": "x",
                        "interface_name": "stock_zh_a_hist",
                        "message": "no evidence",
                        "checked_at": pd.Timestamp("2026-07-27T12:00:00+08:00"),
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    assert decide_stage15_status(
        checks=warned, cross=clean_cross, risks=clean_risks
    ) == "WARN"


ROOT_CONFIG_STAGE10 = Path(__file__).resolve().parents[1] / "config" / "stage10.yml"
