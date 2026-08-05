from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest
import yaml

from akshare_data_test.config import load_universe
from akshare_data_test.fundamental_analysis import load_stage10_config
from akshare_data_test.quality.stage15_checks import (
    CROSS_VALIDATION_COLUMNS,
    RISK_LOG_COLUMNS,
    build_cross_validation,
    build_risk_log,
    run_daily_quality_checks,
)
from akshare_data_test.stage15_config import load_stage15_config


ROOT = Path(__file__).resolve().parents[1]
SYMBOLS = [item.symbol for item in load_universe().stocks]


def _config() -> dict:
    config = deepcopy(load_stage15_config(ROOT / "config/stage15.yml")[0])
    config["daily_checks"]["row_count_expected_minimum"] = {
        table: 1
        for table in config["daily_checks"]["row_count_expected_minimum"]
    }
    return config


def _stage10() -> dict:
    return load_stage10_config(ROOT / "config/stage10.yml")[0]


def _daily_rows() -> list[dict]:
    rows: list[dict] = []
    for symbol in SYMBOLS:
        for adjust in ("qfq", "raw"):
            for day in ("2026-07-24", "2026-07-27"):
                rows.append(
                    {
                        "transform_run_id": "t",
                        "source_run_id": "r",
                        "symbol": symbol,
                        "exchange": "SH" if symbol.startswith("6") else "SZ",
                        "trade_date": pd.Timestamp(day).date(),
                        "adjust_type": adjust,
                        "open": 10.0,
                        "high": 11.0,
                        "low": 9.0,
                        "close": 10.5,
                        "volume_lot": 1000.0,
                        "volume_share": 100000.0,
                        "amount_cny": 10500.0,
                        "amplitude": 0.02,
                        "pct_change": 0.01,
                        "price_change": 0.1,
                        "turnover_rate": 0.005,
                        "source_file": "x",
                        "source_row_number": 1,
                        "ingested_at": pd.Timestamp("2026-07-27T01:00:00+08:00"),
                    }
                )
    return rows


def _spot_rows() -> list[dict]:
    rows: list[dict] = []
    for symbol in SYMBOLS:
        rows.append(
            {
                "transform_run_id": "t",
                "source_run_id": "r",
                "snapshot_at": pd.Timestamp("2026-07-27T15:00:00+08:00"),
                "snapshot_scope": "target_16",
                "symbol": symbol,
                "exchange": "SH" if symbol.startswith("6") else "SZ",
                "name": "test",
                "latest_price": 10.5,
                "pct_change": 0.01,
                "price_change": 0.1,
                "volume_lot": 1000.0,
                "volume_share": 100000.0,
                "amount_cny": 10500.0,
                "amplitude": 0.02,
                "turnover_rate": 0.005,
                "volume_ratio": 1.0,
                "pe_dynamic": 15.0,
                "pb": 2.0,
                "market_cap_cny": 1_000_000_000.0,
                "float_market_cap_cny": 900_000_000.0,
                "source_payload_json": "{}",
                "source_file": "x",
            }
        )
    return rows


def _statement_rows() -> list[dict]:
    stage10 = _stage10()
    rows: list[dict] = []
    for symbol in SYMBOLS:
        for statement_type, mapping in stage10["statement_mappings"].items():
            for canonical, specification in mapping.items():
                aliases = (
                    specification.get("priority")
                    if isinstance(specification, dict)
                    else specification
                )
                source_column = aliases[0]
                rows.append(
                    {
                        "transform_run_id": "t",
                        "source_run_id": "r",
                        "symbol": symbol,
                        "exchange": "SH" if symbol.startswith("6") else "SZ",
                        "statement_type": statement_type,
                        "report_period": pd.Timestamp("2026-03-31").date(),
                        "announcement_date": pd.Timestamp("2026-04-30").date(),
                        "line_item_code": f"code_{canonical}",
                        "line_item_name_source": source_column,
                        "line_item_value": 1.0,
                        "line_item_value_raw": "1.0",
                        "unit_source": "CNY_yuan",
                        "unit_canonical": "CNY_yuan",
                        "potential_lookahead": False,
                        "announcement_date_status": "available",
                        "source_column": source_column,
                        "source_file": "x",
                        "source_row_number": 1,
                    }
                )
    return rows


def _financial_rows(table: str) -> list[dict]:
    rows: list[dict] = []
    for symbol in SYMBOLS:
        rows.append(
            {
                "transform_run_id": "t",
                "source_run_id": "r",
                "symbol": symbol,
                "exchange": "SH" if symbol.startswith("6") else "SZ",
                "report_period": pd.Timestamp("2026-03-31").date(),
                "announcement_date": None,
                "metric_code": "m1",
                "metric_name_source": "test",
                "metric_value": 1.0,
                "metric_value_raw": "1.0",
                "unit_source": "CNY_yuan",
                "unit_canonical": "CNY_yuan",
                "potential_lookahead": None,
                "announcement_date_status": "unavailable",
                "source_interface": "test",
                "source_field": "test",
                "source_file": "x",
                "source_row_number": 1,
            }
        )
    if table == "fact_financial_indicator":
        for row in rows:
            row["metric_category_source"] = "test"
    else:
        for row in rows:
            row["metric_category_source"] = "test"
    return rows


def _fund_flow_rows() -> list[dict]:
    rows: list[dict] = []
    for symbol in SYMBOLS:
        rows.append(
            {
                "transform_run_id": "t",
                "source_run_id": "r",
                "symbol": symbol,
                "exchange": "SH" if symbol.startswith("6") else "SZ",
                "trade_date": pd.Timestamp("2026-07-27").date(),
                "close": 10.5,
                "pct_change": 0.01,
                "main_net_inflow_cny": 100.0,
                "main_net_inflow_ratio": 0.01,
                "super_large_net_inflow_cny": 10.0,
                "super_large_net_inflow_ratio": 0.001,
                "large_net_inflow_cny": 10.0,
                "large_net_inflow_ratio": 0.001,
                "medium_net_inflow_cny": 10.0,
                "medium_net_inflow_ratio": 0.001,
                "small_net_inflow_cny": 10.0,
                "small_net_inflow_ratio": 0.001,
                "source_file": "x",
            }
        )
    return rows


def _tables() -> dict[str, pd.DataFrame]:
    config = _config()
    expected = config["daily_checks"]["expected_columns"]
    builders = {
        "fact_stock_daily": _daily_rows,
        "fact_stock_spot": _spot_rows,
        "fact_financial_abstract": lambda: _financial_rows("fact_financial_abstract"),
        "fact_financial_indicator": lambda: _financial_rows("fact_financial_indicator"),
        "fact_financial_statement": _statement_rows,
        "fact_stock_fund_flow": _fund_flow_rows,
    }
    result: dict[str, pd.DataFrame] = {}
    for table, builder in builders.items():
        frame = pd.DataFrame(builder())
        result[table] = frame[expected[table]]
    return result


def _run(tables=None, *, baseline=None, elapsed=None, config=None, as_of="2026-07-27"):
    return run_daily_quality_checks(
        run_id="run-1",
        checked_at=pd.Timestamp("2026-07-27T12:00:00+08:00"),
        tables=tables or _tables(),
        expected_symbols=SYMBOLS,
        config=config or _config(),
        stage10_config=_stage10(),
        as_of_date=pd.Timestamp(as_of),
        baseline=baseline,
        elapsed=elapsed,
    )


def test_daily_checks_cover_stage15_1_and_pass():
    checks = _run()
    names = set(checks["check_name"])
    assert "row_count:fact_stock_daily" in names
    assert "latest_trade_date_updated:raw" in names
    assert "schema_field_set:fact_stock_daily" in names
    assert "sample_stocks_present:fact_financial_statement" in names
    assert "ohlc_logic:qfq" in names
    assert "primary_key_duplicates:fact_stock_spot" in names
    assert "negative_volume_amount:fact_stock_daily:raw" in names
    assert "pe_pb_missing_rate:pe_dynamic" in names
    assert "financial_key_fields_coverage" in names
    assert checks.loc[checks["severity"].eq("error"), "status"].eq("PASS").all()


def test_duplicate_primary_key_detected():
    tables = _tables()
    daily = tables["fact_stock_daily"].copy()
    tables["fact_stock_daily"] = pd.concat([daily, daily.iloc[[0]]], ignore_index=True)
    checks = _run(tables)
    row = checks.loc[checks["check_name"].eq("primary_key_duplicates:fact_stock_daily")]
    assert (row["status"] == "FAIL").all()
    assert "1" in str(row.iloc[0]["observed_value"])


def test_negative_volume_detected():
    tables = _tables()
    daily = tables["fact_stock_daily"].copy()
    daily.loc[0, "volume_lot"] = -1.0
    tables["fact_stock_daily"] = daily
    checks = _run(tables)
    row = checks.loc[checks["check_name"].eq("negative_volume_amount:fact_stock_daily:qfq")]
    assert (row["status"] == "FAIL").all()


def test_ohlc_violation_detected():
    tables = _tables()
    daily = tables["fact_stock_daily"].copy()
    daily.loc[0, "high"] = 8.0
    tables["fact_stock_daily"] = daily
    checks = _run(tables)
    row = checks.loc[checks["check_name"].eq("ohlc_logic:qfq")]
    assert (row["status"] == "FAIL").all()


def test_missing_sample_symbol_detected():
    tables = _tables()
    daily = tables["fact_stock_daily"].copy()
    dropped = SYMBOLS[0]
    tables["fact_stock_daily"] = daily.loc[daily["symbol"].ne(dropped)].reset_index(drop=True)
    checks = _run(tables)
    row = checks.loc[checks["check_name"].eq("sample_stocks_present:fact_stock_daily:qfq")]
    assert (row["status"] == "FAIL").all()
    assert dropped in str(row.iloc[0]["observed_value"])


def test_stale_latest_trade_date_detected():
    tables = _tables()
    daily = tables["fact_stock_daily"].copy()
    daily["trade_date"] = pd.Timestamp("2026-07-01").date()
    tables["fact_stock_daily"] = daily
    checks = _run(tables)
    row = checks.loc[checks["check_name"].eq("latest_trade_date_updated:raw")]
    assert (row["status"] == "FAIL").all()


def test_row_count_decline_vs_baseline_detected():
    baseline = {
        "table_row_counts": {"fact_stock_daily": 10000},
        "table_schemas": {},
        "interface_elapsed_seconds": {},
    }
    checks = _run(baseline=baseline)
    row = checks.loc[checks["check_name"].eq("row_count:fact_stock_daily")]
    assert (row["status"] == "FAIL").all()
    assert "abnormal decline" in str(row.iloc[0]["message"])


def test_schema_change_vs_baseline_detected():
    baseline = {
        "table_row_counts": {},
        "table_schemas": {
            "fact_stock_daily": sorted(
                _config()["daily_checks"]["expected_columns"]["fact_stock_daily"]
            )
            + ["new_column"]
        },
        "interface_elapsed_seconds": {},
    }
    checks = _run(baseline=baseline)
    row = checks.loc[checks["check_name"].eq("schema_field_set:fact_stock_daily")]
    assert (row["status"] == "FAIL").all()


def test_pe_pb_missing_rate_detected():
    tables = _tables()
    spot = tables["fact_stock_spot"].copy()
    spot.loc[:8, "pe_dynamic"] = None
    tables["fact_stock_spot"] = spot
    checks = _run(tables)
    row = checks.loc[checks["check_name"].eq("pe_pb_missing_rate:pe_dynamic")]
    assert (row["status"] == "FAIL").all()
    assert row.iloc[0]["severity"] == "warning"


def test_financial_key_field_missing_detected():
    tables = _tables()
    statements = tables["fact_financial_statement"].copy()
    revenue_rows = statements["source_column"].eq("TOTAL_OPERATE_INCOME")
    tables["fact_financial_statement"] = statements.loc[~revenue_rows].reset_index(drop=True)
    checks = _run(tables)
    row = checks.loc[checks["check_name"].eq("financial_key_field_missing:revenue")]
    assert (row["status"] == "FAIL").all()
    aggregate = checks.loc[checks["check_name"].eq("financial_key_fields_coverage")]
    assert (aggregate["status"] == "PASS").all()


def test_financial_coverage_aggregate_fails_on_high_threshold():
    config = _config()
    config["daily_checks"]["financial_key_fields_coverage_threshold"] = 0.99
    tables = _tables()
    statements = tables["fact_financial_statement"].copy()
    revenue_rows = statements["source_column"].eq("TOTAL_OPERATE_INCOME")
    tables["fact_financial_statement"] = statements.loc[~revenue_rows].reset_index(drop=True)
    checks = _run(tables, config=config)
    aggregate = checks.loc[checks["check_name"].eq("financial_key_fields_coverage")]
    assert (aggregate["status"] == "FAIL").all()


def test_interface_elapsed_spike_detected():
    elapsed = pd.DataFrame(
        [
            {"interface_name": "stock_zh_a_hist", "elapsed_seconds": 100.0},
            {"interface_name": "stock_zh_a_hist", "elapsed_seconds": 120.0},
        ]
    )
    baseline = {
        "table_row_counts": {},
        "table_schemas": {},
        "interface_elapsed_seconds": {"stock_zh_a_hist": 10.0},
    }
    checks = _run(elapsed=elapsed, baseline=baseline)
    row = checks.loc[checks["check_name"].eq("interface_elapsed_time_spike:stock_zh_a_hist")]
    assert (row["status"] == "FAIL").all()
    assert row.iloc[0]["interface_name"] == "stock_zh_a_hist"


def test_cross_validation_without_stage8_marks_limit_items_unavailable():
    tables = _tables()
    symbols = ["002067", "600763", "300274"]
    cross = build_cross_validation(
        run_id="run-1",
        as_of_date=pd.Timestamp("2026-07-27"),
        daily=tables["fact_stock_daily"],
        spot=tables["fact_stock_spot"],
        statements=tables["fact_financial_statement"],
        limit_events=None,
        symbols=symbols,
        config=_config(),
        stage10_config=_stage10(),
    )
    assert list(cross.columns) == CROSS_VALIDATION_COLUMNS
    assert len(cross) == len(symbols) * 7
    limit_rows = cross.loc[
        cross["check_item"].isin(["recent_limit_up_day", "next_day_open_after_limit_up"])
    ]
    assert limit_rows["verification_status"].eq("UNAVAILABLE").all()
    assert limit_rows["note"].astype(str).str.contains("unavailable").all()
    last5 = cross.loc[cross["check_item"].eq("last_5_days_close_volume")]
    assert last5["verification_status"].eq("REVIEW").all()
    assert last5["observed_value"].astype(str).str.contains("2026-07-27").all()


def test_cross_validation_with_stage8_events():
    tables = _tables()
    symbols = ["002067"]
    events = pd.DataFrame(
        [
            {
                "symbol": "002067",
                "trade_date": pd.Timestamp("2026-07-20").date(),
                "event_type": "limit_up",
                "next_open": 11.2,
                "next_trade_date": pd.Timestamp("2026-07-21").date(),
            }
        ]
    )
    cross = build_cross_validation(
        run_id="run-1",
        as_of_date=pd.Timestamp("2026-07-27"),
        daily=tables["fact_stock_daily"],
        spot=tables["fact_stock_spot"],
        statements=tables["fact_financial_statement"],
        limit_events=events,
        symbols=symbols,
        config=_config(),
        stage10_config=_stage10(),
    )
    limit_up = cross.loc[cross["check_item"].eq("recent_limit_up_day")]
    assert limit_up["verification_status"].eq("REVIEW").all()
    assert limit_up["observed_value"].iloc[0] == "2026-07-20"
    next_open = cross.loc[cross["check_item"].eq("next_day_open_after_limit_up")]
    assert next_open["verification_status"].eq("REVIEW").all()
    assert next_open["observed_value"].iloc[0] == "11.2"


def test_risk_log_contract_and_blocked_stage8():
    checks = _run()
    checks.loc[0, "status"] = "FAIL"
    checks.loc[0, "message"] = "synthetic failure"
    cross = pd.DataFrame(
        [
            {
                "run_id": "run-1",
                "symbol": "002067",
                "check_item": "recent_limit_up_day",
                "observed_value": "unavailable",
                "source_table": "analysis.fact_limit_event",
                "as_of_date": pd.Timestamp("2026-07-27").date(),
                "verification_status": "UNAVAILABLE",
                "note": "Stage 8 formal limit events unavailable",
            }
        ]
    )
    risks = build_risk_log(
        run_id="run-1",
        checked_at=pd.Timestamp("2026-07-27T12:00:00+08:00"),
        checks=checks,
        cross_validation=cross,
        stage8_blocker_codes=["no_authoritative_limit_rules"],
        config=_config(),
    )
    assert list(risks.columns) == RISK_LOG_COLUMNS
    assert risks["status"].isin({"open", "blocked"}).all()
    assert risks["status"].eq("blocked").any()
    assert risks["severity"].isin({"info", "warning", "error", "critical"}).all()
    joined = " ".join(risks.astype(str).sum(axis=1))
    assert "投资建议" not in joined
    assert "买入" not in joined
    assert risks["risk_id"].nunique() == len(risks)
