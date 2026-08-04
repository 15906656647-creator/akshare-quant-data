from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv/Scripts/python.exe"


def _formal_run_id() -> str:
    return json.loads((ROOT / "reports/stage13/stage13_run.json").read_text(encoding="utf-8"))["run_id"]


def test_stage13_cli_dry_run_is_json_only_and_does_not_change_report():
    marker = ROOT / "reports/stage13/stage13_run.json"
    before = marker.read_bytes()
    process = subprocess.run([
        str(PYTHON), "run_pipeline.py", "present-stage13",
        "--as-of-date", "2026-07-27", "--config", "config/stage13.yml",
        "--input-database", "database/akshare_data_test_stage5_repaired.duckdb",
        "--reports-dir", "reports/stage13", "--run-id", _formal_run_id(), "--dry-run",
    ], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
    payload = json.loads(process.stdout)
    assert process.returncode == 0 and payload["status"] == "READY"
    assert process.stdout.count("\n") <= 1
    assert marker.read_bytes() == before


def test_stage13_cli_invalid_date_is_structured_blocked():
    process = subprocess.run([
        str(PYTHON), "run_pipeline.py", "present-stage13", "--as-of-date", "invalid",
        "--run-id", "bad",
    ], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=False)
    assert process.returncode != 0
    assert json.loads(process.stdout)["status"] == "BLOCKED"
