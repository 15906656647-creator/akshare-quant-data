from pathlib import Path

import pandas as pd

from akshare_data_test.quality.stage13_checks import validate_asset_manifest


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports/stage13"


def test_formal_report_has_complete_asset_matrix_and_matching_files():
    assets = pd.read_csv(REPORTS / "stage13_asset_manifest.csv", dtype={"symbol": str}, keep_default_na=False)
    assert len(assets) == 16 * 9
    assert assets.groupby("symbol").size().eq(9).all()
    assert set(assets.status) == {"AVAILABLE", "PARTIAL", "NOT_AVAILABLE"}
    assert validate_asset_manifest(assets, REPORTS) == []


def test_report_contains_required_safety_and_reproduction_sections():
    text = (REPORTS / "stage13_presentation.md").read_text(encoding="utf-8")
    assert "Reproducible SQL" in text
    assert "Network attempts: 0" in text
    assert "does not provide investment advice" in text
    assert str(ROOT) not in text
