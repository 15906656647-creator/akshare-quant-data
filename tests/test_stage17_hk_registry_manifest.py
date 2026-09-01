from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from akshare_data_test.adapters.hk_provider_registry import (
    HkProviderAttempt,
    HkProviderSelection,
)
from akshare_data_test.stage17_collect import _collect_hk_registry_daily_dataset
from akshare_data_test.stage17_config import load_stage17_config
from akshare_data_test.storage.stage17_raw_store import Stage17RawStore


ROOT = Path(__file__).resolve().parents[1]


def _frame(*, broken: bool = False) -> pd.DataFrame:
    frame = pd.DataFrame({
        "date": ["2020-01-02", "2020-01-03"], "open": [10.0, 10.2],
        "high": [10.5, 10.6], "low": [9.8, 10.0], "close": [10.2, 10.4],
        "volume": [100, 120],
    })
    if broken:
        frame.loc[0, "high"] = 9.0
    return frame


def _call(frame: pd.DataFrame, *, blocks: tuple[object, ...] = ()) -> SimpleNamespace:
    return SimpleNamespace(
        dataframe=frame, source_frame=frame, status="success", attempt_count=1,
        error_type="", error_message="", duplicate_rows_removed=236, blocks=blocks,
    )


class _Registry:
    def __init__(self, selection: HkProviderSelection) -> None:
        self.selection = selection

    def select_history(self, **_kwargs: object) -> HkProviderSelection:
        return self.selection


def _target(symbol: str):
    config = load_stage17_config(ROOT / "config/stage17.yml")
    return config, next(target for target in config.equities if target.symbol == symbol)


def test_manifest_row_records_rejected_provider_and_selected_provider(tmp_path: Path) -> None:
    config, target = _target("08462.HK")
    failed_quality = {
        "status": "FAIL", "errors": ["ohlc_logic_error"],
        "min_date": "2020-01-02", "max_date": "2020-01-03",
    }
    pass_quality = {
        "status": "PASS", "errors": [],
        "min_date": "2020-01-02", "max_date": "2020-01-03",
    }
    tencent = HkProviderAttempt(
        "tencent", "stock_zh_ah_daily", _call(_frame(broken=True)),
        failed_quality, "complete_to_verified_listing_date", "ohlc_logic_error",
    )
    eastmoney = HkProviderAttempt(
        "eastmoney", "stock_hk_hist", _call(_frame()), pass_quality,
        "complete_to_verified_listing_date", "",
    )
    registry = _Registry(HkProviderSelection(
        (tencent, eastmoney), eastmoney,
        "eastmoney_passed_identity_quality_coverage_adjust_semantics",
    ))
    formal, audit = _collect_hk_registry_daily_dataset(
        config=config, target=target, registry=registry,
        store=Stage17RawStore(tmp_path / "data/raw/stage17"), root=tmp_path,
        run_id="11111111-1111-4111-8111-111111111117",
        fetched_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        listing_date=date(2020, 1, 2), as_of_date=date(2026, 8, 24), adjust="qfq",
    )
    assert formal["selected_provider"] == "eastmoney"
    assert [row["provider"] for row in formal["provider_attempts"]] == ["tencent", "eastmoney"]
    assert formal["provider_attempts"][0]["rejection_reason"] == "ohlc_logic_error"
    assert len(audit) == 1 and audit[0]["source"] == "tencent"
    metadata = json.loads((tmp_path / formal["metadata_path"]).read_text(encoding="utf-8"))
    assert metadata["selected_provider"] == "eastmoney"
    assert metadata["provider_attempts"][0]["selected"] is False


def test_09669_compatibility_fields_are_exposed_in_formal_manifest_row(tmp_path: Path) -> None:
    config, target = _target("09669.HK")
    frame = _frame()
    block = SimpleNamespace(
        requested_key="qfqday", used_key="day", field_fallback=True,
    )
    quality = {
        "status": "PASS", "errors": [],
        "min_date": "2020-01-02", "max_date": "2020-01-03",
    }
    compat = HkProviderAttempt(
        "tencent_compat", "tencent_hkfqkline_direct_https",
        _call(frame, blocks=(block, block)), quality,
        "complete_to_verified_listing_date", "",
    )
    registry = _Registry(HkProviderSelection(
        (compat,), compat,
        "tencent_compat_passed_identity_quality_coverage_adjust_semantics",
    ))
    formal, _ = _collect_hk_registry_daily_dataset(
        config=config, target=target, registry=registry,
        store=Stage17RawStore(tmp_path / "data/raw/stage17"), root=tmp_path,
        run_id="22222222-2222-4222-8222-222222222217",
        fetched_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        listing_date=date(2020, 1, 2), as_of_date=date(2026, 8, 24), adjust="qfq",
    )
    assert formal["selected_provider"] == "tencent_compat"
    assert formal["requested_response_keys"] == ["qfqday", "qfqday"]
    assert formal["used_response_keys"] == ["day", "day"]
    assert formal["response_field_fallback"] is True
