from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from akshare_data_test.presentation import ChartRenderer


def test_price_and_volume_charts_are_headless_and_close_figures(tmp_path):
    dates = pd.date_range("2026-01-01", periods=30, freq="D")
    price = pd.DataFrame({"trade_date": dates, "close_qfq": range(30)})
    for window in (3, 5, 7, 10, 13, 20, 21):
        price[f"ma_{window}"] = price.close_qfq.rolling(window).mean()
    volume = pd.DataFrame({"trade_date": dates, "volume_share": range(1, 31)})
    volume["volume_ma_5"] = volume.volume_share.rolling(5).mean()
    volume["volume_ma_20"] = volume.volume_share.rolling(20).mean()
    renderer = ChartRenderer(dpi=100, as_of_date=pd.Timestamp("2026-07-27"), run_id="test")
    renderer.price_ma(price, tmp_path / "price.png", "000001")
    renderer.volume_ma(volume, tmp_path / "volume.png", "000001")
    assert (tmp_path / "price.png").stat().st_size > 0
    assert (tmp_path / "volume.png").stat().st_size > 0
    assert plt.get_fignums() == []
