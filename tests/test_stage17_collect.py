from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from akshare_data_test.adapters.stock_market import MarketCall
from akshare_data_test.stage17_collect import (
    extract_listing_date, listing_coverage_status, run_stage17,
    validate_crypto, validate_equity_daily,
)


ROOT = Path(__file__).resolve().parents[1]


def daily_frame():
    return pd.DataFrame({
        "日期": ["2020-01-02", "2020-01-03", "2020-01-06"],
        "开盘": [10, 11, 12], "最高": [12, 13, 14], "最低": [9, 10, 11],
        "收盘": [11, 12, 13], "成交量": [100, 120, 130], "成交额": [1000, 1200, 1300],
    })


class FakeEquityAdapter:
    akshare_version = "test"

    def fetch_profile(self, **_kwargs):
        return MarketCall(pd.DataFrame({"项目": ["上市日期"], "值": ["2020-01-02"]}), 1, "success")

    def fetch_history(self, **_kwargs):
        return MarketCall(daily_frame(), 1, "success")

    def fetch_minutes(self, **_kwargs):
        return MarketCall(pd.DataFrame({
            "时间": ["2026-08-24 09:30:00", "2026-08-24 09:31:00"],
            "开盘": [1, 1], "收盘": [1, 1], "最高": [1, 1], "最低": [1, 1],
            "成交量": [10, 20],
        }), 1, "success")


class FakeCryptoAdapter:
    def fetch(self, *, interval, start_time, **_kwargs):
        seconds = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}[interval]
        times = [start_time + timedelta(seconds=seconds * index) for index in range(3)]
        return pd.DataFrame({
            "raw_instrument": "ETH-USDT", "data_provider": "okx_public_api",
            "raw_exchange": "OKX", "instrument_type": "spot", "bar_interval": interval,
            "confirmed": True, "trade_time": pd.to_datetime(times, utc=True),
            "open": [1, 1, 1], "high": [2, 2, 2], "low": [0.5, 0.5, 0.5],
            "close": [1.5, 1.5, 1.5], "volume": [10, 10, 10],
            "quote_volume": [15, 15, 15],
        })


def copy_config(tmp_path: Path) -> Path:
    path = tmp_path / "config/stage17.yml"
    path.parent.mkdir(parents=True)
    shutil.copy2(ROOT / "config/stage17.yml", path)
    return path


def test_quality_and_strict_listing_coverage_helpers():
    assert validate_equity_daily(daily_frame())["status"] == "PASS"
    profile = pd.DataFrame({"项目": ["上市时间"], "值": ["2020-01-02"]})
    assert extract_listing_date(profile) == date(2020, 1, 2)
    assert listing_coverage_status(date(2020, 1, 2), "2020-02-01") == "provider_history_shorter_than_listing"
    broken = daily_frame().copy()
    broken.loc[1, "最高"] = 0
    assert validate_equity_daily(broken)["status"] == "FAIL"


def test_validate_and_dry_run_never_write_or_call_network(tmp_path):
    config = copy_config(tmp_path)

    class Exploding:
        def __getattr__(self, _name):
            raise AssertionError("network adapter must not be touched")

    for validate_only, dry_run in ((True, False), (False, True)):
        result, code = run_stage17(
            root=tmp_path, config_path=config, as_of_date=date(2026, 8, 24),
            validate_only=validate_only, dry_run=dry_run,
            a_adapter=Exploding(), hk_adapter=Exploding(), crypto_adapter=Exploding(),
        )
        assert code == 0 and result["status"] == "READY"
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "reports").exists()


def test_complete_offline_run_has_closed_manifest_and_pass(tmp_path):
    config = copy_config(tmp_path)
    run_id = "11111111-1111-4111-8111-111111111117"
    ticks = iter(datetime(2026, 8, 24, 1, index, tzinfo=timezone.utc) for index in range(60))
    result, code = run_stage17(
        root=tmp_path, config_path=config, as_of_date=date(2026, 8, 24),
        run_id=run_id, a_adapter=FakeEquityAdapter(), hk_adapter=FakeEquityAdapter(),
        crypto_adapter=FakeCryptoAdapter(), now=lambda: next(ticks), sleeper=lambda _: None,
    )
    assert code == 0 and result["status"] == "PASS"
    assert result["counts"]["daily_success"] == 69
    assert result["counts"]["daily_nonempty_count"] == 69
    assert result["counts"]["daily_quality_pass_count"] == 69
    assert result["counts"]["daily_success_semantics"] == (
        "compatibility_alias_of_daily_nonempty_count"
    )
    assert result["counts"]["crypto_success"] == 6
    report_dir = tmp_path / "reports/stage17" / run_id
    manifest = json.loads((report_dir / "stage17_manifest.json").read_text(encoding="utf-8"))
    assert manifest["raw_manifest_closed_world"] is True
    assert manifest["status"] == "PASS"
    assert result["stage18_authorized"] is True
    assert (report_dir / "minute_data_feasibility_report.md").is_file()


def test_crypto_gap_is_a_formal_quality_failure():
    frame = FakeCryptoAdapter().fetch(
        interval="1h", start_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
    ).drop(index=1)
    assert "time_continuity_gap" in validate_crypto(frame, "1h")["errors"]

class FallbackPassAdapter(FakeEquityAdapter):
    def fetch_history(self, **_kwargs):
        return MarketCall(
            None, 3, "failed", "connection_error", "primary unavailable"
        )

    def fetch_history_fallback(self, **_kwargs):
        return MarketCall(daily_frame(), 1, "success")


class HkBothInvalidAdapter(FakeEquityAdapter):
    def fetch_history(self, **_kwargs):
        broken = daily_frame()
        broken.loc[0, "最高"] = 0
        return MarketCall(broken, 1, "success")

    def fetch_history_fallback(self, **_kwargs):
        broken = daily_frame()
        broken.loc[1, "最低"] = 99
        return MarketCall(broken, 1, "success")


def test_explicit_fallback_is_selected_and_audited_in_same_run(tmp_path):
    config = copy_config(tmp_path)
    run_id = "22222222-2222-4222-8222-222222222217"
    ticks = iter(
        datetime(2026, 8, 24, 2, index, tzinfo=timezone.utc)
        for index in range(60)
    )
    result, code = run_stage17(
        root=tmp_path, config_path=config, as_of_date=date(2026, 8, 24),
        run_id=run_id, a_adapter=FallbackPassAdapter(),
        hk_adapter=FallbackPassAdapter(), crypto_adapter=FakeCryptoAdapter(),
        now=lambda: next(ticks), sleeper=lambda _: None,
    )
    assert code == 0 and result["status"] == "PASS"
    manifest = json.loads(
        (tmp_path / "reports/stage17" / run_id / "stage17_manifest.json")
        .read_text(encoding="utf-8")
    )
    formal = [row for row in manifest["datasets"] if row["kind"] == "equity_daily"]
    attempts = [
        row for row in manifest["datasets"]
        if row["kind"] == "equity_daily_attempt"
    ]
    assert len(formal) == 69 and len(attempts) == 69
    assert {row["selected_source"] for row in formal} == {"sina"}
    assert all("source=sina" in row["data_path"] for row in formal)
    assert manifest["raw_manifest_closed_world"] is True


def test_two_invalid_hk_sources_remain_blocked_without_value_repair(tmp_path):
    config = copy_config(tmp_path)
    run_id = "33333333-3333-4333-8333-333333333317"
    ticks = iter(
        datetime(2026, 8, 24, 3, index, tzinfo=timezone.utc)
        for index in range(60)
    )
    result, code = run_stage17(
        root=tmp_path, config_path=config, as_of_date=date(2026, 8, 24),
        run_id=run_id, a_adapter=FakeEquityAdapter(),
        hk_adapter=HkBothInvalidAdapter(), crypto_adapter=FakeCryptoAdapter(),
        now=lambda: next(ticks), sleeper=lambda _: None,
    )
    assert code == 2 and result["status"] == "BLOCKED"
    assert result["counts"]["daily_nonempty_count"] == 48
    assert result["counts"]["daily_quality_pass_count"] == 48
    assert {item["category"] for item in result["blocker_details"]} == {
        "upstream_ohlc_inconsistency"
    }
    manifest = json.loads(
        (tmp_path / "reports/stage17" / run_id / "stage17_manifest.json")
        .read_text(encoding="utf-8")
    )
    candidates = [
        row for row in manifest["datasets"]
        if row["kind"] == "equity_daily_candidate"
    ]
    assert len(candidates) == 42
    assert {row["source"] for row in candidates} == {"eastmoney", "sina"}
    assert all(row["quality_status"] == "FAIL" for row in candidates)
    assert manifest["raw_manifest_closed_world"] is True
