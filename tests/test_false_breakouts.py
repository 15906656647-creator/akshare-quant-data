from __future__ import annotations

import pandas as pd

from test_style_features import CONFIG, compute, daily


def test_confirmed_up_and_down_false_breakouts_use_prior_box():
    frame = daily(70)
    frame.loc[:39, ["open", "high", "low", "close"]] = [10, 10.2, 9.8, 10]
    frame.loc[40, ["open", "high", "low", "close"]] = [10.4, 10.6, 10.3, 10.5]
    frame.loc[41, ["open", "high", "low", "close"]] = [10, 10.1, 9.9, 10]
    frame.loc[50, ["open", "high", "low", "close"]] = [9.6, 9.7, 9.4, 9.5]
    frame.loc[51, ["open", "high", "low", "close"]] = [10, 10.1, 9.9, 10]
    row = compute(frame, windows=[40]).iloc[0]
    assert row.confirmed_false_breakout_up_count >= 1
    assert row.confirmed_false_breakout_down_count >= 1
    assert row.breakout_return_to_box_days == 1


def test_true_breakout_is_not_false_breakout():
    frame = daily(65)
    frame.loc[:39, ["open", "high", "low", "close"]] = [10, 10.2, 9.8, 10]
    frame.loc[40:, ["open", "high", "low", "close"]] = [11, 11.2, 10.8, 11]
    row = compute(frame, windows=[40]).iloc[0]
    assert row.breakout_up_count >= 1
    assert row.confirmed_false_breakout_up_count == 0


def test_near_as_of_breakout_is_pending_and_future_does_not_confirm_it():
    frame = daily(64)
    frame.loc[:59, ["open", "high", "low", "close"]] = [10, 10.2, 9.8, 10]
    frame.loc[60, ["open", "high", "low", "close"]] = [10.5, 10.6, 10.4, 10.5]
    frame.loc[61, ["open", "high", "low", "close"]] = [10, 10.1, 9.9, 10]
    cutoff = frame.loc[60, "trade_date"]
    pending = compute(frame, windows=[40], as_of=cutoff).iloc[0]
    confirmed = compute(frame, windows=[40], as_of=frame.loc[63, "trade_date"]).iloc[0]
    assert pending.pending_breakout_count >= 1
    assert pending.confirmed_false_breakout_up_count == 0
    assert confirmed.confirmed_false_breakout_up_count >= 1


def test_suspension_does_not_consume_confirmation_trading_day():
    frame = daily(65)
    frame.loc[:59, ["open", "high", "low", "close"]] = [10, 10.2, 9.8, 10]
    frame.loc[60, ["open", "high", "low", "close"]] = [10.5, 10.6, 10.4, 10.5]
    frame.loc[61, "volume_share"] = 0
    frame.loc[62, ["open", "high", "low", "close"]] = [10, 10.1, 9.9, 10]
    row = compute(frame, windows=[40]).iloc[0]
    assert row.confirmed_false_breakout_up_count >= 1

