from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from akshare_data_test.presentation import ChartRenderer
from akshare_data_test.stage13_presentation import (
    EVENT_OUTPUT_COLUMNS,
    build_stage13_presentation,
    prepare_limit_event_outputs,
)


ROOT = Path(__file__).resolve().parents[1]
CUTOFF = pd.Timestamp("2026-07-27")
DATABASE_NAMES = (
    "akshare_data_test_stage5_repaired.duckdb",
    "akshare_features_stage6.duckdb",
    "akshare_features_stage7.duckdb",
)


def _events(rows):
    return pd.DataFrame(rows, columns=[
        "symbol", "trade_date", "limit_direction", "limit_status", "raw_close",
        "detection_confidence", "uncertainty_reason",
    ])


def _prices(rows):
    return pd.DataFrame(rows, columns=["symbol", "trade_date", "open", "high", "low", "close"])


def test_zero_confirmed_events_is_valid_empty_output_with_complete_price_schema():
    events, returns, summary = prepare_limit_event_outputs(_events([]), _prices([]), CUTOFF)
    assert events.empty and returns.empty and summary.empty
    assert tuple(events.columns) == EVENT_OUTPUT_COLUMNS
    assert {"event_price", "event_price_source", "as_of_date"}.issubset(events.columns)
    assert "next_open_return" in returns


@pytest.mark.parametrize("direction", ["up", "down", "limit_up", "limit_down"])
def test_single_confirmed_direction_preserves_authoritative_event_price(direction):
    events = _events([["000100", "2026-07-24", direction, "confirmed", 10.0, .9, None]])
    prices = _prices([["000100", "2026-07-24", 9, 11, 9, 10], ["000100", "2026-07-27", 11, 12, 10, 11]])
    formal, returns, summary = prepare_limit_event_outputs(events, prices, CUTOFF)
    assert formal.iloc[0].limit_direction == direction
    assert formal.iloc[0].event_price == 10.0
    assert formal.iloc[0].event_price_source == "feat_limit_event.raw_close"
    assert formal.iloc[0].as_of_date == "2026-07-27"
    assert returns.iloc[0].event_day_close == formal.iloc[0].event_price
    assert returns.iloc[0].next_open_return == pytest.approx(.1)
    assert summary.iloc[0].sample_count == 1


@pytest.mark.parametrize("status,direction", [("uncertain", "up"), ("warmup", "down"), ("confirmed", None)])
def test_nonformal_events_are_excluded(status, direction):
    formal, returns, summary = prepare_limit_event_outputs(
        _events([["000100", "2026-07-24", direction, status, 10.0, .2, "x"]]), _prices([]), CUTOFF
    )
    assert formal.empty and returns.empty and summary.empty


def test_future_confirmed_event_is_excluded():
    formal, _, _ = prepare_limit_event_outputs(
        _events([["000100", "2026-07-28", "up", "confirmed", 10.0, .9, None]]), _prices([]), CUTOFF
    )
    assert formal.empty


def test_cutoff_event_retains_missing_next_day_without_future_fill():
    events = _events([["000100", "2026-07-27", "up", "confirmed", 10.0, .9, None]])
    prices = _prices([["000100", "2026-07-27", 9, 11, 9, 10]])
    formal, returns, summary = prepare_limit_event_outputs(events, prices, CUTOFF)
    assert formal.iloc[0].event_price == 10.0
    assert returns.iloc[0].return_status == "MISSING_NEXT_TRADE_DAY"
    assert np.isnan(returns.iloc[0].next_open_return)
    assert summary.iloc[0].missing_next_day_count == 1


@pytest.mark.parametrize("bad_price", [None, np.nan, np.inf, -np.inf, 0.0, -1.0])
def test_invalid_confirmed_event_price_is_never_zero_filled_and_blocks_return(bad_price):
    events = _events([["000100", "2026-07-24", "up", "confirmed", bad_price, .9, "price probe"]])
    prices = _prices([["000100", "2026-07-24", 9, 11, 9, 10], ["000100", "2026-07-27", 11, 12, 10, 11]])
    formal, returns, summary = prepare_limit_event_outputs(events, prices, CUTOFF)
    assert len(formal) == 1
    assert returns.iloc[0].return_status == "INVALID_EVENT_PRICE"
    assert pd.isna(returns.iloc[0].event_day_close)
    assert pd.isna(returns.iloc[0].next_open_return)
    assert summary.iloc[0].sample_count == 0


def test_two_known_next_open_returns_and_summary_match_manual_values():
    events = _events([
        ["000100", "2026-07-21", "up", "confirmed", 5.35, .9, None],
        ["000100", "2026-07-23", "down", "confirmed", 5.16, .8, None],
    ])
    prices = _prices([
        ["000100", "2026-07-21", 5.00, 5.40, 4.90, 5.35],
        ["000100", "2026-07-22", 5.24, 5.30, 5.10, 5.20],
        ["000100", "2026-07-23", 5.15, 5.20, 5.10, 5.16],
        ["000100", "2026-07-24", 5.07, 5.15, 5.00, 5.10],
    ])
    formal, returns, summary = prepare_limit_event_outputs(events, prices, CUTOFF)
    expected = [-0.020560747663551315, -0.0174418604651162]
    assert formal.event_price.tolist() == [5.35, 5.16]
    assert returns.next_open_return.tolist() == pytest.approx(expected)
    row = summary.iloc[0]
    assert row.sample_count == 2 and row.missing_next_day_count == 0
    assert row["mean"] == pytest.approx(np.mean(expected))
    assert row["median"] == pytest.approx(np.median(expected))
    assert row["std"] == pytest.approx(np.std(expected, ddof=1))
    assert row["min"] == pytest.approx(min(expected))
    assert row["max"] == pytest.approx(max(expected))
    assert row.positive_ratio == 0


def _copy_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "config").mkdir(parents=True)
    (root / "database").mkdir()
    shutil.copy2(ROOT / "config/stage13.yml", root / "config/stage13.yml")
    for name in DATABASE_NAMES:
        shutil.copy2(ROOT / "database" / name, root / "database" / name)
    return root


def _build(root: Path, run_id: str):
    return build_stage13_presentation(
        root=root,
        as_of_date=CUTOFF,
        config_path=root / "config/stage13.yml",
        input_database=root / "database/akshare_data_test_stage5_repaired.duckdb",
        reports_dir=root / "reports/stage13",
        run_id=run_id,
        symbols=["000100"],
    )


def test_report_marks_event_assets_not_available_when_formal_source_is_absent(tmp_path):
    root = _copy_root(tmp_path)
    with duckdb.connect(str(root / "database/akshare_features_stage6.duckdb")) as connection:
        connection.execute("DROP TABLE feat_limit_event")
    manifest, exit_code = _build(root, "source-absent")
    assets = pd.read_csv(root / "reports/stage13/stage13_asset_manifest.csv", dtype={"symbol": str}, keep_default_na=False)
    selected = assets.loc[assets.asset_id.isin(["limit_events", "next_open_return"])]
    assert exit_code == 0 and manifest["status"] == "READY"
    assert selected.status.eq("NOT_AVAILABLE").all()
    assert selected.output_path.eq("").all()


def test_full_report_reconciles_source_csv_chart_manifest_and_missing_price_status(tmp_path, monkeypatch):
    root = _copy_root(tmp_path)
    feature_db = root / "database/akshare_features_stage6.duckdb"
    with duckdb.connect(str(feature_db)) as connection:
        connection.execute("UPDATE feat_limit_event SET limit_status='confirmed', limit_direction='up', detection_confidence=.95, uncertainty_reason=NULL WHERE symbol='000100' AND trade_date=TIMESTAMP '2026-07-21'")
        connection.execute("UPDATE feat_limit_event SET limit_status='confirmed', limit_direction='down', detection_confidence=.90, uncertainty_reason=NULL WHERE symbol='000100' AND trade_date=TIMESTAMP '2026-07-23'")
    captured = []
    original = ChartRenderer.limit_events

    def capture(self, frame, path, symbol, *, status="AVAILABLE"):
        captured.append(frame.copy())
        return original(self, frame, path, symbol, status=status)

    monkeypatch.setattr(ChartRenderer, "limit_events", capture)
    manifest, exit_code = _build(root, "positive-events")
    output = root / "reports/stage13"
    event_csv = pd.read_csv(output / "tables/000100/limit_events.csv", dtype={"symbol": str})
    returns = pd.read_csv(output / "tables/000100/next_open_return_events.csv", dtype={"symbol": str})
    assets = pd.read_csv(output / "stage13_asset_manifest.csv", dtype={"symbol": str}, keep_default_na=False)
    with duckdb.connect(str(feature_db), read_only=True) as connection:
        source = connection.execute(
            "SELECT trade_date, raw_close FROM feat_limit_event "
            "WHERE symbol='000100' AND limit_status='confirmed' AND trade_date<=DATE '2026-07-27' ORDER BY trade_date"
        ).fetchdf()
    assert exit_code == 0 and manifest["status"] == "READY"
    assert tuple(event_csv.columns) == EVENT_OUTPUT_COLUMNS
    assert event_csv.event_price.tolist() == source.raw_close.tolist()
    assert event_csv.event_price_source.eq("feat_limit_event.raw_close").all()
    assert np.isfinite(event_csv.event_price).all() and event_csv.event_price.gt(0).all()
    assert len(captured) == 1
    pd.testing.assert_frame_equal(
        captured[0].reset_index(drop=True),
        event_csv.assign(trade_date=pd.to_datetime(event_csv.trade_date)).reset_index(drop=True),
        check_dtype=False,
    )
    limit_asset = assets.loc[assets.asset_id.eq("limit_events")].iloc[0]
    assert int(limit_asset.source_row_count) == len(event_csv) == 2
    assert limit_asset.status == "AVAILABLE"
    assert returns.event_day_close.tolist() == event_csv.event_price.tolist()
    assert returns.next_open_return.tolist() == pytest.approx([
        -0.020560747663551315, -0.0174418604651162,
    ], abs=5e-7)


def test_full_report_marks_invalid_confirmed_event_price_partial(tmp_path):
    root = _copy_root(tmp_path)
    with duckdb.connect(str(root / "database/akshare_features_stage6.duckdb")) as connection:
        connection.execute("UPDATE feat_limit_event SET limit_status='confirmed', limit_direction='up', raw_close=NULL WHERE symbol='000100' AND trade_date=TIMESTAMP '2026-07-21'")
    manifest, exit_code = _build(root, "invalid-event-price")
    output = root / "reports/stage13"
    assets = pd.read_csv(output / "stage13_asset_manifest.csv", dtype={"symbol": str}, keep_default_na=False)
    events = pd.read_csv(output / "tables/000100/limit_events.csv", dtype={"symbol": str})
    returns = pd.read_csv(output / "tables/000100/next_open_return_events.csv", dtype={"symbol": str})
    selected = assets.loc[assets.asset_id.isin(["limit_events", "next_open_return"])]
    assert exit_code == 0 and manifest["status"] == "READY"
    assert selected.status.eq("PARTIAL").all()
    assert selected.warnings.str.contains("lack a finite positive").all()
    assert pd.isna(events.iloc[0].event_price)
    assert returns.iloc[0].return_status == "INVALID_EVENT_PRICE"
