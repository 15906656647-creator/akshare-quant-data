from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from adjustment.hk_adjustment import apply_hk_adjustment
from akshare_data_test.adapters.hk_manual_provider import HkManualProvider
from akshare_data_test.stage17_hk_audit import HK_SYMBOLS
from akshare_data_test.stage17_hk_manual_validation import run_manual_validation


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(root: Path, run_id: str) -> None:
    datasets: list[dict[str, object]] = []
    raw_files: list[dict[str, object]] = []
    for symbol in HK_SYMBOLS:
        directory = (
            root / "data/raw/stage17/equity_profile" / f"run_id={run_id}"
            / "market=HK" / f"symbol={symbol}"
        )
        directory.mkdir(parents=True)
        data_path = directory / "data.parquet"
        metadata_path = directory / "metadata.json"
        pd.DataFrame({"证券代码": [symbol], "上市日期": ["2023-04-13"]}).to_parquet(
            data_path, index=False
        )
        metadata_path.write_text(json.dumps({"symbol": symbol}), encoding="utf-8")
        data_rel = data_path.relative_to(root).as_posix()
        metadata_rel = metadata_path.relative_to(root).as_posix()
        dataset_id = f"profile:{symbol}"
        datasets.append({
            "dataset_id": dataset_id, "kind": "equity_profile", "market": "HK",
            "symbol": symbol, "quality_status": "PASS", "listing_date": "2023-04-13",
            "data_path": data_rel, "metadata_path": metadata_rel,
            "data_sha256": _hash(data_path), "metadata_sha256": _hash(metadata_path),
        })
        for role, path, relative in (
            ("data", data_path, data_rel), ("metadata", metadata_path, metadata_rel),
        ):
            raw_files.append({
                "dataset_id": dataset_id, "role": role, "path": relative,
                "size_bytes": path.stat().st_size, "sha256": _hash(path),
            })
    report_dir = root / "reports/stage17" / run_id
    report_dir.mkdir(parents=True)
    (report_dir / "stage17_manifest.json").write_text(json.dumps({
        "stage": 17, "run_id": run_id, "as_of_date": "2026-08-24",
        "status": "BLOCKED", "datasets": datasets, "raw_files": raw_files,
    }), encoding="utf-8")
    (report_dir / "stage17_run.json").write_text(json.dumps({
        "stage": 17, "run_id": run_id, "status": "BLOCKED", "stage18_authorized": False,
    }), encoding="utf-8")


def _manual_inputs(root: Path, *, file_type: str = "csv") -> Path:
    input_dir = root / "data/manual/stage17/hk"
    input_dir.mkdir(parents=True)
    frame = pd.DataFrame({
        "symbol": ["09669.HK", "09669.HK"],
        "date": ["2023-04-13", "2026-08-24"],
        "open": [10.0, 11.0], "high": [10.5, 11.5], "low": [9.5, 10.5],
        "close": [10.2, 11.2], "volume": [100, 200], "amount": [1000, 2200],
    })
    for adjust in ("raw", "qfq", "hfq"):
        source = input_dir / f"09669.HK.{adjust}.{file_type}"
        if file_type == "csv":
            frame.to_csv(source, index=False)
        else:
            frame.to_parquet(source, index=False)
        metadata = {
            "symbol": "09669.HK", "provider": "manual_external",
            "source": "licensed-test-export", "adjust_type": adjust,
            "acquired_at": "2026-08-25T00:00:00+00:00", "sha256": _hash(source),
            "adjustment_basis": "unadjusted_provider_native" if adjust == "raw" else "provider_native",
            "provider_adjust_semantics": f"test definition for {adjust}",
            "field_definition": "HKD OHLC, shares volume, HKEX trading dates",
        }
        (input_dir / f"09669.HK.{adjust}.metadata.json").write_text(
            json.dumps(metadata), encoding="utf-8",
        )
    return input_dir


@pytest.mark.parametrize("file_type", ["csv", "parquet"])
def test_manual_provider_accepts_strict_csv_and_parquet(tmp_path: Path, file_type: str) -> None:
    input_dir = _manual_inputs(tmp_path, file_type=file_type)
    call = HkManualProvider(input_dir).fetch_daily("09669.HK", "qfq")
    assert call.status == "success"
    assert list(call.dataframe.columns) == [
        "symbol", "date", "open", "high", "low", "close", "volume", "amount",
    ]
    assert call.source_sha256 == call.metadata["sha256"]


def test_manual_provider_fails_closed_for_missing_file_and_hash_mismatch(tmp_path: Path) -> None:
    provider = HkManualProvider(tmp_path)
    assert provider.fetch_daily("09669.HK", "qfq").error_type == "source_file_missing"
    input_dir = _manual_inputs(tmp_path)
    metadata_path = input_dir / "09669.HK.qfq.metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["sha256"] = "0" * 64
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    call = HkManualProvider(input_dir).fetch_daily("09669.HK", "qfq")
    assert call.status == "failed"
    assert call.error_type == "source_hash_mismatch"


def test_calculated_adjustment_requires_complete_hash_evidence(tmp_path: Path) -> None:
    input_dir = _manual_inputs(tmp_path)
    metadata_path = input_dir / "09669.HK.qfq.metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["adjustment_basis"] = "calculated_from_corporate_actions"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    call = HkManualProvider(input_dir).fetch_daily("09669.HK", "qfq")
    assert call.error_type == "adjustment_evidence_missing"


def test_adjustment_calculation_requires_exact_evidenced_factors() -> None:
    raw = pd.DataFrame({
        "symbol": ["09669.HK", "09669.HK"], "date": ["2023-04-13", "2023-04-14"],
        "open": [10, 11], "high": [12, 13], "low": [9, 10], "close": [11, 12],
        "volume": [100, 200],
    })
    factors = pd.DataFrame({
        "symbol": ["09669.HK", "09669.HK"], "date": ["2023-04-13", "2023-04-14"],
        "price_factor": [0.5, 0.5], "volume_factor": [2.0, 2.0],
        "evidence_id": ["event-1", "event-1"], "source": ["licensed", "licensed"],
    })
    actions = pd.DataFrame({
        "evidence_id": ["event-1"], "event_type": ["split"], "source": ["licensed"],
        "source_sha256": ["a" * 64],
    })
    result = apply_hk_adjustment(raw, factors, actions, symbol="09669.HK", adjust="qfq")
    assert result.open.tolist() == [5.0, 5.5]
    assert result.volume.tolist() == [200.0, 400.0]
    assert result.adjustment_type.tolist() == ["qfq", "qfq"]
    with pytest.raises(ValueError, match="exactly every raw trading date"):
        apply_hk_adjustment(
            raw, factors.iloc[:1], actions, symbol="09669.HK", adjust="qfq",
        )


@pytest.mark.parametrize("mode", ["validate_only", "dry_run"])
def test_nonformal_modes_write_nothing(tmp_path: Path, mode: str) -> None:
    evidence_run_id = str(uuid.uuid4())
    _evidence(tmp_path, evidence_run_id)
    input_dir = _manual_inputs(tmp_path)
    flags = {"validate_only": False, "dry_run": False}
    flags[mode] = True
    result = run_manual_validation(
        evidence_run_id=evidence_run_id, input_dir=input_dir,
        as_of_date=date(2026, 8, 24), root=tmp_path, **flags,
    )
    assert result["network_calls"] == 0
    assert result["outputs_written"] is False
    assert not (tmp_path / "reports/stage17_hk_manual_validation").exists()


def test_formal_pass_is_closed_world_but_does_not_advance_stage(tmp_path: Path) -> None:
    evidence_run_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    _evidence(tmp_path, evidence_run_id)
    input_dir = _manual_inputs(tmp_path)
    result = run_manual_validation(
        evidence_run_id=evidence_run_id, input_dir=input_dir,
        as_of_date=date(2026, 8, 24), run_id=run_id, root=tmp_path,
    )
    assert result["validation_status"] == "PASS"
    assert result["quality_pass_count"] == 3
    assert result["stage17_formal_status"] == "BLOCKED"
    assert result["provider_registry_built"] is False
    assert result["stage18_authorized"] is False
    report_dir = tmp_path / "reports/stage17_hk_manual_validation" / run_id
    manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["raw_files"]) == 12
    assert all(_hash(tmp_path / row["path"]) == row["sha256"] for row in manifest["raw_files"])
    assert all(_hash(tmp_path / row["path"]) == row["sha256"] for row in manifest["outputs"])
    assert not list(tmp_path.rglob("*.tmp"))


def test_formal_missing_inputs_records_blocked_without_fake_raw(tmp_path: Path) -> None:
    evidence_run_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    _evidence(tmp_path, evidence_run_id)
    input_dir = tmp_path / "data/manual/stage17/hk"
    result = run_manual_validation(
        evidence_run_id=evidence_run_id, input_dir=input_dir,
        as_of_date=date(2026, 8, 24), run_id=run_id, root=tmp_path,
    )
    assert result["validation_status"] == "BLOCKED"
    report_dir = tmp_path / "reports/stage17_hk_manual_validation" / run_id
    manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["quality_pass_count"] == 0
    assert manifest["raw_files"] == []
    assert {row["error_type"] for row in manifest["datasets"]} == {"source_file_missing"}
    assert not list(tmp_path.rglob("*.tmp"))


def test_formal_run_refuses_run_id_reuse(tmp_path: Path) -> None:
    evidence_run_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    _evidence(tmp_path, evidence_run_id)
    input_dir = _manual_inputs(tmp_path)
    kwargs = {
        "evidence_run_id": evidence_run_id, "input_dir": input_dir,
        "as_of_date": date(2026, 8, 24), "run_id": run_id, "root": tmp_path,
    }
    run_manual_validation(**kwargs)
    with pytest.raises(FileExistsError, match="already exists"):
        run_manual_validation(**kwargs)
