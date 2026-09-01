from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd

from akshare_data_test.adapters.hk_provider_registry import HkProviderRegistry
from akshare_data_test.adapters.stock_market import MarketCall
from akshare_data_test.stage17_collect import listing_coverage_status, validate_equity_daily
from akshare_data_test.stage17_config import EXPECTED_HK_PROVIDER_ROUTES


def _frame(*, broken: bool = False) -> pd.DataFrame:
    frame = pd.DataFrame({
        "date": ["2020-01-02", "2020-01-03"],
        "open": [10.0, 10.2], "high": [10.5, 10.6],
        "low": [9.8, 10.0], "close": [10.2, 10.4], "volume": [100, 120],
    })
    if broken:
        frame.loc[0, "high"] = 9.0
    return frame


def _call(frame: pd.DataFrame | None, *, error: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        dataframe=frame, source_frame=frame, status="success" if frame is not None else "failed",
        attempt_count=1, error_type=error, error_message=error,
        duplicate_rows_removed=0, blocks=(),
    )


class _Tencent:
    def fetch_history(self, *, symbol: str, adjust: str, **_kwargs: object) -> SimpleNamespace:
        broken = symbol == "08462.HK" and adjust in {"qfq", "hfq"}
        return _call(_frame(broken=broken))


class _Compat:
    def fetch_history(self, *, symbol: str, adjust: str, **_kwargs: object) -> SimpleNamespace:
        assert symbol in {"08462.HK", "09669.HK"} and adjust in {"qfq", "hfq"}
        return _call(_frame())


class _Eastmoney:
    akshare_version = "test"

    def fetch_history(self, **_kwargs: object) -> MarketCall:
        return MarketCall(_frame(), 1, "success")

    def fetch_history_fallback(self, **_kwargs: object) -> MarketCall:
        return MarketCall(_frame(broken=True), 1, "success")


def _registry() -> HkProviderRegistry:
    return HkProviderRegistry(
        routes=EXPECTED_HK_PROVIDER_ROUTES, eastmoney=_Eastmoney(),
        tencent=_Tencent(), tencent_compat=_Compat(),
    )


def _select(registry: HkProviderRegistry, symbol: str, adjust: str):
    return registry.select_history(
        symbol=symbol, listing_date=date(2020, 1, 2),
        as_of_date=date(2026, 8, 24), adjust=adjust,
        quality_validator=validate_equity_daily,
        coverage_validator=listing_coverage_status,
    )


def test_08462_raw_selects_tencent_but_adjusted_uses_compat_after_ohlc_fail() -> None:
    registry = _registry()
    raw = _select(registry, "08462.HK", "raw")
    assert raw.selected.provider == "tencent"
    for adjust in ("qfq", "hfq"):
        result = _select(registry, "08462.HK", adjust)
        assert result.selected.provider == "tencent_compat"
        assert [attempt.provider for attempt in result.attempts] == ["tencent", "tencent_compat"]
        assert result.attempts[0].rejection_reason == "ohlc_logic_error"


def test_09669_adjusted_uses_compat_route_and_does_not_hide_semantics() -> None:
    registry = _registry()
    for adjust in ("qfq", "hfq"):
        result = _select(registry, "09669.HK", adjust)
        assert result.selected.provider == "tencent_compat"
        assert result.selected.interface == "tencent_hkfqkline_direct_https"
        assert len(result.attempts) == 1


def test_nonempty_ohlc_failure_never_selects_and_all_fail_is_closed() -> None:
    registry = _registry()
    registry.routes = {
        **registry.routes,
        "02180.HK": {
            "raw": ("sina",), "qfq": ("sina",), "hfq": ("sina",),
        },
    }
    result = _select(registry, "02180.HK", "raw")
    assert result.selected is None
    assert result.selection_reason == "no_provider_passed_all_gates"
    assert result.attempts[0].rejection_reason == "ohlc_logic_error"


def test_connection_failure_continues_to_next_provider() -> None:
    registry = _registry()
    registry.tencent = SimpleNamespace(
        fetch_history=lambda **_kwargs: _call(None, error="connection_error")
    )
    result = _select(registry, "02180.HK", "raw")
    assert result.selected.provider == "eastmoney"
    assert result.attempts[0].rejection_reason == "connection_error"
