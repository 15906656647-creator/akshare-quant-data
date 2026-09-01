from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from akshare_data_test.stage17_hk_audit import (
    ADJUSTMENTS,
    HK_SYMBOLS,
    run_hk_ohlc_audit,
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(root: Path, formal_run_id: str) -> list[Path]:
    raw_files: list[dict[str, object]] = []
    datasets: list[dict[str, object]] = []
    paths: list[Path] = []
    for symbol in HK_SYMBOLS:
        for adjust in ADJUSTMENTS:
            directory = (
                root / "data" / "raw" / "stage17" / "equity_daily"
                / f"run_id={formal_run_id}" / "market=HK" / f"symbol={symbol}"
                / f"adjust={adjust}" / "source=sina"
            )
            directory.mkdir(parents=True)
            data_path = directory / "data.parquet"
            metadata_path = directory / "metadata.json"
            pd.DataFrame({
                "date": ["2026-08-20", "2026-08-21"],
                "open": [10.0, 10.0], "high": [10.5, 9.5],
                "low": [9.5, 9.0], "close": [10.2, 10.1],
                "volume": [100.0, 200.0], "amount": [1000.0, 2000.0],
            }).to_parquet(data_path, index=False)
            metadata_path.write_text(
                json.dumps({"source": "sina", "interface": "stock_hk_daily"}),
                encoding="utf-8",
            )
            data_rel = data_path.relative_to(root).as_posix()
            metadata_rel = metadata_path.relative_to(root).as_posix()
            data_hash = _hash(data_path)
            metadata_hash = _hash(metadata_path)
            dataset_id = f"daily:{symbol}:{adjust}:candidate:sina"
            datasets.append({
                "dataset_id": dataset_id, "kind": "equity_daily_candidate",
                "symbol": symbol, "market": "HK", "adjust": adjust,
                "status": "success", "quality_status": "FAIL", "source": "sina",
                "interface": "stock_hk_daily", "data_path": data_rel,
                "metadata_path": metadata_rel, "data_sha256": data_hash,
                "metadata_sha256": metadata_hash,
            })
            for role, path, relative, digest in (
                ("data", data_path, data_rel, data_hash),
                ("metadata", metadata_path, metadata_rel, metadata_hash),
            ):
                raw_files.append({
                    "dataset_id": dataset_id, "role": role, "path": relative,
                    "size_bytes": path.stat().st_size, "sha256": digest,
                })
                paths.append(path)
    report_dir = root / "reports" / "stage17" / formal_run_id
    report_dir.mkdir(parents=True)
    (report_dir / "stage17_manifest.json").write_text(
        json.dumps({
            "stage": 17, "run_id": formal_run_id, "as_of_date": "2026-08-24",
            "status": "BLOCKED", "raw_files": raw_files, "datasets": datasets,
        }), encoding="utf-8",
    )
    (report_dir / "stage17_run.json").write_text(
        json.dumps({
            "stage": 17, "run_id": formal_run_id, "status": "BLOCKED",
            "stage18_authorized": False,
        }), encoding="utf-8",
    )
    return paths


def test_hk_audit_is_read_only_and_classifies_raw_propagation(tmp_path: Path) -> None:
    formal_run_id = str(uuid.uuid4())
    audit_run_id = str(uuid.uuid4())
    raw_paths = _fixture(tmp_path, formal_run_id)
    before = {path: _hash(path) for path in raw_paths}

    result = run_hk_ohlc_audit(
        formal_run_id=formal_run_id, audit_run_id=audit_run_id,
        as_of_date=date(2026, 8, 24), audit_date=date(2026, 8, 25), root=tmp_path,
    )

    assert result.status == "BLOCKED"
    assert result.dataset_count == 21
    assert result.error_rows == 21
    assert before == {path: _hash(path) for path in raw_paths}
    errors = pd.read_csv(result.report_dir / "hk_ohlc_error_analysis.csv")
    assert set(errors.adjust) == {"raw", "qfq", "hfq"}
    assert set(errors.loc[errors.adjust == "raw", "root_cause"]) == {
        "upstream_raw_ohlc_inconsistency"
    }
    assert set(errors.loc[errors.adjust != "raw", "root_cause"]) == {
        "upstream_raw_inconsistency_propagated_by_adjustment"
    }
    manifest = json.loads((result.report_dir / "audit_manifest.json").read_text())
    assert manifest["network_calls"] == 0
    assert manifest["raw_files_modified"] == 0
    assert manifest["stage18_authorized"] is False
    assert len(manifest["verified_inputs"]) == 42


def test_hk_audit_fails_closed_on_input_hash_mismatch(tmp_path: Path) -> None:
    formal_run_id = str(uuid.uuid4())
    raw_paths = _fixture(tmp_path, formal_run_id)
    raw_paths[0].write_bytes(raw_paths[0].read_bytes() + b"tamper")

    with pytest.raises(ValueError, match="hash mismatch"):
        run_hk_ohlc_audit(
            formal_run_id=formal_run_id, audit_run_id=str(uuid.uuid4()),
            as_of_date=date(2026, 8, 24), audit_date=date(2026, 8, 25), root=tmp_path,
        )


def test_hk_audit_refuses_stage18_authorization(tmp_path: Path) -> None:
    formal_run_id = str(uuid.uuid4())
    _fixture(tmp_path, formal_run_id)
    run_path = tmp_path / "reports" / "stage17" / formal_run_id / "stage17_run.json"
    run = json.loads(run_path.read_text())
    run["stage18_authorized"] = True
    run_path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(ValueError, match="Stage 18"):
        run_hk_ohlc_audit(
            formal_run_id=formal_run_id, audit_run_id=str(uuid.uuid4()),
            as_of_date=date(2026, 8, 24), audit_date=date(2026, 8, 25), root=tmp_path,
        )


def test_hk_audit_refuses_report_overwrite(tmp_path: Path) -> None:
    formal_run_id = str(uuid.uuid4())
    audit_run_id = str(uuid.uuid4())
    _fixture(tmp_path, formal_run_id)
    kwargs = {
        "formal_run_id": formal_run_id, "audit_run_id": audit_run_id,
        "as_of_date": date(2026, 8, 24), "audit_date": date(2026, 8, 25),
        "root": tmp_path,
    }
    run_hk_ohlc_audit(**kwargs)
    with pytest.raises(FileExistsError):
        run_hk_ohlc_audit(**kwargs)
