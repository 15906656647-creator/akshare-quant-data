from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_contains_no_future_coverage():
    assets = pd.read_csv(ROOT / "reports/stage13/stage13_asset_manifest.csv", dtype={"symbol": str}, keep_default_na=False)
    visible = pd.to_datetime(assets.loc[assets.source_date_max.ne(""), "source_date_max"])
    assert visible.le(pd.Timestamp("2026-07-27")).all()
    valuation = assets.loc[assets.asset_id.eq("valuation_snapshot")]
    assert valuation.status.eq("NOT_AVAILABLE").all()
    assert valuation.output_path.eq("").all()
