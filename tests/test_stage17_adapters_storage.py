from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from akshare_data_test.adapters.hk_market import HkMarketAdapter, hk_source_symbol
from akshare_data_test.adapters.stage17_crypto import Stage17OkxAdapter
from akshare_data_test.adapters.stage17_a_market import (
    Stage17AShareAdapter, a_sina_symbol,
)
from akshare_data_test.adapters.stock_market import _call_with_default_http_timeout
from akshare_data_test.storage.stage17_raw_store import Stage17RawStore


def test_hk_identity_and_parameters_are_exact():
    calls = []

    class Ak:
        __version__ = "test"

        @staticmethod
        def stock_hk_hist(**kwargs):
            calls.append(kwargs)
            return pd.DataFrame({"日期": ["2026-08-24"]})

    assert hk_source_symbol("02180.HK") == "02180"
    with pytest.raises(ValueError):
        hk_source_symbol("2180")
    result = HkMarketAdapter(ak_module=Ak()).fetch_history(
        symbol="02180.HK", start_date="19700101", end_date="20260824", adjust="hfq",
    )
    assert result.status == "success"
    assert calls == [{
        "symbol": "02180", "period": "daily", "start_date": "19700101",
        "end_date": "20260824", "adjust": "hfq",
    }]


def test_okx_paginates_without_hard_cap_and_filters_unconfirmed():
    timestamps = [300000, 240000, 180000, 120000, 60000]
    calls = []

    def request_json(url, _timeout):
        query = parse_qs(urlparse(url).query)
        calls.append(query)
        cursor = int(query["after"][0])
        eligible = [stamp for stamp in timestamps if stamp < cursor]
        page = eligible[:2]
        return {"code": "0", "data": [
            [str(stamp), "1", "2", "0.5", "1.5", "10", "10", "15", "0" if stamp == 240000 else "1"]
            for stamp in page
        ]}

    adapter = Stage17OkxAdapter(
        request_json=request_json, sleeper=lambda _: None, inter_request_delay_seconds=0,
    )
    frame = adapter.fetch(
        symbol="ETHUSDT", interval="3m",
        start_time=datetime.fromtimestamp(0, timezone.utc),
        end_time=datetime.fromtimestamp(360, timezone.utc), limit=2,
    )
    assert len(calls) >= 3
    assert frame.confirmed.all()
    assert frame.raw_instrument.eq("ETH-USDT").all()
    assert frame.bar_interval.eq("3m").all()


def test_stage17_raw_store_is_atomic_and_append_only(tmp_path):
    store = Stage17RawStore(tmp_path / "data/raw/stage17")
    directory = store.dataset_dir(
        dataset="equity_daily", run_id="abc", market="A", symbol="002067",
        adjust="raw", source="sina",
    )
    result = store.write_dataset(pd.DataFrame({"日期": ["2026-08-24"]}), directory, {"run_id": "abc"})
    assert result["data_path"].is_file() and result["metadata_path"].is_file()
    assert not list(directory.glob("*.tmp"))
    with pytest.raises(FileExistsError):
        store.write_dataset(pd.DataFrame({"日期": ["2026-08-25"]}), directory, {"run_id": "abc"})

def test_a_share_primary_timeout_fallback_mapping_and_bounded_backoff():
    calls = []

    class Ak:
        __version__ = "test"

        @staticmethod
        def stock_zh_a_hist(**kwargs):
            calls.append(("primary", kwargs))
            raise ConnectionError("temporary connection")

        @staticmethod
        def stock_zh_a_daily(**kwargs):
            calls.append(("fallback", kwargs))
            return pd.DataFrame({"date": ["2026-08-21"]})

    delays = []
    adapter = Stage17AShareAdapter(
        ak_module=Ak(), max_attempts=3, retry_delay_seconds=2,
        max_retry_delay_seconds=3, request_timeout_seconds=17,
        sleeper=delays.append,
    )
    primary = adapter.fetch_history(
        symbol="002067", start_date="20060915", end_date="20260824", adjust="",
    )
    fallback = adapter.fetch_history_fallback(
        symbol="002067", start_date="20060915", end_date="20260824", adjust="qfq",
    )
    assert primary.status == "failed" and primary.attempt_count == 3
    assert fallback.status == "success"
    assert delays == [2, 3]
    assert calls[0][1]["timeout"] == 17
    assert calls[-1][1]["symbol"] == "sz002067"
    assert a_sina_symbol("600763") == "sh600763"


def test_hk_fallback_applies_only_requested_date_range():
    class Ak:
        __version__ = "test"

        @staticmethod
        def stock_hk_daily(**_kwargs):
            return pd.DataFrame({
                "date": ["2019-01-01", "2026-08-21", "2026-08-25"],
                "open": [1, 2, 3],
            })

    result = HkMarketAdapter(ak_module=Ak()).fetch_history_fallback(
        symbol="02180.HK", start_date="19700101", end_date="20260824", adjust="",
    )
    assert result.status == "success"
    assert result.dataframe["date"].tolist() == ["2019-01-01", "2026-08-21"]

def test_default_http_timeout_is_applied_and_restored(monkeypatch):
    import requests

    seen = []

    def fake_get(_url, **kwargs):
        seen.append(kwargs.get("timeout"))
        return object()

    monkeypatch.setattr(requests, "get", fake_get)
    original = requests.get

    def akshare_like_call():
        requests.get("https://example.invalid")
        return "ok"

    assert _call_with_default_http_timeout(
        akshare_like_call, parameters={}, timeout=7,
    ) == "ok"
    assert seen == [7]
    assert requests.get is original
