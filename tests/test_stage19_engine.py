from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pandas as pd

from akshare_data_test.limit_rules import LimitRule, SecurityStatus
from akshare_data_test.stage19_engine import (
    blocked_statistics, build_candidates, coverage_matrix, eligible_official_events,
    formal_statistics, release_gate,
)
from akshare_data_test.stage19_build import _persist


ROOT = Path(__file__).resolve().parents[1]


def rule(**overrides):
    values = dict(exchange="SZ", board="main", is_st=False,
        effective_start=date(2020, 1, 1), effective_end=None,
        limit_up_ratio=Decimal("0.10"), limit_down_ratio=Decimal("0.10"),
        no_limit_flag=False, tick_size=Decimal("0.01"), price_precision=2,
        rounding_rule="half_up", rule_version="r1", source_reference="fixture://rule",
        source_name="fixture", verified_at=date(2026, 7, 27), evidence_status="verified")
    values.update(overrides)
    return LimitRule(**values)


def status(**overrides):
    values = dict(symbol="000001", effective_start=date(2020, 1, 1), effective_end=None,
        exchange="SZ", board="main", is_st=False, listing_status="listed",
        listing_date=date(1991, 1, 1), delisting_date=None, no_limit_reason=None,
        source_reference="fixture://status", status_version="s1", evidence_status="verified",
        review_status="approved", reviewer="fixture")
    values.update(overrides)
    return SecurityStatus(**values)


def bars(symbol="000001"):
    closes = [10.0, 11.0, 12.1, 12.0, 13.2, 13.0, 14.3, 14.0, 15.4, 15.0, 16.5, 16.0]
    return pd.DataFrame({"symbol": symbol, "trade_date": pd.bdate_range("2026-01-02", periods=len(closes)),
        "adjust_type": "raw", "open": closes, "high": [x * 1.01 for x in closes],
        "low": [x * .99 for x in closes], "close": closes, "volume_share": 100})


def test_unknown_st_is_counted_and_never_treated_as_false():
    matrix = coverage_matrix([status(is_st=None)], ["000001"], date(2026, 1, 2), date(2026, 1, 2))
    assert matrix.loc[matrix.status_type.eq("ST"), "unknown_days"].item() == 1


def test_missing_status_produces_full_gap_matrix():
    matrix = coverage_matrix([], ["000001"], date(2026, 1, 1), date(2026, 1, 3))
    assert matrix["gap_days"].sum() == 6


def test_overlap_is_machine_visible():
    statuses = [status(effective_end=date(2026, 1, 3)), status(effective_start=date(2026, 1, 2), status_version="s2")]
    matrix = coverage_matrix(statuses, ["000001"], date(2026, 1, 2), date(2026, 1, 2))
    assert matrix["overlap_or_conflict_days"].sum() == 2


def test_release_gate_requires_all_g1_to_g9():
    coverage = coverage_matrix([status()], ["000001"], date(2026, 1, 2), date(2026, 1, 2))
    gate = release_gate(coverage=coverage,
        rule_result={"status": "READY", "review_status": "approved"},
        status_result={"status": "READY", "review_status": "approved"},
        stage8_rebuild_pass=True, s15_14_pass=True)
    assert gate["formal_event_release"]["status"] == "PASS"
    assert set(gate["formal_event_release"]["checks"]) == {f"G{i}" for i in range(1, 10)}


def test_waiver_cannot_satisfy_manual_review_gate():
    coverage = coverage_matrix([status()], ["000001"], date(2026, 1, 2), date(2026, 1, 2))
    gate = release_gate(coverage=coverage,
        rule_result={"status": "READY", "review_status": "approved_with_waiver"},
        status_result={"status": "READY", "review_status": "approved"},
        stage8_rebuild_pass=True, s15_14_pass=True)
    assert gate["formal_event_release"]["checks"]["G4"]["status"] == "BLOCKED"


def test_blocked_aggregates_are_null_never_zero():
    frame = blocked_statistics(["000001"], date(2025, 1, 1), date(2026, 1, 1), "run", ["G1:x"])
    assert frame["value"].isna().all()
    assert frame["availability_status"].eq("BLOCKED").all()


def test_candidate_layer_preserves_missing_status_blocker():
    output = build_candidates(bars(), [rule()], [], run_id="run", created_at=pd.Timestamp("2026-01-20T00:00:00Z"))
    assert output["event_type"].eq("unresolved").all()
    assert output.iloc[1]["resolution_reason"] == "missing_security_status"


def test_streaks_and_forward_excursions_use_symbol_trading_sequence():
    output = build_candidates(bars(), [rule()], [status()], run_id="run", created_at=pd.Timestamp("2026-01-20T00:00:00Z"))
    assert output.iloc[2]["consecutive_limit_up_count"] == 2
    assert pd.notna(output.iloc[1]["mfe_3d"])
    assert pd.notna(output.iloc[1]["mae_3d"])


def test_insufficient_forward_window_remains_null():
    output = build_candidates(bars().iloc[:3], [rule()], [status()], run_id="run", created_at=pd.Timestamp("2026-01-20T00:00:00Z"))
    assert pd.isna(output.iloc[-1]["forward_3d_return"])
    assert pd.isna(output.iloc[-1]["mfe_3d"])


def test_symbol_isolation_for_next_day_metrics():
    frame = pd.concat([bars("000001").iloc[:2], bars("000002").iloc[:2]], ignore_index=True)
    statuses = [status(), status(symbol="000002", status_version="s2")]
    output = build_candidates(frame, [rule()], statuses, run_id="run", created_at=pd.Timestamp("2026-01-20T00:00:00Z"))
    first_symbol_last = output.loc[output.symbol.eq("000001")].iloc[-1]
    assert pd.isna(first_symbol_last["next_open_return_vs_event_close"])


def pass_gate():
    return {"formal_event_release": {"status": "PASS", "blocked_reasons": [],
        "checks": {f"G{i}": {"status": "PASS", "reason": ""} for i in range(1, 10)}}}


def blocked_gate():
    gate = pass_gate()
    gate["formal_event_release"]["status"] = "BLOCKED"
    gate["formal_event_release"]["checks"]["G1"] = {"status": "BLOCKED", "reason": "fixture blocker"}
    gate["formal_event_release"]["blocked_reasons"] = ["G1:fixture blocker"]
    return gate


def synthetic_candidates(run_id="release-test"):
    common = {"run_id": run_id, "symbol": "000001", "rule_version": "r1",
        "security_status_version": "s1", "detection_method": "theoretical_decimal",
        "evidence_status": "verified", "quality_status": "pass", "resolution_reason": "resolved",
        "next_open_return_vs_event_close": 0.01, "next_close_return": 0.02,
        "next_day_continued_limit": False, "forward_3d_return": 0.03,
        "forward_5d_return": 0.05, "forward_10d_return": 0.10,
        "forward_sample_status": "complete",
        "consecutive_limit_up_count": 0, "consecutive_limit_down_count": 0,
        "created_at": pd.Timestamp("2026-01-20T00:00:00Z")}
    up = dict(common, trade_date=pd.Timestamp("2026-01-05"), event_type="limit_up",
              consecutive_limit_up_count=1)
    down = dict(common, trade_date=pd.Timestamp("2026-01-06"), event_type="limit_down",
                consecutive_limit_down_count=1, next_day_continued_limit=True)
    unresolved = dict(common, trade_date=pd.Timestamp("2026-01-07"), event_type="unresolved",
                      evidence_status="unresolved", quality_status="failed",
                      resolution_reason="missing_security_status", rule_version=None)
    return pd.DataFrame([up, down, unresolved])


def test_pass_gate_publishes_only_resolved_limit_events():
    candidates = synthetic_candidates()
    official = eligible_official_events(candidates, pass_gate())
    assert official["event_type"].tolist() == ["limit_up", "limit_down"]
    assert not official["event_type"].eq("unresolved").any()


def test_blocked_gate_cannot_be_bypassed_by_eligible_candidate():
    assert eligible_official_events(synthetic_candidates(), blocked_gate()).empty


def test_formal_statistics_are_computed_from_official_events():
    official = eligible_official_events(synthetic_candidates(), pass_gate())
    result = formal_statistics(official, ["000001"], date(2025, 1, 1), date(2026, 1, 1), "release-test")
    values = result.set_index("metric_name")["value"]
    assert values["limit_up_count"] == 1
    assert values["limit_down_count"] == 1
    assert values["max_limit_up_streak"] == 1
    assert values["max_limit_down_streak"] == 1
    assert values["avg_next_open_return"] == 0.01
    assert values["forward_10d_return"] == 0.10
    assert result["availability_status"].eq("AVAILABLE").all()


def test_no_limit_up_is_a_valid_zero_but_missing_returns_are_unavailable():
    official = eligible_official_events(synthetic_candidates(), pass_gate())
    official = official.loc[official.event_type.eq("limit_down")].copy()
    official["forward_10d_return"] = None
    result = formal_statistics(official, ["000001", "000002"], date(2025, 1, 1), date(2026, 1, 1), "release-test")
    first = result.loc[result.symbol.eq("000001")].set_index("metric_name")
    empty = result.loc[result.symbol.eq("000002")].set_index("metric_name")
    assert first.loc["limit_up_count", "value"] == 0
    assert first.loc["limit_up_count", "availability_status"] == "AVAILABLE"
    assert pd.isna(first.loc["forward_10d_return", "value"])
    assert first.loc["forward_10d_return", "availability_status"] == "UNAVAILABLE"
    assert empty.loc["limit_up_count", "value"] == 0
    assert pd.isna(empty.loc["avg_next_open_return", "value"])


def test_persist_pass_idempotency_and_gate_transitions_clear_stale_rows(tmp_path):
    run_id = "release-transition"
    candidates = synthetic_candidates(run_id)
    official = eligible_official_events(candidates, pass_gate())
    available = formal_statistics(official, ["000001"], date(2025, 1, 1), date(2026, 1, 1), run_id)
    config = {"database_root": str(tmp_path / "stage19"), "analysis_as_of_date": "2026-07-27",
              "period_start": "2025-07-27", "period_end": "2026-07-27"}
    created = pd.Timestamp("2026-01-20T00:00:00Z")
    path = _persist(ROOT, run_id, created, candidates, available, pass_gate(), config, [], [])
    _persist(ROOT, run_id, created, candidates, available, pass_gate(), config, [], [])
    with duckdb.connect(str(path), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM analysis.limit_event").fetchone()[0] == 2
        assert connection.execute("SELECT official_event_count FROM audit.stage19_run").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM analysis.limit_event_statistics").fetchone()[0] == 10

    blocked = blocked_statistics(["000001"], date(2025, 1, 1), date(2026, 1, 1), run_id, ["G1:x"])
    _persist(ROOT, run_id, created, candidates, blocked, blocked_gate(), config, [], [])
    with duckdb.connect(str(path), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM analysis.limit_event").fetchone()[0] == 0
        assert connection.execute("SELECT official_event_count FROM audit.stage19_run").fetchone()[0] == 0
        assert connection.execute("SELECT count(value) FROM analysis.limit_event_statistics").fetchone()[0] == 0

    _persist(ROOT, run_id, created, candidates, available, pass_gate(), config, [], [])
    with duckdb.connect(str(path), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM analysis.limit_event").fetchone()[0] == 2
        assert connection.execute("SELECT count(*) FROM analysis.limit_event_statistics").fetchone()[0] == 10
