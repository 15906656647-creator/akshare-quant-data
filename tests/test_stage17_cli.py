from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*extra: str):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [
            sys.executable, str(ROOT / "run_pipeline.py"), "collect-stage17",
            "--as-of-date", "2026-08-24", *extra,
        ], cwd=ROOT, env=env, capture_output=True, text=True,
    )


def test_stage17_cli_validate_only_and_dry_run_are_offline():
    validated = run_cli("--validate-only")
    planned = run_cli("--dry-run")
    assert validated.returncode == 0, validated.stderr
    assert planned.returncode == 0, planned.stderr
    assert '"status": "READY"' in validated.stdout
    assert '"daily_expected_count": 69' in planned.stdout


def test_stage17_cli_rejects_date_drift():
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [
            sys.executable, str(ROOT / "run_pipeline.py"), "collect-stage17",
            "--as-of-date", "2026-08-23", "--validate-only",
        ], cwd=ROOT, env=env, capture_output=True, text=True,
    )
    assert completed.returncode == 1
    assert "must equal configured 2026-08-24" in completed.stderr
