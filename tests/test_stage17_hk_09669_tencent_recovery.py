from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from pathlib import Path
from urllib.error import URLError

import pandas as pd
import pytest

from akshare_data_test.adapters.hk_tencent_direct import (
    HkTencentDirectAdapter,
    TencentDirectBlock,
    TencentDirectHistoryCall,
)
from akshare_data_test.stage17_hk_09669_tencent_recovery import run_tencent_recovery
from akshare_data_test.stage17_hk_audit import HK_SYMBOLS


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(root: Path, run_id: str) -> None:
    datasets: list[dict[str, object]] = []
    raw_files: list[dict[str, object]] = []
    for symbol in HK_SYMBOLS:
        listing = "2023-04-13" if symbol == "09669.HK" else "2020-01-02"
        directory = (
            root / "data/raw/stage17/equity_profile" / f"run_id={run_id}"
            / "market=HK" / f"symbol={symbol}"
        )
        directory.mkdir(parents=True)
        data_path = directory / "data.parquet"
        metadata_path = directory / "metadata.json"
        pd.DataFrame({"证券代码": [symbol], "上市日期": [listing]}).to_parquet(data_path, index=False)
        metadata_path.write_text(json.dumps({"symbol": symbol}), encoding="utf-8")
        data_rel = data_path.relative_to(root).as_posix()
        metadata_rel = metadata_path.relative_to(root).as_posix()
        dataset_id = f"profile:{symbol}"
        datasets.append({
            "dataset_id": dataset_id, "kind": "equity_profile", "market": "HK",
            "symbol": symbol, "quality_status": "PASS", "listing_date": listing,
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


class _Response:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def _payload(key: str = "day", identity: str = "hk09669") -> bytes:
    value = {"data": {identity: {key: [["2023-04-13", "1", "1.1", "1.2", "0.9", "10"]]}}}
    return f"var x={json.dumps(value)};".encode()


def test_adjusted_response_prefers_documented_key_and_accepts_day_fallback() -> None:
    documented = HkTencentDirectAdapter(opener=lambda *_args, **_kwargs: _Response(_payload("qfqday")))
    block = documented._fetch_block(symbol="09669.HK", year=2023, adjust="qfq")
    assert block.status == "success"
    assert block.used_key == "qfqday"
    assert block.field_fallback is False
    fallback = HkTencentDirectAdapter(opener=lambda *_args, **_kwargs: _Response(_payload("day")))
    block = fallback._fetch_block(symbol="09669.HK", year=2023, adjust="hfq")
    assert block.status == "success"
    assert block.requested_key == "hfqday"
    assert block.used_key == "day"
    assert block.field_fallback is True


def test_direct_adapter_accepts_other_hk_symbol_with_strict_identity() -> None:
    payload = _payload("day", identity="hk08462")
    adapter = HkTencentDirectAdapter(opener=lambda *_args, **_kwargs: _Response(payload))
    block = adapter._fetch_block(symbol="08462.HK", year=2017, adjust="qfq")
    assert block.status == "success"
    assert block.used_key == "day"
    assert block.field_fallback is True

@pytest.mark.parametrize(
    "payload,error",
    [(_payload(identity="hk02180"), "identity mismatch"), (b"var x={\"data\":{\"hk09669\":{}}};", "missing qfqday")],
)
def test_response_identity_and_schema_fail_closed(payload: bytes, error: str) -> None:
    adapter = HkTencentDirectAdapter(opener=lambda *_args, **_kwargs: _Response(payload))
    block = adapter._fetch_block(symbol="09669.HK", year=2023, adjust="qfq")
    assert block.status == "failed"
    assert block.error_type == "response_error"
    assert error in block.error_message


def test_connection_error_retries_with_bounded_exponential_backoff() -> None:
    calls = 0
    delays: list[float] = []

    def opener(*_args: object, **_kwargs: object) -> _Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise URLError("temporary")
        return _Response(_payload("day"))

    adapter = HkTencentDirectAdapter(
        opener=opener, sleeper=delays.append, retry_delay_seconds=1,
        max_retry_delay_seconds=2,
    )
    block = adapter._fetch_block(symbol="09669.HK", year=2023, adjust="qfq")
    assert block.status == "success"
    assert block.attempt_count == 3
    assert delays == [1, 2]


def _candidate_frame() -> pd.DataFrame:
    all_dates = pd.date_range("2023-04-13", "2026-08-24", freq="D")
    selected = [all_dates[0], *all_dates[1:-1][:827], all_dates[-1]]
    return pd.DataFrame({
        "date": [timestamp.date() for timestamp in selected],
        "open": 10.0, "close": 10.2, "high": 10.5, "low": 9.5, "volume": 100,
    })


def _block(adjust: str, year: int, frame: pd.DataFrame) -> TencentDirectBlock:
    payload = _payload("day")
    return TencentDirectBlock(
        year=year, adjust=adjust, request_url=f"https://example.test/{year}",
        request_params={"param": str(year)}, requested_key="day" if adjust == "raw" else f"{adjust}day",
        used_key="day", field_fallback=adjust != "raw", requested_at="2026-08-24T00:00:00+00:00",
        completed_at="2026-08-24T00:00:01+00:00", attempt_count=1, http_status=200,
        raw_response=payload, source_frame=frame.iloc[:2].copy(), status="success",
    )


class _PassingAdapter:
    def fetch_history(self, *, adjust: str, **_: object) -> TencentDirectHistoryCall:
        candidate = _candidate_frame()
        source = pd.concat([candidate, candidate.iloc[:236]], ignore_index=True)
        return TencentDirectHistoryCall(
            source_frame=source, dataframe=candidate,
            blocks=(_block(adjust, 2023, candidate), _block(adjust, 2025, candidate)),
            status="success", duplicate_rows_removed=236 if adjust != "raw" else 0,
        )


class _NeverAdapter:
    def fetch_history(self, **_: object) -> TencentDirectHistoryCall:
        raise AssertionError("nonformal modes must not call the adapter")


@pytest.mark.parametrize("mode", ["validate_only", "dry_run"])
def test_nonformal_modes_do_not_call_network_or_write(tmp_path: Path, mode: str) -> None:
    evidence_run_id = str(uuid.uuid4())
    _evidence(tmp_path, evidence_run_id)
    flags = {"validate_only": False, "dry_run": False}
    flags[mode] = True
    result = run_tencent_recovery(
        evidence_run_id=evidence_run_id, as_of_date=date(2026, 8, 24),
        root=tmp_path, adapter=_NeverAdapter(), **flags,
    )
    assert result["network_calls"] == 0
    assert result["outputs_written"] is False
    assert not (tmp_path / "reports/stage17_hk_09669_tencent_recovery").exists()


def test_formal_fake_recovery_is_closed_world_and_does_not_advance_stage(tmp_path: Path) -> None:
    evidence_run_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    _evidence(tmp_path, evidence_run_id)
    result = run_tencent_recovery(
        evidence_run_id=evidence_run_id, as_of_date=date(2026, 8, 24),
        run_id=run_id, root=tmp_path, adapter=_PassingAdapter(),
    )
    assert result["validation_status"] == "PASS"
    assert result["quality_pass_count"] == 3
    assert result["qfq_hfq_identical"] is True
    assert result["stage17_formal_status"] == "BLOCKED"
    assert result["stage18_authorized"] is False
    assert result["provider_registry_built"] is False
    report_dir = tmp_path / "reports/stage17_hk_09669_tencent_recovery" / run_id
    manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["raw_manifest_closed_world"] is True
    assert manifest["candidate_hk_coverage_after_success"] == "21/21"
    assert len(manifest["raw_files"]) == 18
    assert all(_hash(tmp_path / row["path"]) == row["sha256"] for row in manifest["raw_files"])
    assert not list(tmp_path.rglob("*.tmp"))


def test_formal_recovery_refuses_run_id_reuse(tmp_path: Path) -> None:
    evidence_run_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    _evidence(tmp_path, evidence_run_id)
    kwargs = {
        "evidence_run_id": evidence_run_id, "as_of_date": date(2026, 8, 24),
        "run_id": run_id, "root": tmp_path, "adapter": _PassingAdapter(),
    }
    run_tencent_recovery(**kwargs)
    with pytest.raises(FileExistsError, match="already exists"):
        run_tencent_recovery(**kwargs)
