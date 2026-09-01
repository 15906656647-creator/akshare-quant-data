from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from akshare_data_test.adapters.hk_external import (
    ExternalHistoryCall,
    normalize_yahoo_chart,
    yahoo_hk_symbol,
)
from akshare_data_test.stage17_hk_audit import HK_SYMBOLS
from akshare_data_test.stage17_hk_external_validation import (
    build_provider_comparison,
    run_external_validation,
)


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_candidate(
    root: Path, *, run_id: str, provider: str, adjust: str,
    frame: pd.DataFrame,
) -> tuple[str, str]:
    path = (
        root / "data/raw/stage17/test_candidate" / f"run_id={run_id}"
        / "market=HK/symbol=09669.HK" / f"adjust={adjust}" / f"source={provider}"
        / "data.parquet"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return path.relative_to(root).as_posix(), _hash(path)


def _evidence(root: Path) -> tuple[str, str, str]:
    sina_run = str(uuid.uuid4())
    tencent_run = str(uuid.uuid4())
    eastmoney_run = str(uuid.uuid4())
    datasets: list[dict[str, object]] = []
    raw_files: list[dict[str, object]] = []
    for symbol in HK_SYMBOLS:
        directory = (
            root / "data/raw/stage17/equity_profile" / f"run_id={sina_run}"
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
        meta_rel = metadata_path.relative_to(root).as_posix()
        dataset_id = f"profile:{symbol}"
        datasets.append({
            "dataset_id": dataset_id, "kind": "equity_profile", "market": "HK",
            "symbol": symbol, "quality_status": "PASS", "listing_date": "2023-04-13",
            "data_path": data_rel, "metadata_path": meta_rel,
            "data_sha256": _hash(data_path), "metadata_sha256": _hash(metadata_path),
        })
        for role, path, relative in (
            ("data", data_path, data_rel), ("metadata", metadata_path, meta_rel),
        ):
            raw_files.append({
                "dataset_id": dataset_id, "role": role, "path": relative,
                "size_bytes": path.stat().st_size, "sha256": _hash(path),
            })
    valid = pd.DataFrame({
        "date": [date(2023, 4, 13), date(2026, 8, 24)],
        "open": [10.0, 11.0], "high": [10.5, 11.5], "low": [9.5, 10.5],
        "close": [10.2, 11.2], "volume": [100, 200],
    })
    invalid = valid.copy()
    invalid.loc[0, "high"] = 9.0
    for adjust in ("raw", "qfq", "hfq"):
        path, digest = _write_candidate(
            root, run_id=sina_run, provider="sina", adjust=adjust, frame=invalid,
        )
        datasets.append({
            "dataset_id": f"daily:09669.HK:{adjust}:candidate:sina",
            "kind": "equity_daily_candidate", "symbol": "09669.HK", "adjust": adjust,
            "source": "sina", "status": "success", "quality_status": "FAIL",
            "data_path": path, "data_sha256": digest, "error_message": "ohlc_logic_error",
        })
    formal_dir = root / "reports/stage17" / sina_run
    formal_dir.mkdir(parents=True)
    (formal_dir / "stage17_manifest.json").write_text(json.dumps({
        "stage": 17, "run_id": sina_run, "as_of_date": "2026-08-24",
        "status": "BLOCKED", "datasets": datasets, "raw_files": raw_files,
    }), encoding="utf-8")
    (formal_dir / "stage17_run.json").write_text(json.dumps({
        "stage": 17, "run_id": sina_run, "status": "BLOCKED", "stage18_authorized": False,
    }), encoding="utf-8")

    tencent_rows: list[dict[str, object]] = []
    path, digest = _write_candidate(
        root, run_id=tencent_run, provider="tencent", adjust="raw", frame=valid,
    )
    tencent_rows.append({
        "symbol": "09669.HK", "adjust": "raw", "provider": "tencent",
        "status": "PASS", "quality_status": "PASS", "data_path": path,
        "data_sha256": digest,
    })
    for adjust in ("qfq", "hfq"):
        tencent_rows.append({
            "symbol": "09669.HK", "adjust": adjust, "provider": "tencent",
            "status": "FAIL", "quality_status": "NOT_RUN", "data_path": "",
            "data_sha256": "", "error_type": "upstream_error", "error_message": "'日期'",
        })
    tencent_dir = root / "reports/stage17_hk_tencent_validation" / tencent_run
    tencent_dir.mkdir(parents=True)
    (tencent_dir / "manifest.json").write_text(json.dumps({
        "run_id": tencent_run, "datasets": tencent_rows,
    }), encoding="utf-8")

    eastmoney_rows = []
    for adjust in ("raw", "qfq", "hfq"):
        path, digest = _write_candidate(
            root, run_id=eastmoney_run, provider="eastmoney", adjust=adjust, frame=invalid,
        )
        eastmoney_rows.append({
            "symbol": "09669.HK", "adjust": adjust, "provider": "eastmoney",
            "status": "FAIL", "quality_status": "FAIL", "data_path": path,
            "data_sha256": digest, "quality_errors": "ohlc_logic_error",
        })
    eastmoney_dir = root / "reports/stage17_hk_eastmoney_validation" / eastmoney_run
    eastmoney_dir.mkdir(parents=True)
    (eastmoney_dir / "manifest.json").write_text(json.dumps({
        "run_id": eastmoney_run, "datasets": eastmoney_rows,
    }), encoding="utf-8")
    return sina_run, tencent_run, eastmoney_run


class _YahooPassing:
    def fetch_history(self, **_: object) -> ExternalHistoryCall:
        frame = pd.DataFrame({
            "date": [date(2023, 4, 13), date(2026, 8, 24)],
            "open": [10.0, 11.0], "high": [10.5, 11.5], "low": [9.5, 10.5],
            "close": [10.2, 11.2], "adj_close": [9.8, 11.2],
            "volume": [100, 200],
        })
        return ExternalHistoryCall(
            b'{"test":true}', frame, 1, "success", provider_symbol="9669.HK",
            response_url="https://example.invalid/chart", provider_timezone="Asia/Hong_Kong",
        )


class _YahooNever:
    def fetch_history(self, **_: object) -> ExternalHistoryCall:
        raise AssertionError("nonformal mode must not call the network adapter")


def test_yahoo_symbol_mapping_and_chart_normalization() -> None:
    assert yahoo_hk_symbol("09669.HK") == "9669.HK"
    payload = {"chart": {"error": None, "result": [{
        "meta": {"exchangeTimezoneName": "Asia/Hong_Kong"},
        "timestamp": [1681349400],
        "indicators": {
            "quote": [{"open": [10], "high": [11], "low": [9], "close": [10.5], "volume": [1]}],
            "adjclose": [{"adjclose": [10.25]}],
        },
    }]}}
    frame, provider_timezone = normalize_yahoo_chart(payload)
    assert provider_timezone == "Asia/Hong_Kong"
    assert list(frame.columns) == ["date", "open", "high", "low", "close", "adj_close", "volume"]
    assert frame.iloc[0].adj_close == 10.25


def test_comparison_verifies_hashes_and_finds_synchronized_anomaly(tmp_path: Path) -> None:
    sina, tencent, eastmoney = _evidence(tmp_path)
    rows, evidence = build_provider_comparison(
        root=tmp_path, sina_run_id=sina, tencent_run_id=tencent,
        eastmoney_run_id=eastmoney,
    )
    assert len(evidence) == 9
    assert any(row["provider"] == "tencent" and row["adjust"] == "qfq"
               and row["error_type"] == "upstream_error" for row in rows)
    assert any(row["provider"] == "sina" and row["trade_date"] == "2023-04-13"
               and "open_gt_high" in row["error_type"] for row in rows)
    assert any(row["provider"] == "eastmoney" and row["trade_date"] == "2023-04-13"
               for row in rows)


@pytest.mark.parametrize("mode", ["validate_only", "dry_run"])
def test_nonformal_modes_are_offline_and_write_nothing(tmp_path: Path, mode: str) -> None:
    sina, tencent, eastmoney = _evidence(tmp_path)
    flags = {"validate_only": False, "dry_run": False}
    flags[mode] = True
    result = run_external_validation(
        evidence_run_id=sina, tencent_run_id=tencent, eastmoney_run_id=eastmoney,
        as_of_date=date(2026, 8, 24), root=tmp_path, yahoo_adapter=_YahooNever(), **flags,
    )
    assert result["network_calls"] == 0
    assert result["outputs_written"] is False
    assert not (tmp_path / "reports/stage17_hk_external_validation").exists()


def test_formal_validation_keeps_adjusted_semantics_blocked_and_closes_manifest(
    tmp_path: Path,
) -> None:
    sina, tencent, eastmoney = _evidence(tmp_path)
    run_id = str(uuid.uuid4())
    result = run_external_validation(
        evidence_run_id=sina, tencent_run_id=tencent, eastmoney_run_id=eastmoney,
        as_of_date=date(2026, 8, 24), run_id=run_id, root=tmp_path,
        yahoo_adapter=_YahooPassing(),
    )
    assert result["validation_status"] == "BLOCKED"
    assert result["yahoo_raw_status"] == "PASS"
    assert result["qfq_status"] == result["hfq_status"] == "FAIL"
    assert result["provider_registry_built"] is False
    assert result["stage18_authorized"] is False
    report_dir = tmp_path / "reports/stage17_hk_external_validation" / run_id
    manifest = json.loads((report_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["raw_manifest_closed_world"] is True
    assert len(manifest["raw_files"]) == 4
    assert all(_hash(tmp_path / row["path"]) == row["sha256"] for row in manifest["raw_files"])
    assert all(_hash(tmp_path / row["path"]) == row["sha256"] for row in manifest["outputs"])
    yahoo = [row for row in manifest["external_provider_results"] if row["provider"] == "yahoo"]
    assert [row["status"] for row in yahoo] == ["PASS", "FAIL", "FAIL"]
    comparison = pd.read_csv(report_dir / "09669_provider_comparison.csv")
    assert set(comparison.provider) == {"sina", "tencent", "eastmoney", "yahoo"}
    assert set(comparison.loc[comparison.trade_date == "2023-04-13", "provider"]) == {
        "sina", "eastmoney",
    }
    assert not list(tmp_path.rglob("*.tmp"))


def test_formal_validation_refuses_run_id_reuse(tmp_path: Path) -> None:
    sina, tencent, eastmoney = _evidence(tmp_path)
    run_id = str(uuid.uuid4())
    kwargs = {
        "evidence_run_id": sina, "tencent_run_id": tencent,
        "eastmoney_run_id": eastmoney, "as_of_date": date(2026, 8, 24),
        "run_id": run_id, "root": tmp_path, "yahoo_adapter": _YahooPassing(),
    }
    run_external_validation(**kwargs)
    with pytest.raises(FileExistsError, match="already exists"):
        run_external_validation(**kwargs)
