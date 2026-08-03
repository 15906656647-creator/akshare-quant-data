from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from akshare_data_test.adapters.crypto_exchange import assess_akshare_crypto_spot
from akshare_data_test.assets import AssetIdentity, AssetType, ETHUSDT, TradingCalendar
from akshare_data_test.crypto_market import (
    build_crypto_profile, compute_crypto_indicators, load_stage11_config,
    normalize_crypto_bars, resample_crypto_bars,
)
from akshare_data_test.crypto_evidence import write_raw_evidence
from akshare_data_test.assets import ETHUSDT_OKX_SPOT
from akshare_data_test.fundamental_analysis import (
    FundamentalAnalysisNotApplicable, require_equity_asset,
)
from akshare_data_test.quality.crypto_checks import run_stage11_quality_checks
from akshare_data_test.stage11_build import analyze_stage11, validate_stage11_inputs


ROOT = Path(__file__).resolve().parents[1]
AS_OF = pd.Timestamp("2026-07-27")


def hourly_input(periods: int = 960) -> pd.DataFrame:
    end = pd.Timestamp("2026-07-28T00:00:00Z")
    times = pd.date_range(end=end - pd.Timedelta(hours=1), periods=periods, freq="h")
    base = 2000 + np.linspace(0, 30, periods) + np.sin(np.arange(periods) / 4) * 10
    return pd.DataFrame({
        "trade_time": times, "open": base - 1, "high": base + 4,
        "low": base - 5, "close": base, "volume": 100 + np.arange(periods),
        "quote_volume": (100 + np.arange(periods)) * base,
        "raw_instrument": "ETH-USDT", "data_provider": "okx_public_api",
        "raw_exchange": "OKX", "instrument_type": "spot",
        "bar_interval": "1h", "confirmed": True,
    })


def normalized(periods: int = 960, run_id: str = "stage11-test") -> pd.DataFrame:
    return normalize_crypto_bars(
        hourly_input(periods), asset=ETHUSDT, interval="1h",
        local_timezone="Asia/Shanghai", source="okx_public_api", run_id=run_id,
    )


def raw_evidence(tmp_path: Path, frame: pd.DataFrame, run_id: str) -> Path:
    path = tmp_path / "raw" / f"run_id={run_id}"
    write_raw_evidence(
        path, run_id=run_id, provider="okx_public_api",
        endpoint="https://www.okx.com/api/v5/market/history-candles",
        request_parameters={"instId": "ETH-USDT", "bar": "1H"},
        response=frame, identity=ETHUSDT_OKX_SPOT,
        fetched_at=pd.Timestamp("2026-07-28T00:10:00Z"),
    )
    return path


def test_asset_abstraction_supports_equity_and_crypto_without_calendar_confusion():
    equity = AssetIdentity("600763", "SH", "A-share", AssetType.EQUITY, TradingCalendar.EXCHANGE_SESSIONS)
    assert equity.asset_type.value == "equity"
    assert ETHUSDT.asset_type.value == "crypto"
    assert ETHUSDT.trading_calendar.value == "continuous_24_7"
    with pytest.raises(ValueError, match="continuous_24_7"):
        AssetIdentity("ETHUSDT", "OKX", "spot", AssetType.CRYPTO, TradingCalendar.EXCHANGE_SESSIONS)


def test_eth_hourly_time_is_continuous_weekend_and_24_hours():
    bars = normalized()
    quality = run_stage11_quality_checks(
        bars, run_id="stage11-test", as_of_date=AS_OF, interval="1h",
        expected_symbol="ETHUSDT", checked_at=pd.Timestamp("2026-07-27T23:59:59Z"),
    ).set_index("check_name")
    assert quality.loc["time_continuity", "status"] == "PASS"
    assert quality.loc["weekend_trading_supported", "status"] == "PASS"
    assert quality.loc["twenty_four_hour_coverage", "status"] == "PASS"


def test_missing_kline_is_blocked():
    bars = normalized().drop(index=30).reset_index(drop=True)
    quality = run_stage11_quality_checks(
        bars, run_id="stage11-test", as_of_date=AS_OF, interval="1h",
        expected_symbol="ETHUSDT", checked_at=pd.Timestamp("2026-07-27T23:59:59Z"),
    ).set_index("check_name")
    assert quality.loc["time_continuity", "status"] == "FAIL"


def test_utc_local_conversion_and_utc_daily_segmentation():
    bars = normalized()
    assert str(bars["trade_time"].dt.tz) == "UTC"
    assert bars.loc[0, "local_trade_time"].hour == 8
    daily = resample_crypto_bars(bars, "1d")
    assert len(daily) == 40
    assert daily.loc[0, "volume"] == pytest.approx(hourly_input().iloc[:24]["volume"].sum())


def test_stage9_indicator_concepts_migrate_with_crypto_annualization():
    config, _ = load_stage11_config(ROOT / "config/stage11.yml")
    bars = normalized()
    indicators = compute_crypto_indicators(bars, interval="1h", config=config, run_id="stage11-test")
    row = indicators.loc[indicators.indicator_status.eq("calculated")].iloc[-1]
    for field in ("annualized_volatility", "atr", "bollinger_band_width", "trend_slope", "box_width"):
        assert pd.notna(row[field])
    expected = row["realized_volatility"] * np.sqrt(8760)
    assert row["annualized_volatility"] == pytest.approx(expected)
    profile = build_crypto_profile(indicators, config=config, as_of_date=AS_OF, run_id="stage11-test")
    assert profile.loc[0, "profile_status"] == "descriptive_only"
    assert "投资结论" in profile.loc[0, "explanation"]


def test_false_breakout_detection_is_causal_and_confirmed():
    config, _ = load_stage11_config(ROOT / "config/stage11.yml")
    frame = hourly_input(60)
    frame.loc[30, ["open", "high", "low", "close"]] = [2050, 2100, 2045, 2090]
    frame.loc[31, ["open", "high", "low", "close"]] = [2040, 2050, 2020, 2030]
    bars = normalize_crypto_bars(frame, asset=ETHUSDT, interval="1h", local_timezone="Asia/Shanghai", source="okx_public_api", run_id="breakout")
    indicators = compute_crypto_indicators(bars, interval="1h", config=config, run_id="breakout")
    assert bool(indicators.loc[30, "false_breakout_up"])


def test_crypto_fundamental_analysis_is_not_applicable():
    require_equity_asset("equity")
    with pytest.raises(FundamentalAnalysisNotApplicable) as error:
        require_equity_asset("crypto")
    assert error.value.status == "not_applicable"


def test_akshare_exact_pair_is_never_substituted():
    partial = assess_akshare_crypto_spot(pd.DataFrame({"pair": ["ETHUSD"]}))
    exact = assess_akshare_crypto_spot(pd.DataFrame({"pair": ["ETHUSDT"]}))
    assert partial.status == "partial_success" and not partial.exact_match
    assert exact.status == "success" and exact.exact_match


def test_repository_reports_and_six_required_tables(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "sql").mkdir()
    shutil.copy2(ROOT / "config/stage11.yml", tmp_path / "config/stage11.yml")
    shutil.copy2(ROOT / "sql/stage11_schema.sql", tmp_path / "sql/stage11_schema.sql")
    database = tmp_path / "database/stage11.duckdb"
    frame = hourly_input()
    report, code = analyze_stage11(
        root=tmp_path, as_of_date=AS_OF, input_frame=frame, interval="1h",
        source="okx_public_api", config_path=tmp_path / "config/stage11.yml",
        output_database=database, run_id="repo-run",
        raw_evidence_dir=raw_evidence(tmp_path, frame, "repo-run"),
    )
    assert code == 0 and report["run_status"] == "PASS"
    for name in ("stage11_validation.md", "stage11_independent_audit.md", "stage11_run.json", "stage11_quality.csv"):
        assert (tmp_path / "reports" / name).is_file()
    with duckdb.connect(str(database), read_only=True) as connection:
        tables = {(row[0], row[1]) for row in connection.execute(
            "SELECT table_schema, table_name FROM information_schema.tables"
        ).fetchall()}
        assert {
            ("raw", "crypto_market_data"), ("clean", "crypto_price_fact"),
            ("feature", "crypto_indicator"), ("analysis", "crypto_profile"),
            ("quality", "stage11_quality_result"), ("audit", "stage11_run"),
        }.issubset(tables)
        assert connection.execute("SELECT count(*) FROM clean.crypto_price_fact").fetchone()[0] == 960
    payload = json.loads((tmp_path / "reports/stage11_run.json").read_text(encoding="utf-8"))
    assert payload["artifact_hash"] == report["artifact_hash"]
    assert "csv_json_duckdb_consistency" in pd.read_csv(tmp_path / "reports/stage11_quality.csv")["check_name"].tolist()


def test_repository_is_idempotent_per_run(tmp_path):
    (tmp_path / "sql").mkdir()
    shutil.copy2(ROOT / "sql/stage11_schema.sql", tmp_path / "sql/stage11_schema.sql")
    database = tmp_path / "stage11.duckdb"
    frame = hourly_input()
    kwargs = dict(root=tmp_path, as_of_date=AS_OF, input_frame=frame, interval="1h", source="okx_public_api", config_path=ROOT / "config/stage11.yml", output_database=database, run_id="same-run", raw_evidence_dir=raw_evidence(tmp_path, frame, "same-run"))
    analyze_stage11(**kwargs)
    analyze_stage11(**kwargs)
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM audit.stage11_run").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM raw.crypto_market_data").fetchone()[0] == 960


def test_validate_only_and_cli_dry_run_are_read_only(tmp_path):
    (tmp_path / "config").mkdir()
    shutil.copy2(ROOT / "config/stage11.yml", tmp_path / "config/stage11.yml")
    csv_path = tmp_path / "eth.csv"
    hourly_input().to_csv(csv_path, index=False)
    raw_dir = raw_evidence(tmp_path, hourly_input(), "dry-run")
    output = tmp_path / "new/stage11.duckdb"
    result = validate_stage11_inputs(config_path=tmp_path / "config/stage11.yml", input_csv=csv_path, output_database=output)
    assert result["status"] == "READY" and not output.parent.exists()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    command = [
        sys.executable, str(ROOT / "run_pipeline.py"), "validate-crypto",
        "--as-of-date", "2026-07-27", "--config", str(tmp_path / "config/stage11.yml"),
        "--input-csv", str(csv_path), "--raw-evidence-dir", str(raw_dir),
        "--run-id", "dry-run", "--output-database", str(output), "--dry-run",
    ]
    completed = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    assert "Stage 11 crypto validation: PASS" in completed.stdout
    assert not output.exists() and not (tmp_path / "reports").exists()
