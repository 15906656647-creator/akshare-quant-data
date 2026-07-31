from __future__ import annotations

import subprocess
import sys
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STAGE7_RUNTIME_FILES = [
    ROOT / "src/akshare_data_test/stage7_build.py",
    ROOT / "src/akshare_data_test/features/stock_daily_features.py",
    ROOT / "src/akshare_data_test/features/activity_score.py",
    ROOT / "src/akshare_data_test/storage/feature_repository.py",
    ROOT / "src/akshare_data_test/quality/feature_checks.py",
]


def test_stage7_runtime_has_no_network_client_or_akshare_import():
    prohibited = [
        r"\bimport\s+akshare(?:\s|$)",
        r"\bfrom\s+akshare(?:\s|$)",
        r"\bimport\s+requests(?:\s|$)",
        r"\bimport\s+httpx(?:\s|$)",
        r"\burllib\.request\b",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in STAGE7_RUNTIME_FILES)
    assert not any(re.search(pattern, text, flags=re.MULTILINE) for pattern in prohibited)


def test_cli_missing_source_returns_nonzero_and_no_output_database(tmp_path):
    output = tmp_path / "must_not_exist.duckdb"
    result = subprocess.run(
        [
            sys.executable,
            "run_pipeline.py",
            "build-features",
            "--as-of-date",
            "2026-07-27",
            "--source-database",
            str(tmp_path / "missing.duckdb"),
            "--output-database",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert not output.exists()
