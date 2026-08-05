"""Global offline guard for the default test suite."""
from __future__ import annotations

import json
import socket
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _universe_symbols() -> list[str]:
    from akshare_data_test.config import load_universe

    return [item.symbol for item in load_universe().stocks]


def _statement_rows() -> list[dict[str, object]]:
    import yaml

    stage10 = yaml.safe_load(
        (ROOT / "config/stage10.yml").read_text(encoding="utf-8")
    )
    rows: list[dict[str, object]] = []
    for symbol in _universe_symbols():
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
                        "transform_run_id": "stage15-test",
                        "source_run_id": "source-stage5",
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
                        "source_file": "data/raw/test",
                        "source_row_number": 1,
                    }
                )
    return rows


@pytest.fixture
def stage15_test_config(tmp_path: Path) -> Path:
    """Stage 15 config with permissive row minimums for tiny synthetic inputs."""
    import yaml

    payload = yaml.safe_load(
        (ROOT / "config/stage15.yml").read_text(encoding="utf-8")
    )
    payload["daily_checks"]["row_count_expected_minimum"] = {
        table: 1
        for table in payload["daily_checks"]["row_count_expected_minimum"]
    }
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "stage10.yml").write_text(
        (ROOT / "config/stage10.yml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    path = config_dir / "stage15.yml"
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def stage15_synthetic_db(tmp_path: Path) -> Path:
    """Minimal Stage 5-compatible DuckDB for offline Stage 15 tests."""
    database = tmp_path / "input_stage5.duckdb"
    connection = duckdb.connect(str(database))
    try:
        connection.execute(
            (ROOT / "sql/stage5_schema.sql").read_text(encoding="utf-8")
        )
        connection.execute(
            (ROOT / "sql/stage5_views.sql").read_text(encoding="utf-8")
        )
        symbols = _universe_symbols()
        dim = pd.DataFrame(
            [
                {
                    "symbol": item,
                    "exchange": "SH" if item.startswith("6") else "SZ",
                    "symbol_em": ("SH" if item.startswith("6") else "SZ") + item,
                    "market_lower": "sh" if item.startswith("6") else "sz",
                    "asset_type": "A_SHARE",
                    "currency": "CNY",
                    "is_active": True,
                }
                for item in symbols
            ]
        )
        connection.register("dim", dim)
        connection.execute("INSERT INTO dim_security SELECT * FROM dim")
        connection.unregister("dim")
        etl = pd.DataFrame(
            [
                {
                    "transform_run_id": "stage15-test",
                    "market_source_run_id": "market-stage3",
                    "fundamental_source_run_id": "fundamental-stage4",
                    "as_of_date": pd.Timestamp("2026-07-27").date(),
                    "started_at": pd.Timestamp("2026-07-27T00:00:00+08:00"),
                    "finished_at": pd.Timestamp("2026-07-27T01:00:00+08:00"),
                    "code_version": "stage5",
                    "status": "PASS",
                }
            ]
        )
        connection.register("etl", etl)
        connection.execute(
            "INSERT INTO etl_run "
            "(transform_run_id, market_source_run_id, fundamental_source_run_id, "
            "as_of_date, started_at, finished_at, code_version, status) "
            "SELECT transform_run_id, market_source_run_id, fundamental_source_run_id, "
            "as_of_date, started_at, finished_at, code_version, status FROM etl"
        )
        connection.unregister("etl")
        daily_rows: list[dict[str, object]] = []
        for symbol in symbols:
            for adjust in ("qfq", "raw"):
                for day in ("2026-07-24", "2026-07-27"):
                    daily_rows.append(
                        {
                            "transform_run_id": "stage15-test",
                            "source_run_id": "source-stage3",
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
                            "source_file": "data/raw/test",
                            "source_row_number": 1,
                            "ingested_at": pd.Timestamp("2026-07-27T01:00:00+08:00"),
                        }
                    )
        daily = pd.DataFrame(daily_rows)
        connection.register("daily", daily)
        connection.execute("INSERT INTO fact_stock_daily SELECT * FROM daily")
        connection.unregister("daily")
        spot_rows: list[dict[str, object]] = []
        for symbol in symbols:
            spot_rows.append(
                {
                    "transform_run_id": "stage15-test",
                    "source_run_id": "source-stage3",
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
                    "source_file": "data/raw/test",
                }
            )
        spot = pd.DataFrame(spot_rows)
        connection.register("spot", spot)
        connection.execute("INSERT INTO fact_stock_spot SELECT * FROM spot")
        connection.unregister("spot")
        abstract_rows: list[dict[str, object]] = []
        for symbol in symbols:
            abstract_rows.append(
                {
                    "transform_run_id": "stage15-test",
                    "source_run_id": "source-stage4",
                    "symbol": symbol,
                    "exchange": "SH" if symbol.startswith("6") else "SZ",
                    "report_period": pd.Timestamp("2026-03-31").date(),
                    "announcement_date": None,
                    "metric_code": "m1",
                    "metric_name_source": "test",
                    "metric_category_source": "test",
                    "metric_value": 1.0,
                    "metric_value_raw": "1.0",
                    "unit_source": "CNY_yuan",
                    "unit_canonical": "CNY_yuan",
                    "potential_lookahead": None,
                    "announcement_date_status": "unavailable",
                    "source_interface": "stock_financial_abstract",
                    "source_field": "test",
                    "source_file": "data/raw/test",
                    "source_row_number": 1,
                }
            )
        abstract = pd.DataFrame(abstract_rows)
        connection.register("abstract", abstract)
        connection.execute(
            "INSERT INTO fact_financial_abstract SELECT * FROM abstract"
        )
        connection.unregister("abstract")
        indicator = abstract.drop(columns=["metric_category_source"])
        connection.register("indicator", indicator)
        connection.execute(
            "INSERT INTO fact_financial_indicator SELECT * FROM indicator"
        )
        connection.unregister("indicator")
        statements = pd.DataFrame(_statement_rows())
        connection.register("statements", statements)
        connection.execute(
            "INSERT INTO fact_financial_statement SELECT * FROM statements"
        )
        connection.unregister("statements")
        fund_rows: list[dict[str, object]] = []
        for symbol in symbols:
            fund_rows.append(
                {
                    "transform_run_id": "stage15-test",
                    "source_run_id": "source-stage4",
                    "symbol": symbol,
                    "exchange": "SH" if symbol.startswith("6") else "SZ",
                    "trade_date": pd.Timestamp("2026-07-27").date(),
                    "close": 10.5,
                    "pct_change": 0.01,
                    "main_net_inflow_cny": 100.0,
                    "main_net_inflow_ratio": 0.01,
                    "source_file": "data/raw/test",
                }
            )
        fund = pd.DataFrame(fund_rows)
        connection.register("fund", fund)
        connection.execute(
            "INSERT INTO fact_stock_fund_flow "
            "(transform_run_id, source_run_id, symbol, exchange, trade_date, close, "
            "pct_change, main_net_inflow_cny, main_net_inflow_ratio, source_file) "
            "SELECT transform_run_id, source_run_id, symbol, exchange, trade_date, close, "
            "pct_change, main_net_inflow_cny, main_net_inflow_ratio, source_file FROM fund"
        )
        connection.unregister("fund")
    finally:
        connection.close()
    return database


@pytest.fixture
def stage15_elapsed_evidence(tmp_path: Path) -> None:
    """Small elapsed-time CSVs referenced by the Stage 15 config."""
    reports = tmp_path / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    smoke_interfaces = [
        "stock_zh_a_hist",
        "stock_zh_a_spot_em",
        "crypto_js_spot",
    ]
    financial_interfaces = [
        "stock_financial_abstract",
        "stock_financial_analysis_indicator",
        "stock_balance_sheet_by_report_em",
        "stock_profit_sheet_by_report_em",
        "stock_cash_flow_sheet_by_report_em",
        "stock_individual_fund_flow",
    ]
    rows = [
        {"run_id": "r1", "interface_name": interface, "elapsed_seconds": 0.5}
        for interface in smoke_interfaces
    ]
    rows.extend(
        {"run_id": "r1", "interface_name": interface, "elapsed_seconds": 0.6}
        for interface in financial_interfaces
    )
    pd.DataFrame(rows).to_csv(
        reports / "interface_smoke_test.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame(rows).to_csv(
        reports / "stage4_financial_coverage.csv", index=False, encoding="utf-8-sig"
    )
    (reports / "stage3_market_coverage.csv").write_text(
        "run_id,dataset_id,symbol,status\nr1,stock_zh_a_hist,600763,success\n",
        encoding="utf-8-sig",
    )

@pytest.fixture(autouse=True)
def block_real_network(monkeypatch):
    """Fail every unmocked outbound socket attempt."""

    def blocked(*args, **kwargs):
        raise AssertionError("Real network access is forbidden during pytest")

    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)


@pytest.fixture(autouse=True)
def stage14_child_env(monkeypatch):
    """Keep subprocess CLI tests from nesting Stage 14 status logging.

    Stage 14 wraps standalone commands so production invocations receive a
    status record.  Most repository CLI tests invoke those commands only to
    exercise the underlying stages; treating them as stage14 children avoids
    writing fault-injection logs into the project's real logs directory.
    """
    monkeypatch.setenv("AKSHARE_STAGE14_CHILD", "1")
