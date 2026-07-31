from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from akshare_data_test.quality.limit_event_checks import (
    run_stage8_post_write_checks,
    run_stage8_quality_checks,
)
from akshare_data_test.stage8_analysis import decide_publication
from akshare_data_test.storage.limit_event_repository import upsert_stage8_results
from test_limit_event_repository import frames
from test_limit_rules import rule, status


ROOT = Path(__file__).resolve().parents[1]


def _quality(routes: set[str] | None = None):
    observations, summary, _, _ = frames()
    quality = run_stage8_quality_checks(
        observations,
        summary,
        run_id="repo-run",
        created_at=pd.Timestamp("2026-07-27T00:00:00Z"),
        input_price_routes={"raw"} if routes is None else routes,
    )
    return observations, summary, quality


def _result(quality: pd.DataFrame, name: str):
    return quality.loc[quality["check_name"].eq(name)].iloc[0]


def test_actual_price_route_has_pass_and_fail_scenarios():
    _, _, passed = _quality({"raw"})
    _, _, failed = _quality({"qfq"})
    assert _result(passed, "input_price_route_raw")["status"] == "PASS"
    assert _result(failed, "input_price_route_raw")["status"] == "FAIL"


def test_unresolved_and_coverage_are_measured_and_block_publication():
    observations, _, quality = _quality()
    unresolved = _result(quality, "unresolved_count")
    coverage = _result(quality, "rule_coverage")
    assert unresolved["numerator"] == 1
    assert unresolved["status"] == "FAIL"
    assert coverage["denominator"] == 2
    assert coverage["status"] == "PASS"
    decision = decide_publication(observations, quality)
    assert decision.publication_status == "blocked"


def test_missing_rule_version_fails_measured_coverage():
    observations, summary, _, _ = frames()
    observations.loc[1, "rule_version"] = None
    quality = run_stage8_quality_checks(
        observations,
        summary,
        run_id="repo-run",
        created_at=pd.Timestamp("2026-07-27T00:00:00Z"),
        input_price_routes={"raw"},
    )
    coverage = _result(quality, "rule_coverage")
    assert coverage["numerator"] == 1
    assert coverage["denominator"] == 2
    assert coverage["status"] == "FAIL"


def test_warning_does_not_behave_as_error():
    observations, _, quality = _quality()
    warning = _result(quality, "forward_return_completeness")
    assert warning["severity"] == "WARNING"
    assert warning["status"] == "FAIL"
    errors = quality.loc[quality["severity"].eq("ERROR")].copy()
    errors["status"] = "PASS"
    decision = decide_publication(
        observations.loc[observations["event_type"].eq("limit_up")],
        pd.concat([errors, warning.to_frame().T], ignore_index=True),
    )
    assert not any(
        item.startswith("quality_error:forward_return_completeness")
        for item in decision.blocking_reasons
    )


def test_abnormal_return_range_fails():
    observations, summary, _, _ = frames()
    observations.loc[1, "forward_3d_return"] = 11.0
    quality = run_stage8_quality_checks(
        observations,
        summary,
        run_id="repo-run",
        created_at=pd.Timestamp("2026-07-27T00:00:00Z"),
        input_price_routes={"raw"},
    )
    assert _result(quality, "return_range_valid")["status"] == "FAIL"


def test_post_write_database_mismatch_is_detected(tmp_path):
    database = tmp_path / "stage8-quality.duckdb"
    observations, summary, quality, run = frames()
    upsert_stage8_results(
        database_path=database,
        schema_sql_path=ROOT / "sql/stage8_schema.sql",
        rules=[rule()],
        statuses=[status()],
        observations=observations,
        summary=summary,
        quality=quality,
        run=run,
    )
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "DELETE FROM analysis.fact_limit_event "
            "WHERE run_id='repo-run' AND trade_date = "
            "(SELECT min(trade_date) FROM analysis.fact_limit_event)"
        )
    post = run_stage8_post_write_checks(
        database,
        run_id="repo-run",
        expected_event_rows=len(observations),
        expected_summary_rows=len(summary),
        expected_formal_events=1,
        checked_at=pd.Timestamp("2026-07-27T00:00:00Z"),
    )
    assert _result(post, "database_report_consistent")["status"] == "FAIL"


def test_each_prewrite_quality_check_has_data_driven_opposite_scenario():
    observations, summary, _, _ = frames()

    def calculate(
        changed_observations=observations,
        changed_summary=summary,
        routes={"raw"},
    ):
        return run_stage8_quality_checks(
            changed_observations,
            changed_summary,
            run_id="repo-run",
            created_at=pd.Timestamp("2026-07-27T00:00:00Z"),
            input_price_routes=routes,
        )

    baseline = calculate()
    expected = {
        "input_price_route_raw": "PASS",
        "event_primary_key_unique": "PASS",
        "summary_primary_key_unique": "PASS",
        "formal_event_mutual_exclusion": "PASS",
        "unresolved_count": "FAIL",
        "rule_coverage": "PASS",
        "security_status_coverage": "PASS",
        "official_or_theoretical_evidence_complete": "PASS",
        "theoretical_limit_fields_complete": "PASS",
        "event_date_order_valid": "PASS",
        "forbidden_formal_event_type": "PASS",
        "forward_return_completeness": "FAIL",
        "return_range_valid": "PASS",
        "run_id_consistent": "PASS",
    }
    assert {name: _result(baseline, name)["status"] for name in expected} == expected

    scenarios: dict[str, pd.DataFrame] = {}
    scenarios["input_price_route_raw"] = calculate(routes={"hfq"})
    scenarios["event_primary_key_unique"] = calculate(
        pd.concat([observations, observations.iloc[[1]]], ignore_index=True)
    )
    scenarios["summary_primary_key_unique"] = calculate(
        observations, pd.concat([summary, summary], ignore_index=True)
    )
    conflict = observations.copy()
    conflict.loc[1, "resolution_reason"] = "mutual_exclusion_conflict"
    scenarios["formal_event_mutual_exclusion"] = calculate(conflict)
    scenarios["unresolved_count"] = calculate(observations.iloc[[1]].copy())
    missing_rule = observations.copy()
    missing_rule.loc[1, "rule_version"] = None
    scenarios["rule_coverage"] = calculate(missing_rule)
    missing_status = observations.copy()
    missing_status.loc[1, "security_status_version"] = None
    scenarios["security_status_coverage"] = calculate(missing_status)
    incomplete_evidence = observations.copy()
    incomplete_evidence.loc[1, "matched_limit_price"] = None
    scenarios["official_or_theoretical_evidence_complete"] = calculate(
        incomplete_evidence
    )
    incomplete_theoretical = observations.copy()
    incomplete_theoretical.loc[1, "unrounded_limit_up_price"] = None
    scenarios["theoretical_limit_fields_complete"] = calculate(
        incomplete_theoretical
    )
    bad_order = observations.copy()
    bad_order.loc[0, "next_trade_date"] = bad_order.loc[0, "trade_date"]
    scenarios["event_date_order_valid"] = calculate(bad_order)
    forbidden = observations.copy()
    forbidden.loc[0, "event_type"] = "candidate"
    forbidden.loc[0, ["evidence_status", "quality_status"]] = ["verified", "pass"]
    scenarios["forbidden_formal_event_type"] = calculate(forbidden)
    complete = observations.copy()
    complete["forward_sample_status"] = "complete"
    scenarios["forward_return_completeness"] = calculate(complete)
    abnormal = observations.copy()
    abnormal.loc[1, "forward_3d_return"] = 11.0
    scenarios["return_range_valid"] = calculate(abnormal)
    wrong_run = observations.copy()
    wrong_run.loc[1, "run_id"] = "other-run"
    scenarios["run_id_consistent"] = calculate(wrong_run)

    for check_name, quality in scenarios.items():
        assert (
            _result(quality, check_name)["status"] != expected[check_name]
        ), check_name


def test_post_write_checks_have_pass_scenario(tmp_path):
    database = tmp_path / "stage8-quality-pass.duckdb"
    observations, summary, quality, run = frames()
    upsert_stage8_results(
        database_path=database,
        schema_sql_path=ROOT / "sql/stage8_schema.sql",
        rules=[rule()],
        statuses=[status()],
        observations=observations,
        summary=summary,
        quality=quality,
        run=run,
    )
    result = run_stage8_post_write_checks(
        database,
        run_id="repo-run",
        expected_event_rows=2,
        expected_summary_rows=1,
        expected_formal_events=1,
        checked_at=pd.Timestamp("2026-07-27T00:00:00Z"),
    )
    assert set(result["status"]) == {"PASS"}
