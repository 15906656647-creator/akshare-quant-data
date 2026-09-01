from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from akshare_data_test.adapters.stock_market import MarketCall
from akshare_data_test.hk_eastmoney_validation import (
    normalize_eastmoney_history,
    run_eastmoney_validation,
)
from akshare_data_test.stage17_hk_audit import HK_SYMBOLS


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
        pd.DataFrame({"证券代码": [symbol], "上市日期": ["2020-01-02"]}).to_parquet(
            data_path, index=False
        )
        metadata_path.write_text(json.dumps({"symbol": symbol}), encoding="utf-8")
        data_rel = data_path.relative_to(root).as_posix()
        metadata_rel = metadata_path.relative_to(root).as_posix()
        dataset_id = f"profile:{symbol}"
        datasets.append({
            "dataset_id": dataset_id, "kind": "equity_profile", "market": "HK",
            "symbol": symbol, "quality_status": "PASS", "listing_date": "2020-01-02",
            "data_path": data_rel, "metadata_path": metadata_rel,
            "data_sha256": _hash(data_path), "metadata_sha256": _hash(metadata_path),
        })
        for role, path, relative in (
            ("data", data_path, data_rel), ("metadata", metadata_path, metadata_rel)
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
        "stage": 17, "run_id": run_id, "status": "BLOCKED",
        "stage18_authorized": False,
    }), encoding="utf-8")


class _PassingAdapter:
    def fetch_history(
        self, *, symbol: str, start_date: str, end_date: str, adjust: str,
    ) -> MarketCall:
        return MarketCall(pd.DataFrame({
            "日期": [date.fromisoformat("2020-01-02"), date.fromisoformat("2026-08-24")],
            "开盘": [10.0, 11.0], "最高": [10.5, 11.5],
            "最低": [9.5, 10.5], "收盘": [10.2, 11.2], "成交量": [100, 200],
            "成交额": [1000, 2000],
        }), 1, "success")


class _NeverAdapter:
    def fetch_history(self, **_: object) -> MarketCall:
        raise AssertionError("nonformal mode must not call adapter")


def test_normalizer_only_renames_and_selects_required_columns() -> None:
    source = pd.DataFrame({
        "日期": ["2020-01-03", "2020-01-02"], "开盘": [2, 1],
        "最高": [3, 2], "最低": [1, 0], "收盘": [2.5, 1.5],
        "成交量": [20, 10], "成交额": [50, 15],
    })
    result = normalize_eastmoney_history(source)
    assert list(result.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert result.date.tolist() == ["2020-01-03", "2020-01-02"]
    assert result.open.tolist() == [2, 1]


def test_normalizer_fails_closed_on_missing_schema() -> None:
    with pytest.raises(ValueError, match="missing required columns"):
        normalize_eastmoney_history(pd.DataFrame({"日期": ["2020-01-02"]}))


@pytest.mark.parametrize("mode", ["validate_only", "dry_run"])
def test_nonformal_modes_are_offline_and_write_nothing(tmp_path: Path, mode: str) -> None:
    evidence_run_id = str(uuid.uuid4())
    _evidence(tmp_path, evidence_run_id)
    flags = {"validate_only": False, "dry_run": False}
    flags[mode] = True
    result = run_eastmoney_validation(
        evidence_run_id=evidence_run_id, as_of_date=date(2026, 8, 24),
        root=tmp_path, adapter=_NeverAdapter(), **flags,
    )
    assert result["network_calls"] == 0
    assert result["outputs_written"] is False
    assert not (tmp_path / "reports/stage17_hk_eastmoney_validation").exists()


def test_formal_fake_run_is_closed_world_and_does_not_advance_stage(tmp_path: Path) -> None:
    evidence_run_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    _evidence(tmp_path, evidence_run_id)
    result = run_eastmoney_validation(
        evidence_run_id=evidence_run_id, as_of_date=date(2026, 8, 24),
        run_id=run_id, root=tmp_path, adapter=_PassingAdapter(),
    )
    assert result["validation_status"] == "PASS"
    assert result["quality_pass_count"] == 21
    assert result["stage17_formal_status"] == "BLOCKED"
    assert result["provider_registry_built"] is False
    assert result["stage18_authorized"] is False
    report_dir = tmp_path / "reports/stage17_hk_eastmoney_validation" / run_id
    manifest = json.loads((report_dir / "manifest.json").read_text())
    assert manifest["raw_manifest_closed_world"] is True
    assert len(manifest["raw_files"]) == 84
    assert all(_hash(tmp_path / row["path"]) == row["sha256"] for row in manifest["raw_files"])
    assert all(_hash(tmp_path / row["path"]) == row["sha256"] for row in manifest["outputs"])
    assert not list(tmp_path.rglob("*.tmp"))


def test_formal_run_refuses_run_id_reuse(tmp_path: Path) -> None:
    evidence_run_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    _evidence(tmp_path, evidence_run_id)
    kwargs = {
        "evidence_run_id": evidence_run_id, "as_of_date": date(2026, 8, 24),
        "run_id": run_id, "root": tmp_path, "adapter": _PassingAdapter(),
    }
    run_eastmoney_validation(**kwargs)
    with pytest.raises(FileExistsError, match="already exists"):
        run_eastmoney_validation(**kwargs)
