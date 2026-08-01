from __future__ import annotations

import json
import shutil
from pathlib import Path

import duckdb
import pandas as pd

from akshare_data_test.quality.style_checks import run_stage9_post_write_checks
from akshare_data_test.stage9_build import analyze_stage9
from test_style_features import daily


ROOT = Path(__file__).resolve().parents[1]


def prepare(root: Path):
    (root / "config").mkdir()
    (root / "sql").mkdir()
    shutil.copy2(ROOT / "config/stage9.yml", root / "config/stage9.yml")
    shutil.copy2(ROOT / "sql/stage9_schema.sql", root / "sql/stage9_schema.sql")
    source = root / "source.duckdb"
    frame = daily()
    with duckdb.connect(str(source)) as connection:
        connection.execute("CREATE SCHEMA clean")
        connection.register("daily", frame.drop(columns=["volume_ratio_20", "return_1d"]))
        connection.execute("CREATE TABLE clean.fact_stock_daily AS SELECT * FROM daily")
    return source


def test_full_pipeline_is_idempotent_and_reports_match_database(tmp_path):
    source = prepare(tmp_path)
    output = tmp_path / "stage9.duckdb"
    kwargs = dict(
        root=tmp_path, config_path=tmp_path / "config/stage9.yml",
        input_database=source, output_database=output,
        as_of_date=pd.Timestamp("2026-04-22"), run_id="integration-style",
    )
    first, first_code = analyze_stage9(**kwargs)
    second, second_code = analyze_stage9(**kwargs)
    assert first_code == second_code == 0
    assert first["run_status"] == second["run_status"] == "PASS"
    assert first["publication_status"] == "research_only"
    assert first["stage8_publication_status"] == "not_available"
    assert first["stage8_formal_events_used"] is False
    manifest = json.loads((tmp_path / "reports/stage9_run.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "integration-style"
    assert manifest["feature_row_count"] == 3
    assert manifest["profile_row_count"] == 1
    assert manifest["output_type"] == "fixture"
    with duckdb.connect(str(output), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM feature.stage9_style_feature").fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM analysis.stage9_style_profile").fetchone()[0] == 1
        assert connection.execute("SELECT status FROM quality.stage9_quality_result WHERE run_id='integration-style' AND check_name='database_report_consistent'").fetchone()[0] == "PASS"


def test_dry_run_writes_no_database_or_reports(tmp_path):
    source = prepare(tmp_path)
    report, code = analyze_stage9(
        root=tmp_path, config_path=tmp_path / "config/stage9.yml",
        input_database=source, output_database=tmp_path / "out.duckdb",
        as_of_date=pd.Timestamp("2026-04-22"), run_id="dry-style", dry_run=True,
    )
    assert code == 0 and report["run_status"] == "PASS"
    assert not (tmp_path / "out.duckdb").exists()
    assert not (tmp_path / "reports").exists()


def test_stage8_blocked_database_never_supplies_formal_zero(tmp_path):
    source = prepare(tmp_path)
    stage8 = tmp_path / "stage8.duckdb"
    with duckdb.connect(str(stage8)) as connection:
        connection.execute("CREATE SCHEMA audit; CREATE SCHEMA analysis")
        connection.execute("CREATE TABLE audit.stage8_run(run_id VARCHAR,publication_status VARCHAR,created_at TIMESTAMP)")
        connection.execute("INSERT INTO audit.stage8_run VALUES ('s8','blocked',TIMESTAMP '2026-01-01')")
        connection.execute("CREATE TABLE analysis.fact_limit_event(symbol VARCHAR,event_type VARCHAR,evidence_status VARCHAR,quality_status VARCHAR,run_id VARCHAR)")
        connection.execute("INSERT INTO analysis.fact_limit_event VALUES ('000001','gap_proxy','unresolved','failed','s8')")
    report, code = analyze_stage9(
        root=tmp_path, config_path=tmp_path / "config/stage9.yml",
        input_database=source, output_database=tmp_path / "out.duckdb",
        stage8_database=stage8, as_of_date=pd.Timestamp("2026-04-22"), run_id="blocked-s8",
    )
    assert code == 0 and report["stage8_publication_status"] == "blocked"
    with duckdb.connect(str(tmp_path / "out.duckdb"), read_only=True) as connection:
        row = connection.execute("SELECT stage8_formal_event_frequency,stage8_gap_proxy_frequency,stage8_unresolved_event_frequency FROM feature.stage9_style_feature WHERE window_size=40").fetchone()
    assert row[0] is None and row[1:] == (1.0, 1.0)


def test_report_run_id_tampering_is_detected(tmp_path):
    source = prepare(tmp_path)
    output = tmp_path / "stage9.duckdb"
    report, _ = analyze_stage9(
        root=tmp_path, config_path=tmp_path / "config/stage9.yml",
        input_database=source, output_database=output,
        as_of_date=pd.Timestamp("2026-04-22"), run_id="tamper-style",
    )
    path = tmp_path / "reports/stage9_run.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["run_id"] = "wrong-run"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    checks = run_stage9_post_write_checks(
        output, tmp_path / "reports", run_id="tamper-style",
        expected_feature_rows=3, expected_profile_rows=1,
        expected_config_hash=report["config_hash"],
        checked_at=pd.Timestamp("2026-04-23", tz="UTC"),
    )
    assert checks.loc[checks.check_name.eq("database_report_consistent"), "status"].item() == "FAIL"


def _post_write_status(output, reports, report):
    checks = run_stage9_post_write_checks(
        output, reports, run_id=report["run_id"],
        expected_feature_rows=report["feature_row_count"],
        expected_profile_rows=report["profile_row_count"],
        expected_config_hash=report["config_hash"],
        checked_at=pd.Timestamp("2026-04-23", tz="UTC"),
    )
    row = checks.loc[checks.check_name.eq("database_report_consistent")].iloc[0]
    assert row.severity == "ERROR"
    return row.status


def test_all_published_artifact_tampering_is_detected(tmp_path):
    source = prepare(tmp_path)
    output = tmp_path / "stage9.duckdb"
    report, _ = analyze_stage9(
        root=tmp_path, config_path=tmp_path / "config/stage9.yml",
        input_database=source, output_database=output,
        as_of_date=pd.Timestamp("2026-04-22"), run_id="tamper-all",
    )
    reports = tmp_path / "reports"
    assert _post_write_status(output, reports, report) == "PASS"

    with duckdb.connect(str(output)) as connection:
        original_confidence = connection.execute(
            "SELECT confidence FROM analysis.stage9_style_profile "
            "WHERE run_id='tamper-all' LIMIT 1"
        ).fetchone()[0]
        connection.execute(
            "UPDATE analysis.stage9_style_profile SET confidence=0.123456789 "
            "WHERE run_id='tamper-all'"
        )
    assert _post_write_status(output, reports, report) == "FAIL"
    with duckdb.connect(str(output)) as connection:
        connection.execute(
            "UPDATE analysis.stage9_style_profile SET confidence=? "
            "WHERE run_id='tamper-all'", [original_confidence]
        )
        original_publication = connection.execute(
            "SELECT publication_status FROM audit.stage9_run "
            "WHERE run_id='tamper-all'"
        ).fetchone()[0]
        connection.execute(
            "UPDATE audit.stage9_run SET publication_status='formal' "
            "WHERE run_id='tamper-all'"
        )
    assert _post_write_status(output, reports, report) == "FAIL"
    with duckdb.connect(str(output)) as connection:
        connection.execute(
            "UPDATE audit.stage9_run SET publication_status=? "
            "WHERE run_id='tamper-all'", [original_publication]
        )

    for name, mutate in (
        ("stage9_style_profile.csv", lambda frame: frame.assign(confidence=0.234567891)),
        ("stage9_style_feature_sample.csv", lambda frame: frame.assign(box_width=0.987654321)),
        (
            "stage9_data_quality.csv",
            lambda frame: frame.assign(
                status=frame["status"].mask(frame.index == frame.index[0], "FAIL")
            ),
        ),
    ):
        path = reports / name
        original = path.read_bytes()
        frame = pd.read_csv(path, dtype={"symbol": str, "run_id": str})
        mutate(frame).to_csv(path, index=False, encoding="utf-8-sig")
        assert _post_write_status(output, reports, report) == "FAIL", name
        path.write_bytes(original)

    manifest_path = reports / "stage9_run.json"
    original_manifest = manifest_path.read_bytes()
    for field, value in (
        ("style_distribution", {"伪造风格": 999}),
        ("publication_status", "formal"),
        ("run_id", "wrong-run"),
        ("blocking_reasons", ["forged-blocker"]),
    ):
        manifest = json.loads(original_manifest.decode("utf-8"))
        manifest[field] = value
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert _post_write_status(output, reports, report) == "FAIL", field
        manifest_path.write_bytes(original_manifest)

    markdown_path = reports / "stage9_validation.md"
    original_markdown = markdown_path.read_bytes()
    markdown = original_markdown.decode("utf-8").replace(
        "风格标签不是投资建议，也不构成投资建议。", "该风格标签可直接作为投资建议。"
    )
    assert markdown.encode("utf-8") != original_markdown
    markdown_path.write_text(markdown, encoding="utf-8")
    assert _post_write_status(output, reports, report) == "FAIL"
    markdown_path.write_bytes(original_markdown)


def test_cross_run_history_preserved(tmp_path):
    source = prepare(tmp_path)
    output = tmp_path / "stage9.duckdb"
    common = dict(
        root=tmp_path, config_path=tmp_path / "config/stage9.yml",
        input_database=source, output_database=output,
        as_of_date=pd.Timestamp("2026-04-22"),
    )
    first, first_code = analyze_stage9(**common, run_id="run-one")
    second, second_code = analyze_stage9(**common, run_id="run-two")
    assert first_code == second_code == 0
    with duckdb.connect(str(output), read_only=True) as connection:
        for table in (
            "feature.stage9_style_feature", "analysis.stage9_style_profile",
            "quality.stage9_quality_result", "audit.stage9_run",
        ):
            assert {
                row[0] for row in connection.execute(
                    f"SELECT DISTINCT run_id FROM {table}"
                ).fetchall()
            } == {"run-one", "run-two"}
        latest = connection.execute(
            "SELECT DISTINCT run_id FROM analysis.v_latest_stage9_style_profile"
        ).fetchall()
        assert latest == [("run-two",)]
        assert connection.execute(
            "SELECT status FROM quality.stage9_quality_result "
            "WHERE run_id='run-two' AND check_name='cross_run_history_preserved'"
        ).fetchone()[0] == "PASS"
