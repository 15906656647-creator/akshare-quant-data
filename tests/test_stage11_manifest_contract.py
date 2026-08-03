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
RUN_ID = "stage11-manifest-contract"


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


def load_manifest(path: Path) -> dict:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))


def save_manifest(path: Path, manifest: dict) -> None:
    (path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def snapshot(path: Path) -> dict[str, tuple[str, int]]:
    return {
        str(item.relative_to(path)): (hashlib.sha256(item.read_bytes()).hexdigest(), item.stat().st_mtime_ns)
        for item in path.rglob("*") if item.is_file()
    }


def entry_for(path: Path, role: str, name: str) -> dict:
    target = path / name
    return {"role": role, "name": name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "size_bytes": target.stat().st_size}


def mutate_manifest(path: Path, case: str) -> None:
    manifest = load_manifest(path)
    entries = manifest["evidence_files"]
    if case.startswith("missing_role_"):
        role = case.removeprefix("missing_role_")
        manifest["evidence_files"] = [item for item in entries if item["role"] != role]
    elif case == "duplicate_exact_path":
        entries.append(dict(entries[1]))
    elif case == "duplicate_role_different_path":
        shutil.copy2(path / "response.json", path / "response-copy.json")
        entries.append(entry_for(path, "response", "response-copy.json"))
    elif case == "duplicate_casefold_path":
        duplicate = dict(entries[1]); duplicate["name"] = "RESPONSE.JSON"; entries.append(duplicate)
    elif case == "duplicate_separator_path":
        first = dict(entries[1]); first["name"] = ".\\response.json"
        second = dict(entries[1]); second["name"] = "./response.json"
        entries.extend([first, second])
    elif case == "duplicate_dot_path":
        duplicate = dict(entries[1]); duplicate["name"] = "./response.json"; entries.append(duplicate)
    elif case == "absolute_path":
        entries[1]["name"] = str((path / "response.json").resolve())
    elif case == "parent_traversal":
        entries[1]["name"] = "subdir/../response.json"
    elif case == "listed_file_missing":
        entries[1]["name"] = "missing.json"
    elif case == "response_json_and_parquet":
        (path / "response.parquet").write_bytes(b"not-a-real-parquet-sidecar")
        entries.append(entry_for(path, "response", "response.parquet"))
    elif case == "size_mismatch":
        entries[1]["size_bytes"] += 1
    elif case == "hash_mismatch":
        entries[1]["sha256"] = "0" * 64
    elif case == "entries_not_array":
        manifest["evidence_files"] = {"unexpected": "object"}
    elif case.startswith("missing_field_"):
        field = case.removeprefix("missing_field_")
        entries[1].pop(field)
    else:
        raise AssertionError(f"unknown case: {case}")
    save_manifest(path, manifest)


@pytest.mark.parametrize(
    ("case", "error_code"),
    [
        ("missing_role_request", "raw_manifest_missing_role: request"),
        ("missing_role_response", "raw_manifest_missing_role: response"),
        ("missing_role_metadata", "raw_manifest_missing_role: metadata"),
        ("duplicate_exact_path", "raw_manifest_duplicate_path"),
        ("duplicate_role_different_path", "raw_manifest_duplicate_role: response"),
        ("duplicate_casefold_path", "raw_manifest_duplicate_path: response.json"),
        ("duplicate_separator_path", "raw_manifest_duplicate_path: response.json"),
        ("duplicate_dot_path", "raw_manifest_duplicate_path: response.json"),
        ("absolute_path", "raw_manifest_invalid_path"),
        ("parent_traversal", "raw_manifest_invalid_path"),
        ("listed_file_missing", "raw_manifest_file_missing"),
        ("response_json_and_parquet", "raw_manifest_duplicate_role: response"),
        ("size_mismatch", "raw_manifest_file_size_mismatch"),
        ("hash_mismatch", "raw_manifest_file_hash_mismatch"),
        ("entries_not_array", "raw_manifest_entries_invalid"),
        ("missing_field_role", "raw_manifest_entry_missing_field"),
        ("missing_field_name", "raw_manifest_entry_missing_field"),
        ("missing_field_sha256", "raw_manifest_entry_invalid_hash"),
        ("missing_field_size_bytes", "raw_manifest_entry_invalid_size"),
    ],
)
def test_manifest_faults_fail_closed_without_mutating_evidence(tmp_path, case, error_code):
    evidence = make_evidence(tmp_path / "raw")
    mutate_manifest(evidence, case)
    before = snapshot(evidence)
    result = validate_raw_evidence(evidence, run_id=RUN_ID, expected=ETHUSDT_OKX_SPOT)
    after = snapshot(evidence)
    assert result["status"] == "BLOCKED"
    assert any(error_code in reason for reason in result["blocking_reasons"])
    assert before == after


def test_valid_manifest_has_exact_roles_paths_hashes_and_sizes(tmp_path):
    evidence = make_evidence(tmp_path / "raw")
    manifest = load_manifest(evidence)
    entries = manifest["evidence_files"]
    assert [(item["role"], item["name"]) for item in entries] == [
        ("request", "request.json"), ("response", "response.json"), ("metadata", "metadata.json")
    ]
    assert all(item["size_bytes"] == (evidence / item["name"]).stat().st_size for item in entries)
    result = validate_raw_evidence(evidence, run_id=RUN_ID, expected=ETHUSDT_OKX_SPOT)
    assert result["status"] == "READY" and result["blocking_reasons"] == []


@pytest.fixture(scope="module")
def valid_workspace(tmp_path_factory) -> Path:
    workspace = tmp_path_factory.mktemp("stage11-manifest-cli-source")
    (workspace / "config").mkdir(); (workspace / "sql").mkdir()
    shutil.copy2(ROOT / "config/stage11.yml", workspace / "config/stage11.yml")
    shutil.copy2(ROOT / "sql/stage11_schema.sql", workspace / "sql/stage11_schema.sql")
    evidence = make_evidence(workspace / "raw", periods=960)
    report, code = analyze_stage11(
        root=workspace, as_of_date=pd.Timestamp("2026-07-27"), input_frame=raw_frame(), interval="1h",
        source="okx_public_api", config_path=workspace / "config/stage11.yml",
        output_database=workspace / "database/stage11.duckdb", run_id=RUN_ID,
        raw_evidence_dir=evidence,
    )
    assert code == 0 and report["run_status"] == "PASS"
    return workspace


@pytest.mark.parametrize(
    ("case", "error_code"),
    [("missing_role_metadata", "raw_manifest_missing_role"),
     ("duplicate_exact_path", "raw_manifest_duplicate_path")],
)
def test_validate_crypto_cli_propagates_manifest_failure_read_only(
    tmp_path, valid_workspace, case, error_code
):
    workspace = tmp_path / "workspace"
    shutil.copytree(valid_workspace, workspace)
    evidence = workspace / "raw"
    mutate_manifest(evidence, case)
    protected = [workspace / "database/stage11.duckdb", *evidence.iterdir(), *(workspace / "reports").iterdir()]
    before = {str(path): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in protected}
    command = [
        sys.executable, str(ROOT / "run_pipeline.py"), "validate-crypto", "--as-of-date", "2026-07-27",
        "--config", str(workspace / "config/stage11.yml"),
        "--input-csv", str(workspace / "reports/stage11_crypto_price.csv"),
        "--input-json", str(workspace / "reports/stage11_crypto_price.json"),
        "--raw-evidence-dir", str(evidence), "--reports-dir", str(workspace / "reports"),
        "--output-database", str(workspace / "database/stage11.duckdb"),
        "--run-id", RUN_ID, "--validate-only",
    ]
    environment = os.environ.copy()
    environment.update({"HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1"})
    completed = subprocess.run(command, cwd=ROOT, env=environment, text=True, capture_output=True)
    payload = json.loads(completed.stdout)
    after = {str(path): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns) for path in protected}
    assert completed.returncode != 0
    assert payload["status"] == "BLOCKED" and payload["status"] != "READY"
    assert any(error_code in reason for reason in payload["blocking_reasons"])
    assert before == after
