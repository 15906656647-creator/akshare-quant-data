from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from akshare_data_test.assets import ETHUSDT_OKX_SPOT
from akshare_data_test.crypto_evidence import validate_raw_evidence, write_raw_evidence
from akshare_data_test.stage11_build import analyze_stage11


ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "stage11-manifest-closed-world"


def raw_frame(periods: int = 960) -> pd.DataFrame:
    close = 1800 + np.arange(periods, dtype=float) / 10
    return pd.DataFrame({
        "raw_instrument": "ETH-USDT", "data_provider": "okx_public_api",
        "raw_exchange": "OKX", "instrument_type": "spot", "bar_interval": "1h",
        "confirmed": True,
        "trade_time": pd.date_range("2026-06-18T00:00:00Z", periods=periods, freq="h"),
        "open": close - 1, "high": close + 2, "low": close - 3, "close": close,
        "volume": 10 + np.arange(periods), "quote_volume": (10 + np.arange(periods)) * close,
    })


def make_evidence(path: Path, periods: int = 8) -> Path:
    write_raw_evidence(
        path, run_id=RUN_ID, provider="okx_public_api",
        endpoint="https://www.okx.com/api/v5/market/history-candles",
        request_parameters={"instId": "ETH-USDT", "bar": "1H"},
        response=raw_frame(periods), identity=ETHUSDT_OKX_SPOT,
        fetched_at=pd.Timestamp("2026-07-28T00:10:00Z"),
    )
    return path


def snapshot(path: Path) -> dict[str, tuple[str, int, int]]:
    return {
        item.relative_to(path).as_posix(): (
            hashlib.sha256(item.read_bytes()).hexdigest(), item.stat().st_size,
            item.stat().st_mtime_ns,
        )
        for item in path.rglob("*") if item.is_file()
    }


@pytest.mark.parametrize(
    ("relative_path", "content"),
    [
        ("orphan.json", b"{}\n"),
        ("nested/orphan.json", b"{}\n"),
        ("response.json.bak", b"backup"),
        ("response.json.tmp", b"temporary"),
        (".unlisted", b"hidden"),
        ("empty-file", b""),
        ("payload.bin", b"\x00\xff\x10\x80"),
    ],
)
def test_unlisted_ordinary_files_fail_closed(tmp_path, relative_path, content):
    evidence = make_evidence(tmp_path / "raw")
    extra = evidence / relative_path
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_bytes(content)
    before = snapshot(evidence)
    result = validate_raw_evidence(evidence, run_id=RUN_ID, expected=ETHUSDT_OKX_SPOT)
    assert result["status"] == "BLOCKED"
    assert f"manifest_unlisted_file: {relative_path}" in result["blocking_reasons"]
    assert result["manifest_closed_world"] == {
        "check_name": "manifest_closed_world", "status": "FAIL",
        "error_code": "manifest_unlisted_file",
        "unlisted_files": [relative_path], "missing_files": [],
    }
    assert snapshot(evidence) == before


def test_multiple_unlisted_files_are_all_reported_in_stable_order(tmp_path):
    evidence = make_evidence(tmp_path / "raw")
    extras = {"z.tmp": b"z", ".hidden": b"h", "a/orphan.bin": b"\x00"}
    for relative_path, content in extras.items():
        target = evidence / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    result = validate_raw_evidence(evidence, run_id=RUN_ID, expected=ETHUSDT_OKX_SPOT)
    assert result["manifest_closed_world"]["unlisted_files"] == [
        ".hidden", "a/orphan.bin", "z.tmp"
    ]
    assert [
        reason for reason in result["blocking_reasons"]
        if reason.startswith("manifest_unlisted_file:")
    ] == [
        "manifest_unlisted_file: .hidden",
        "manifest_unlisted_file: a/orphan.bin",
        "manifest_unlisted_file: z.tmp",
    ]


def test_normal_manifest_directory_remains_ready(tmp_path):
    evidence = make_evidence(tmp_path / "raw")
    result = validate_raw_evidence(evidence, run_id=RUN_ID, expected=ETHUSDT_OKX_SPOT)
    assert result["status"] == "READY"
    assert result["manifest_closed_world"] == {
        "check_name": "manifest_closed_world", "status": "PASS",
        "error_code": None, "unlisted_files": [], "missing_files": [],
    }


def test_declared_additional_file_is_explicitly_rejected_by_current_role_contract(tmp_path):
    evidence = make_evidence(tmp_path / "raw")
    extra = evidence / "sidecar.bin"
    extra.write_bytes(b"sidecar")
    manifest_path = evidence / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["evidence_files"].append({
        "role": "sidecar", "name": "sidecar.bin",
        "sha256": hashlib.sha256(extra.read_bytes()).hexdigest(),
        "size_bytes": extra.stat().st_size,
    })
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    result = validate_raw_evidence(evidence, run_id=RUN_ID, expected=ETHUSDT_OKX_SPOT)
    assert result["status"] == "BLOCKED"
    assert "raw_manifest_unknown_role: sidecar" in result["blocking_reasons"]
    assert result["manifest_closed_world"]["status"] == "PASS"


@pytest.fixture(scope="module")
def valid_workspace(tmp_path_factory) -> Path:
    workspace = tmp_path_factory.mktemp("stage11-closed-world-cli-source")
    (workspace / "config").mkdir()
    (workspace / "sql").mkdir()
    shutil.copy2(ROOT / "config/stage11.yml", workspace / "config/stage11.yml")
    shutil.copy2(ROOT / "sql/stage11_schema.sql", workspace / "sql/stage11_schema.sql")
    evidence = make_evidence(workspace / "raw", periods=960)
    report, code = analyze_stage11(
        root=workspace, as_of_date=pd.Timestamp("2026-07-27"),
        input_frame=raw_frame(), interval="1h", source="okx_public_api",
        config_path=workspace / "config/stage11.yml",
        output_database=workspace / "database/stage11.duckdb",
        run_id=RUN_ID, raw_evidence_dir=evidence,
    )
    assert code == 0 and report["run_status"] == "PASS"
    return workspace


def install_network_guard(path: Path) -> tuple[Path, dict[str, str]]:
    guard = path / "network_guard"
    guard.mkdir()
    count_file = guard / "network_calls.txt"
    (guard / "sitecustomize.py").write_text(
        "import atexit, os, pathlib, socket\n"
        "count = [0]\n"
        "def blocked(*args, **kwargs):\n"
        "    count[0] += 1\n"
        "    raise AssertionError('network access forbidden in validate-only')\n"
        "socket.create_connection = blocked\n"
        "socket.socket.connect = blocked\n"
        "@atexit.register\n"
        "def save_count():\n"
        "    pathlib.Path(os.environ['NETWORK_COUNT_FILE']).write_text(str(count[0]))\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(guard) + os.pathsep + environment.get("PYTHONPATH", "")
    environment["NETWORK_COUNT_FILE"] = str(count_file)
    environment.update({
        "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1",
        "ALL_PROXY": "http://127.0.0.1:1", "NO_PROXY": "",
    })
    return count_file, environment


@pytest.mark.parametrize("relative_path", ["orphan.json", "nested/orphan.json"])
def test_production_cli_propagates_closed_world_failure_read_only(
    tmp_path, valid_workspace, relative_path
):
    workspace = tmp_path / "workspace"
    shutil.copytree(valid_workspace, workspace)
    extra = workspace / "raw" / relative_path
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_text("{}\n", encoding="utf-8")
    count_file, environment = install_network_guard(tmp_path)
    before = snapshot(workspace)
    completed = subprocess.run(
        [
            sys.executable, str(ROOT / "run_pipeline.py"), "validate-crypto",
            "--as-of-date", "2026-07-27",
            "--config", str(workspace / "config/stage11.yml"),
            "--input-csv", str(workspace / "reports/stage11_crypto_price.csv"),
            "--input-json", str(workspace / "reports/stage11_crypto_price.json"),
            "--raw-evidence-dir", str(workspace / "raw"),
            "--reports-dir", str(workspace / "reports"),
            "--output-database", str(workspace / "database/stage11.duckdb"),
            "--run-id", RUN_ID, "--validate-only",
        ],
        cwd=ROOT, env=environment, text=True, capture_output=True, encoding="utf-8",
    )
    after = snapshot(workspace)
    payload = json.loads(completed.stdout)
    assert completed.returncode != 0
    assert payload["status"] == "BLOCKED"
    assert "READY" not in completed.stdout
    assert f"manifest_unlisted_file: {relative_path}" in payload["blocking_reasons"]
    assert payload["raw_evidence"]["manifest_closed_world"]["unlisted_files"] == [relative_path]
    assert before == after
    assert count_file.read_text(encoding="utf-8") == "0"
