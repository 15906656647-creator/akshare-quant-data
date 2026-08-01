from pathlib import Path

import pandas as pd
import pytest

from akshare_data_test.fundamental_analysis import (
    build_fundamental_summary,
    calculate_fundamental_indicators,
    cumulative_to_single_quarter,
    load_stage10_config,
    normalize_financial_statements,
    normalize_valuation_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]


def _config():
    return load_stage10_config(ROOT / "config/stage10.yml")[0]


def _statement(
    column="TOTAL_OPERATE_INCOME", value=100.0, period="2025-03-31",
    statement_type="profit_statement", source_run_id="source-a", unit="CNY_yuan",
    announcement="2025-04-30", row_number=1,
):
    return {
        "symbol": "000001", "statement_type": statement_type,
        "report_period": period, "announcement_date": announcement,
        "line_item_code": "hashed", "line_item_name_source": column,
        "line_item_value": value, "unit_canonical": unit,
        "source_column": column, "source_file": f"data/raw/{source_run_id}.parquet",
        "source_run_id": source_run_id, "source_row_number": row_number,
    }


def _normalize(rows):
    return normalize_financial_statements(pd.DataFrame(rows), run_id="run-1", config=_config())


def test_config_has_reproducible_hash_and_versions():
    config, first = load_stage10_config(ROOT / "config/stage10.yml")
    _, second = load_stage10_config(ROOT / "config/stage10.yml")
    assert first == second
    assert config["calculation_version"] == "stage10_calculation_v1"


def test_normalization_preserves_report_source_and_version_metadata():
    raw, facts = _normalize([_statement()])
    row = raw.iloc[0]
    assert row["symbol"] == "000001"
    assert row["source_name"] == "AKShare"
    assert row["source_reference"].endswith("source-a.parquet")
    assert row["version"] == "source-a"
    assert pd.isna(row["update_time"])
    assert facts.iloc[0]["item_code"] == "revenue"
    assert bool(facts.iloc[0]["cumulative_flag"])


def test_two_announcement_versions_are_both_preserved():
    rows = [
        _statement(value=100, source_run_id="v1", announcement="2025-04-20"),
        _statement(value=105, source_run_id="v2", announcement="2025-05-01", row_number=2),
    ]
    raw, facts = _normalize(rows)
    assert len(raw) == len(facts) == 2
    assert raw["version_key"].nunique() == 2
    assert set(raw["version"]) == {"v1", "v2"}


def test_unmapped_statement_fields_are_not_guessed():
    raw, facts = _normalize([_statement(column="UNKNOWN_FIELD")])
    assert raw.empty
    assert facts.empty


@pytest.mark.parametrize("period", ["2025-01-31", "bad-date"])
def test_invalid_report_period_is_rejected(period):
    with pytest.raises(ValueError, match="report_period|Unsupported"):
        _normalize([_statement(period=period)])


def test_missing_input_field_is_rejected():
    row = _statement()
    row.pop("source_column")
    with pytest.raises(ValueError, match="missing columns"):
        _normalize([row])


def test_unsupported_unit_is_rejected():
    with pytest.raises(ValueError, match="Unsupported financial units"):
        _normalize([_statement(unit="CNY_ten_thousand")])


def test_balance_sheet_is_point_in_time_not_cumulative():
    _, facts = _normalize([
        _statement(column="TOTAL_ASSETS", value=500, statement_type="balance_sheet")
    ])
    converted = cumulative_to_single_quarter(facts)
    assert not bool(converted.iloc[0]["cumulative_flag"])
    assert converted.iloc[0]["single_quarter_value"] == 500
    assert converted.iloc[0]["conversion_status"] == "not_applicable"


def test_cumulative_q1_h1_q3_and_fy_convert_to_single_quarters():
    rows = [
        _statement(value=100, period="2025-03-31", row_number=1),
        _statement(value=250, period="2025-06-30", row_number=2),
        _statement(value=450, period="2025-09-30", row_number=3),
        _statement(value=700, period="2025-12-31", row_number=4),
    ]
    _, facts = _normalize(rows)
    converted = cumulative_to_single_quarter(facts)
    assert converted["single_quarter_value"].tolist() == [100, 150, 200, 250]
    assert converted["conversion_status"].tolist() == [
        "direct_q1", "derived_from_cumulative", "derived_from_cumulative",
        "derived_from_cumulative",
    ]


def test_conversion_is_independent_of_input_order():
    rows = [
        _statement(value=450, period="2025-09-30", row_number=3),
        _statement(value=100, period="2025-03-31", row_number=1),
        _statement(value=250, period="2025-06-30", row_number=2),
    ]
    _, facts = _normalize(rows)
    converted = cumulative_to_single_quarter(facts)
    assert converted["single_quarter_value"].tolist() == [100, 150, 200]


def test_missing_prior_cumulative_is_null_and_explicit():
    _, facts = _normalize([_statement(value=250, period="2025-06-30")])
    converted = cumulative_to_single_quarter(facts)
    assert pd.isna(converted.iloc[0]["single_quarter_value"])
    assert converted.iloc[0]["conversion_status"] == "missing_prior_cumulative"


def test_duplicate_report_in_same_version_is_rejected():
    with pytest.raises(ValueError, match="Duplicate .*report"):
        _normalize([_statement(row_number=1), _statement(row_number=2)])


@pytest.mark.parametrize(
    ("primary", "fallback", "expected_code"),
    [
        ("TOTAL_OPERATE_INCOME", "OPERATE_INCOME", "revenue"),
        ("TOTAL_OPERATE_COST", "OPERATE_COST", "operating_cost"),
    ],
)
def test_alias_priority_selects_one_fact_and_tracks_conflict(primary, fallback, expected_code):
    raw, facts = _normalize([
        _statement(column=fallback, value=90, row_number=1),
        _statement(column=primary, value=100, row_number=2),
    ])
    assert len(raw) == 2
    assert len(facts) == 1
    fact = facts.iloc[0]
    assert fact["item_code"] == expected_code
    assert fact["item_value"] == 100
    assert fact["source_field"] == primary
    assert fact["selected_source"] == primary
    assert bool(fact["conflict_flag"])
    assert bool(fact["conflict_value_mismatch"])


def test_alias_conflict_with_equal_values_is_traceable_without_value_mismatch():
    _, facts = _normalize([
        _statement(column="TOTAL_OPERATE_INCOME", value=100, row_number=1),
        _statement(column="OPERATE_INCOME", value=100, row_number=2),
    ])
    assert len(facts) == 1
    assert bool(facts.iloc[0]["conflict_flag"])
    assert not bool(facts.iloc[0]["conflict_value_mismatch"])


def test_unit_mismatch_between_cumulative_periods_is_rejected():
    _, facts = _normalize([
        _statement(value=100, period="2025-03-31", unit="CNY_yuan", row_number=1),
        _statement(value=250, period="2025-06-30", unit="CNY_per_share", row_number=2),
    ])
    with pytest.raises(ValueError, match="unit mismatch"):
        cumulative_to_single_quarter(facts)


def _complete_facts():
    rows = []
    quarters = [
        ("2024-03-31", 80, 50, 8, 10), ("2024-06-30", 180, 110, 18, 22),
        ("2024-09-30", 290, 175, 29, 35), ("2024-12-31", 420, 250, 42, 50),
        ("2025-03-31", 120, 70, 15, 18), ("2025-06-30", 270, 155, 33, 40),
        ("2025-09-30", 450, 255, 54, 65), ("2025-12-31", 660, 370, 78, 92),
    ]
    for position, (period, revenue, cost, profit, cash) in enumerate(quarters, 1):
        for column, value in [
            ("TOTAL_OPERATE_INCOME", revenue), ("TOTAL_OPERATE_COST", cost),
            ("PARENT_NETPROFIT", profit),
        ]:
            rows.append(_statement(column=column, value=value, period=period, row_number=position * 10 + len(rows)))
        rows.append(_statement(
            column="NETCASH_OPERATE", value=cash, period=period,
            statement_type="cash_flow_statement", row_number=position * 100,
        ))
        for column, value in [
            ("TOTAL_ASSETS", 1000 + position * 10),
            ("TOTAL_LIABILITIES", 400 + position * 5),
            ("TOTAL_EQUITY", 600 + position * 5),
        ]:
            rows.append(_statement(
                column=column, value=value, period=period,
                statement_type="balance_sheet", row_number=position * 1000 + len(rows),
            ))
    _, facts = _normalize(rows)
    return cumulative_to_single_quarter(facts)


def _metric(frame, period, code):
    row = frame.loc[
        frame.report_period.eq(pd.Timestamp(period)) & frame.indicator_code.eq(code)
    ]
    assert len(row) == 1
    return row.iloc[0]["indicator_value"]


def test_indicators_calculate_ttm_yoy_and_profitability_ratios():
    indicators = calculate_fundamental_indicators(
        _complete_facts(), run_id="run-1", calculation_version="v1",
        created_at=pd.Timestamp("2026-01-01", tz="UTC"),
    )
    period = "2025-12-31"
    assert _metric(indicators, period, "revenue_ttm") == pytest.approx(660)
    assert _metric(indicators, period, "net_profit_ttm") == pytest.approx(78)
    assert _metric(indicators, period, "revenue_yoy") == pytest.approx((210 - 130) / 130)
    assert _metric(indicators, period, "net_profit_yoy") == pytest.approx((24 - 13) / 13)
    assert _metric(indicators, period, "gross_margin") == pytest.approx((660 - 370) / 660)
    assert _metric(indicators, period, "net_margin") == pytest.approx(78 / 660)
    assert _metric(indicators, period, "cashflow_profit_ratio") == pytest.approx(92 / 78)
    assert _metric(indicators, period, "asset_liability_ratio") == pytest.approx(440 / 1080)


def test_indicators_keep_missing_ttm_unavailable():
    facts = _complete_facts()
    facts = facts.loc[facts.report_period.ge(pd.Timestamp("2025-09-30"))]
    indicators = calculate_fundamental_indicators(
        facts, run_id="run-1", calculation_version="v1",
        created_at=pd.Timestamp("2026-01-01", tz="UTC"),
    )
    assert pd.isna(_metric(indicators, "2025-12-31", "revenue_ttm"))


@pytest.mark.parametrize(
    "pe,pb,pe_status,pb_status",
    [(10.0, 2.0, "available", "available"), (-3.0, 2.0, "loss-making", "available"),
     (None, None, "unavailable", "unavailable"), (0.0, 0.0, "loss-making", "invalid")],
)
def test_valuation_snapshot_statuses(pe, pb, pe_status, pb_status):
    spot = pd.DataFrame([{
        "snapshot_at": "2026-01-01T01:00:00Z", "symbol": "1",
        "pe_dynamic": pe, "pb": pb, "market_cap_cny": 1000,
        "source_run_id": "spot-1",
    }])
    result = normalize_valuation_snapshot(
        spot, run_id="run-1", source="AKShare", created_at=pd.Timestamp("2026-01-01", tz="UTC")
    )
    assert result.iloc[0]["symbol"] == "000001"
    assert result.iloc[0]["pe_status"] == pe_status
    assert result.iloc[0]["pb_status"] == pb_status
    if pe is None:
        assert pd.isna(result.iloc[0]["pe"])
    if pb is None:
        assert pd.isna(result.iloc[0]["pb"])


def test_historical_valuation_cannot_be_invented_from_snapshot():
    with pytest.raises(ValueError, match="historical values require"):
        normalize_valuation_snapshot(
            pd.DataFrame(), run_id="run-1", source="AKShare",
            created_at=pd.Timestamp("2026-01-01", tz="UTC"), valuation_type="historical",
        )


def test_summary_uses_real_metrics_and_contains_risk_statement():
    indicators = calculate_fundamental_indicators(
        _complete_facts(), run_id="run-1", calculation_version="v1",
        created_at=pd.Timestamp("2026-01-01", tz="UTC"),
    )
    valuations = normalize_valuation_snapshot(pd.DataFrame([{
        "snapshot_at": "2025-12-31T01:00:00Z", "symbol": "000001",
        "pe_dynamic": -1, "pb": None, "market_cap_cny": 1000,
        "source_run_id": "spot-1",
    }]), run_id="run-1", source="AKShare", created_at=pd.Timestamp("2026-01-01", tz="UTC"))
    summary = build_fundamental_summary(
        indicators, valuations, run_id="run-1", as_of_date=pd.Timestamp("2025-12-31"),
        config=_config(), created_at=pd.Timestamp("2026-01-01", tz="UTC"),
    )
    row = summary.iloc[0]
    assert row["revenue_growth"] is not None
    assert "PE loss-making" in row["valuation_status"]
    assert "PB unavailable" in row["valuation_status"]
    assert "不构成投资建议" in row["summary_explanation"]
    assert "买入" not in row["summary_explanation"]
