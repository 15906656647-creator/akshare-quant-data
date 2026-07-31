from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from akshare_data_test.limit_event_detection import (
    detect_limit_events,
    formal_events,
    validate_unadjusted_prices,
)
from test_limit_rules import rule, status


def bars(closes, *, dates=None, adjust="raw", volume=100):
    if dates is None:
        dates = pd.bdate_range("2026-01-02", periods=len(closes))
    return pd.DataFrame(
        {
            "symbol": "000001",
            "exchange": "SZ",
            "trade_date": dates,
            "adjust_type": adjust,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume_share": volume,
            "limit_up_price": None,
            "limit_down_price": None,
            "official_limit_source_name": None,
            "official_limit_source_reference": None,
            "official_limit_source_version": None,
            "official_limit_evidence_status": None,
            "official_limit_verified_at": None,
            "official_limit_fetched_at": None,
            "official_limit_symbol": None,
            "official_limit_trade_date": None,
        }
    )


def detect(frame, rules=None, statuses=None):
    return detect_limit_events(
        frame,
        rules if rules is not None else [rule()],
        statuses if statuses is not None else [status()],
        run_id="stage8-test",
        created_at=pd.Timestamp("2026-07-27T00:00:00Z"),
    )


def test_qfq_prices_are_rejected():
    with pytest.raises(ValueError, match="requires adjust_type='raw'"):
        validate_unadjusted_prices(bars([10, 11], adjust="qfq"))


def test_missing_adjust_type_is_rejected():
    with pytest.raises(ValueError, match="missing required"):
        validate_unadjusted_prices(bars([10]).drop(columns=["adjust_type"]))


def test_first_trading_day_is_unresolved_not_event():
    output = detect(bars([10, 11]))
    assert output.iloc[0]["event_type"] == "unresolved"
    assert output.iloc[0]["resolution_reason"] == "missing_previous_close"


def test_limit_up_and_limit_down_are_detected():
    output = detect(bars([10, 11, 9.9]))
    assert output["event_type"].tolist() == [
        "unresolved", "limit_up", "limit_down"
    ]


def test_mutual_exclusion_is_unresolved_and_never_verified_or_pass():
    output = detect(bars([0.01, 0.01]))
    row = output.iloc[1]
    assert row["event_type"] == "unresolved"
    assert row["evidence_status"] == "unresolved"
    assert row["quality_status"] == "failed"
    assert row["resolution_reason"] == "mutual_exclusion_conflict"
    assert formal_events(output).empty


def test_normal_close_is_not_misclassified():
    output = detect(bars([10, 10.2]))
    assert output.iloc[1]["event_type"] == "none"
    assert output.iloc[1]["quality_status"] == "not_event"


def test_missing_previous_close_is_explicit():
    frame = bars([None, 10])
    output = detect(frame)
    assert output.iloc[1]["resolution_reason"] == "missing_previous_close"


def test_suspension_or_no_trade_is_excluded():
    frame = bars([10, 11], volume=0)
    output = detect(frame)
    assert output.iloc[1]["resolution_reason"] == "invalid_trade_row"
    assert output.iloc[1]["event_type"] == "unresolved"


def test_no_limit_flag_does_not_create_event():
    output = detect(
        bars([10, 20]),
        rules=[rule(no_limit_flag=True, limit_up_ratio=None, limit_down_ratio=None)],
    )
    assert output.iloc[1]["detection_method"] == "no_limit_rule"
    assert output.iloc[1]["event_type"] == "none"


def test_missing_security_status_is_audited():
    output = detect(bars([10, 11]), statuses=[])
    assert output["evidence_status"].eq("unresolved").all()
    assert output.iloc[1]["event_type"] == "unresolved"
    assert output.iloc[1]["resolution_reason"] == "missing_security_status"


def test_missing_rule_is_standardized_as_unresolved():
    output = detect(bars([10, 11]), rules=[rule(board="growth")])
    assert output.iloc[1]["event_type"] == "unresolved"
    assert output.iloc[1]["quality_status"] == "failed"
    assert output.iloc[1]["resolution_reason"] == "missing_rule"


def test_unverified_rule_never_enters_formal_events():
    output = detect(bars([10, 11]), rules=[rule(evidence_status="unverified")])
    assert output.iloc[1]["event_type"] == "limit_up"
    assert output.iloc[1]["evidence_status"] == "provisional"
    assert formal_events(output).empty


def test_gap_proxy_cannot_become_formal_event():
    output = detect(bars([10, 10.5]))
    output.loc[1, "event_type"] = "gap_proxy"
    output.loc[1, "evidence_status"] = "verified"
    assert formal_events(output).empty


def test_next_day_is_next_security_trading_row_not_calendar_day():
    dates = pd.to_datetime(["2026-01-09", "2026-01-12"])
    output = detect(bars([10, 11], dates=dates))
    assert output.iloc[0]["next_trade_date"] == pd.Timestamp("2026-01-12")


def test_zero_volume_rows_are_skipped_for_next_and_continued_limit():
    frame = bars([10, 11, 11, 12.1])
    frame.loc[2, "volume_share"] = 0
    output = detect(frame)
    event = output.iloc[1]
    assert event["next_trade_date"] == frame.loc[3, "trade_date"]
    assert bool(event["is_continued_limit"])
    assert output.iloc[2]["resolution_reason"] == "invalid_trade_row"


def test_multiple_suspensions_and_weekend_are_skipped():
    dates = pd.to_datetime(
        ["2026-01-09", "2026-01-12", "2026-01-13", "2026-01-16"]
    )
    frame = bars([10, 11, 11, 12.1], dates=dates)
    frame.loc[[1, 2], "volume_share"] = 0
    output = detect(frame)
    assert output.iloc[0]["next_trade_date"] == pd.Timestamp("2026-01-16")


def test_forward_windows_count_only_valid_trading_rows():
    frame = bars([10, 99, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20])
    frame.loc[1, "volume_share"] = 0
    output = detect(frame)
    assert output.iloc[0]["forward_3d_return"] == pytest.approx(0.3)
    assert output.iloc[0]["forward_5d_return"] == pytest.approx(0.5)
    assert output.iloc[0]["forward_10d_return"] == pytest.approx(1.0)


def test_valid_sequences_do_not_cross_symbols():
    left = bars([10, 11])
    right = bars([20, 22])
    right["symbol"] = "000002"
    output = detect(pd.concat([left, right], ignore_index=True), statuses=[
        status(), status(symbol="000002", status_version="s2")
    ])
    first_rows = output.groupby("symbol", sort=False).head(1)
    assert first_rows["previous_close"].isna().all()


def test_forward_3_5_10_returns_and_tail_nulls():
    closes = [10 + index for index in range(11)]
    output = detect(bars(closes))
    assert output.iloc[0]["forward_3d_return"] == pytest.approx(0.3)
    assert output.iloc[0]["forward_5d_return"] == pytest.approx(0.5)
    assert output.iloc[0]["forward_10d_return"] == pytest.approx(1.0)
    assert pd.isna(output.iloc[-1]["forward_3d_return"])
    assert output.iloc[-1]["forward_sample_status"] == "tail_incomplete"


def test_continued_limit_uses_next_trading_event():
    output = detect(bars([10, 11, 12.1]))
    assert bool(output.iloc[1]["is_continued_limit"])


def test_official_verified_prices_take_priority():
    frame = bars([10, 10.8])
    frame.loc[1, "limit_up_price"] = 10.8
    frame.loc[1, "limit_down_price"] = 9.2
    frame.loc[1, "official_limit_source_name"] = "fixture"
    frame.loc[1, "official_limit_source_reference"] = "fixture://official"
    frame.loc[1, "official_limit_source_version"] = "v1"
    frame.loc[1, "official_limit_evidence_status"] = "verified"
    frame.loc[1, "official_limit_verified_at"] = pd.Timestamp("2026-01-01")
    frame.loc[1, "official_limit_fetched_at"] = pd.Timestamp("2026-01-01")
    frame.loc[1, "official_limit_symbol"] = "000001"
    frame.loc[1, "official_limit_trade_date"] = frame.loc[1, "trade_date"]
    output = detect(frame)
    assert output.iloc[1]["event_type"] == "limit_up"
    assert output.iloc[1]["detection_method"] == "verified_official_limit_price"


def test_nonempty_official_prices_without_evidence_fall_back_to_theoretical():
    frame = bars([10, 11])
    frame.loc[1, "limit_up_price"] = 10.5
    frame.loc[1, "limit_down_price"] = 9.5
    output = detect(frame)
    assert output.iloc[1]["detection_method"] == "theoretical_decimal"
    assert output.iloc[1]["official_limit_rejection_reason"] == (
        "official_limit_unverified"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("official_limit_source_reference", None),
        ("official_limit_evidence_status", "unverified"),
        ("official_limit_symbol", "000002"),
        ("official_limit_trade_date", pd.Timestamp("2026-01-01")),
    ],
)
def test_incomplete_or_mismatched_official_evidence_is_rejected(field, value):
    frame = bars([10, 11])
    for name, item in {
        "limit_up_price": 11,
        "limit_down_price": 9,
        "official_limit_source_name": "fixture",
        "official_limit_source_reference": "fixture://official",
        "official_limit_source_version": "v1",
        "official_limit_evidence_status": "verified",
        "official_limit_verified_at": pd.Timestamp("2026-01-01"),
        "official_limit_fetched_at": pd.Timestamp("2026-01-01"),
        "official_limit_symbol": "000001",
        "official_limit_trade_date": frame.loc[1, "trade_date"],
    }.items():
        frame.loc[1, name] = item
    frame.loc[1, field] = value
    output = detect(frame)
    assert output.iloc[1]["detection_method"] == "theoretical_decimal"


@pytest.mark.parametrize(
    "field",
    [
        "official_limit_source_name",
        "official_limit_source_reference",
        "official_limit_source_version",
    ],
)
@pytest.mark.parametrize(
    "missing", [None, float("nan"), pd.NA, pd.NaT, "", " ", "\t", "\r\n"]
)
def test_official_source_fields_reject_all_missing_sentinels(field, missing):
    frame = bars([10, 11])
    evidence = {
        "limit_up_price": 11,
        "limit_down_price": 9,
        "official_limit_source_name": "fixture",
        "official_limit_source_reference": "fixture://official",
        "official_limit_source_version": "v1",
        "official_limit_evidence_status": "verified",
        "official_limit_verified_at": pd.Timestamp("2026-01-01"),
        "official_limit_fetched_at": pd.Timestamp("2026-01-01"),
        "official_limit_symbol": "000001",
        "official_limit_trade_date": frame.loc[1, "trade_date"],
    }
    for name, value in evidence.items():
        frame.loc[1, name] = value
    frame.loc[1, field] = missing

    output = detect(frame)

    assert output.iloc[1]["detection_method"] == "theoretical_decimal"
    assert output.iloc[1]["official_limit_rejection_reason"] == (
        "official_limit_unverified"
    )


@pytest.mark.parametrize(
    "field", ["official_limit_source_name", "official_limit_source_reference"]
)
@pytest.mark.parametrize("sentinel", ["nan", "NaN", "none", "None", "null", "NaT"])
def test_official_source_fields_reject_missing_semantic_strings(field, sentinel):
    frame = bars([10, 10.8])
    evidence = {
        "limit_up_price": 10.8,
        "limit_down_price": 9.2,
        "official_limit_source_name": "fixture",
        "official_limit_source_reference": "fixture://official",
        "official_limit_source_version": "v1",
        "official_limit_evidence_status": "verified",
        "official_limit_verified_at": pd.Timestamp("2026-01-01"),
        "official_limit_fetched_at": pd.Timestamp("2026-01-01"),
        "official_limit_symbol": "000001",
        "official_limit_trade_date": frame.loc[1, "trade_date"],
    }
    for name, value in evidence.items():
        frame.loc[1, name] = value
    frame.loc[1, field] = sentinel

    output = detect(frame)

    assert output.iloc[1]["detection_method"] == "theoretical_decimal"
    assert output.iloc[1]["evidence_status"] != "verified"
    assert output.iloc[1]["official_limit_rejection_reason"] == (
        "official_limit_unverified"
    )
