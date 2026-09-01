from __future__ import annotations

import threading

import pandas as pd

from akshare_data_test.adapters.stock_market import MarketCall
from akshare_data_test.stage17_collect import (
    _bounded_minute_fetch,
    _should_disable_minute_network,
)


def test_outer_minute_timeout_fails_closed_when_adapter_never_returns() -> None:
    gate = threading.Event()

    class Hanging:
        def fetch_minutes(self, **_kwargs: object) -> MarketCall:
            gate.wait(5)
            return MarketCall(pd.DataFrame({"x": [1]}), 1, "success")

    result = _bounded_minute_fetch(Hanging(), hard_timeout_seconds=0.01)
    assert result.status == "failed"
    assert result.error_type == "timeout"
    assert "outer hard timeout" in result.error_message
    gate.set()


def test_outer_minute_timeout_preserves_normal_result() -> None:
    expected = MarketCall(pd.DataFrame({"x": [1]}), 1, "success")

    class Passing:
        def fetch_minutes(self, **_kwargs: object) -> MarketCall:
            return expected

    assert _bounded_minute_fetch(Passing(), hard_timeout_seconds=1) is expected

def test_minute_network_is_disabled_after_connection_class_failure() -> None:
    for error_type in ("timeout", "connection_error"):
        call = MarketCall(None, 3, "failed", error_type, "upstream unavailable")
        assert _should_disable_minute_network(call) is True


def test_minute_network_is_not_disabled_after_non_connection_result() -> None:
    assert _should_disable_minute_network(MarketCall(None, 1, "empty")) is False
    success = MarketCall(pd.DataFrame({"x": [1]}), 1, "success")
    assert _should_disable_minute_network(success) is False
