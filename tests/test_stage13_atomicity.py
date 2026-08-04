from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from akshare_data_test.stage13_presentation import build_stage13_presentation


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports/stage13"


def _formal_run_id() -> str:
    return json.loads((REPORTS / "stage13_run.json").read_text(encoding="utf-8"))["run_id"]


def test_injected_chart_failure_preserves_published_report_and_cleans_temp():
    marker = REPORTS / "stage13_run.json"
    before = hashlib.sha256(marker.read_bytes()).hexdigest()
    with pytest.raises(RuntimeError, match="injected"):
        build_stage13_presentation(
            root=ROOT, as_of_date=pd.Timestamp("2026-07-27"), config_path=ROOT / "config/stage13.yml",
            input_database=ROOT / "database/akshare_data_test_stage5_repaired.duckdb",
            reports_dir=REPORTS, run_id=_formal_run_id(), fail_after_chart=1,
        )
    assert hashlib.sha256(marker.read_bytes()).hexdigest() == before
    assert not list((ROOT / "reports").glob(".stage13-*"))
