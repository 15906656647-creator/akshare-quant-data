from __future__ import annotations

import pandas as pd

from akshare_data_test.stage8_analysis import (
    FORMAL_SUMMARY_COLUMNS,
    decide_publication,
    summarize_annual_events,
)


def test_empty_period_has_stable_schema_and_is_blocked():
    frame = pd.DataFrame(
        columns=[
            "symbol", "trade_date", "event_type", "evidence_status",
            "quality_status", "next_open_return", "is_continued_limit",
            "forward_5d_return",
        ]
    )
    summary, status, blockers = summarize_annual_events(
        frame,
        start_date=pd.Timestamp("2025-07-27"),
        end_date=pd.Timestamp("2026-07-27"),
    )
    assert summary.empty
    assert "formal_event_count" in summary.columns
    assert status == "blocked"
    assert blockers == ["no_price_observations"]


def test_unresolved_observation_blocks_counts_instead_of_reporting_zero():
    frame = pd.DataFrame([{
        "symbol": "000001",
        "trade_date": pd.Timestamp("2026-01-01"),
        "event_type": "none",
        "evidence_status": "unresolved",
        "quality_status": "excluded",
        "next_open_return": None,
        "is_continued_limit": None,
        "forward_5d_return": None,
    }])
    summary, status, blockers = summarize_annual_events(
        frame,
        start_date=pd.Timestamp("2025-07-27"),
        end_date=pd.Timestamp("2026-07-27"),
    )
    assert status == "blocked"
    assert summary.loc[0, FORMAL_SUMMARY_COLUMNS].isna().all()
    assert blockers


def test_only_verified_quality_pass_events_enter_summary():
    frame = pd.DataFrame([
        {
            "symbol": "000001", "trade_date": pd.Timestamp("2026-01-01"),
            "event_type": "limit_up", "evidence_status": "verified",
            "quality_status": "pass", "next_open_return": 0.02,
            "is_continued_limit": True, "forward_5d_return": 0.1,
        },
        {
            "symbol": "000001", "trade_date": pd.Timestamp("2026-01-02"),
            "event_type": "limit_down", "evidence_status": "verified",
            "quality_status": "pass", "next_open_return": -0.01,
            "is_continued_limit": False, "forward_5d_return": -0.1,
        },
    ])
    summary, status, blockers = summarize_annual_events(
        frame,
        start_date=pd.Timestamp("2025-07-27"),
        end_date=pd.Timestamp("2026-07-27"),
    )
    assert status == "formal"
    assert not blockers
    assert summary.iloc[0]["limit_up_count"] == 1
    assert summary.iloc[0]["limit_down_count"] == 1


def test_error_quality_failure_blocks_publication():
    observations = pd.DataFrame([{
        "symbol": "000001", "trade_date": pd.Timestamp("2026-01-01"),
        "event_type": "unresolved", "evidence_status": "unresolved",
        "quality_status": "failed", "resolution_reason": "mutual_exclusion_conflict",
    }])
    quality = pd.DataFrame([{
        "check_name": "formal_event_mutual_exclusion",
        "severity": "ERROR",
        "status": "FAIL",
    }])
    decision = decide_publication(observations, quality)
    assert decision.run_status == "BLOCKED"
    assert decision.publication_status == "blocked"
    assert decision.exit_code != 0
    assert decision.failed_quality_checks == ("formal_event_mutual_exclusion",)


def test_zero_formal_events_with_unresolved_is_not_formal_zero():
    observations = pd.DataFrame([{
        "symbol": "000001", "trade_date": pd.Timestamp("2026-01-01"),
        "event_type": "unresolved", "evidence_status": "unresolved",
        "quality_status": "failed", "resolution_reason": "missing_rule",
    }])
    decision = decide_publication(observations, None)
    assert decision.publication_status == "blocked"
