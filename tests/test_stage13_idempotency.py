from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from akshare_data_test.stage13_presentation import build_stage13_presentation


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports/stage13"


def _hashes():
    return {path.relative_to(REPORTS).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(REPORTS.rglob("*")) if path.is_file()}


def _formal_run_id() -> str:
    return json.loads((REPORTS / "stage13_run.json").read_text(encoding="utf-8"))["run_id"]


def test_identical_stage13_run_is_byte_stable():
    before = _hashes()
    manifest, code = build_stage13_presentation(
        root=ROOT, as_of_date=pd.Timestamp("2026-07-27"), config_path=ROOT / "config/stage13.yml",
        input_database=ROOT / "database/akshare_data_test_stage5_repaired.duckdb",
        reports_dir=REPORTS, run_id=_formal_run_id(),
    )
    assert code == 0 and manifest["status"] == "READY"
    assert _hashes() == before
