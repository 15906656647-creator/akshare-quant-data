from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from akshare_data_test.adapters.hk_tencent_adapter import (
    HkTencentAdapter,
    TencentHistoryCall,
    normalize_tencent_history,
    tencent_year_blocks,
)
from akshare_data_test.stage17_hk_audit import HK_SYMBOLS
from akshare_data_test.stage17_hk_tencent_validation import run_tencent_validation


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(root: Path, run_id: str) -> None:
    datasets = []
    raw_files = []
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


class _FakeAk:
    __version__ = "test"

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def stock_zh_ah_daily(self, **kwargs: str) -> pd.DataFrame:
        self.calls.append(kwargs)
        year = int(kwargs["start_year"])
        return pd.DataFrame({
            "日期": [f"{year}-01-03", f"{year + 1}-01-03"],
            "开盘": [10.0, 11.0], "收盘": [10.2, 11.2],
            "最高": [10.5, 11.5], "最低": [9.5, 10.5], "成交量": [100, 200],
        })


class _NeverAdapter:
    def fetch_history(self, **_: object) -> TencentHistoryCall:
        raise AssertionError("validate-only/dry-run must not call the network adapter")


class _PassingAdapter:
    def fetch_history(
        self, *, symbol: str, listing_date: date, as_of_date: date, adjust: str,
    ) -> TencentHistoryCall:
        frame = pd.DataFrame({
            "date": [listing_date, as_of_date], "open": [10.0, 11.0],
            "high": [10.5, 11.5], "low": [9.5, 10.5], "close": [10.2, 11.2],
            "volume": [100, 200],
        })
        return TencentHistoryCall(
            source_frame=frame.copy(), dataframe=frame, attempt_count=1,
            status="success", requested_blocks=(listing_date.year,),
        )


def test_tencent_year_blocks_are_non_overlapping_two_year_windows() -> None:
    assert tencent_year_blocks(date(2017, 5, 26), date(2026, 8, 24)) == (
        2017, 2019, 2021, 2023, 2025,
    )


def test_tencent_adapter_maps_symbol_adjust_and_normalizes() -> None:
    fake = _FakeAk()
    adapter = HkTencentAdapter(ak_module=fake, sleeper=lambda _: None)
    result = adapter.fetch_history(
        symbol="02180.HK", listing_date=date(2019, 7, 10),
        as_of_date=date(2022, 8, 24), adjust="qfq",
    )
    assert result.status == "success"
    assert result.requested_blocks == (2019, 2021)
    assert list(result.dataframe.columns) == ["date", "open", "close", "high", "low", "volume"]
    assert [call["symbol"] for call in fake.calls] == ["02180", "02180"]
    assert [call["adjust"] for call in fake.calls] == ["qfq", "qfq"]
    assert [call["end_year"] for call in fake.calls] == ["2020", "2022"]


def test_normalizer_only_removes_identical_duplicate_dates() -> None:
    frame = pd.DataFrame({
        "date": ["2020-01-02", "2020-01-02"], "open": [1.0, 1.0],
        "close": [1.1, 1.1], "high": [1.2, 1.2], "low": [0.9, 0.9],
        "volume": [10, 10],
    })
    normalized, removed = normalize_tencent_history(
        frame, start_date=date(2020, 1, 1), as_of_date=date(2020, 12, 31)
    )
    assert len(normalized) == 1
    assert removed == 1
    conflict = frame.copy()
    conflict.loc[1, "close"] = 1.15
    with pytest.raises(ValueError, match="conflicting duplicate"):
        normalize_tencent_history(
            conflict, start_date=date(2020, 1, 1), as_of_date=date(2020, 12, 31)
        )


@pytest.mark.parametrize("mode", ["validate_only", "dry_run"])
def test_nonformal_modes_do_not_call_adapter_or_write_outputs(tmp_path: Path, mode: str) -> None:
    evidence_run_id = str(uuid.uuid4())
    _evidence(tmp_path, evidence_run_id)
    kwargs = {"validate_only": False, "dry_run": False}
    kwargs[mode] = True
    result = run_tencent_validation(
        evidence_run_id=evidence_run_id, as_of_date=date(2026, 8, 24),
        root=tmp_path, adapter=_NeverAdapter(), **kwargs,
    )
    assert result["network_calls"] == 0
    assert result["outputs_written"] is False
    assert not (tmp_path / "reports/stage17_hk_tencent_validation").exists()


def test_formal_fake_validation_writes_closed_world_without_authorizing_stage18(
    tmp_path: Path,
) -> None:
    evidence_run_id = str(uuid.uuid4())
    validation_run_id = str(uuid.uuid4())
    _evidence(tmp_path, evidence_run_id)
    result = run_tencent_validation(
        evidence_run_id=evidence_run_id, as_of_date=date(2026, 8, 24),
        run_id=validation_run_id, root=tmp_path, adapter=_PassingAdapter(),
    )
    assert result["validation_status"] == "PASS"
    assert result["quality_pass_count"] == 21
    assert result["stage17_formal_status"] == "BLOCKED"
    assert result["stage18_authorized"] is False
    report_dir = tmp_path / "reports/stage17_hk_tencent_validation" / validation_run_id
    manifest = json.loads((report_dir / "manifest.json").read_text())
    assert manifest["raw_manifest_closed_world"] is True
    assert len(manifest["raw_files"]) == 84
    assert all(_hash(tmp_path / row["path"]) == row["sha256"] for row in manifest["raw_files"])
    assert not list(tmp_path.rglob("*.tmp"))
    assert not list((tmp_path / "reports/stage17_hk_tencent_validation").glob(".*"))


def test_formal_validation_refuses_run_id_reuse(tmp_path: Path) -> None:
    evidence_run_id = str(uuid.uuid4())
    validation_run_id = str(uuid.uuid4())
    _evidence(tmp_path, evidence_run_id)
    kwargs = {
        "evidence_run_id": evidence_run_id, "as_of_date": date(2026, 8, 24),
        "run_id": validation_run_id, "root": tmp_path, "adapter": _PassingAdapter(),
    }
    run_tencent_validation(**kwargs)
    with pytest.raises(FileExistsError, match="already exists"):
        run_tencent_validation(**kwargs)
