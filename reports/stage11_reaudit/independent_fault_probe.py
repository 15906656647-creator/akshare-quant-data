from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from akshare_data_test.assets import ETHUSDT_OKX_SPOT
from akshare_data_test.crypto_evidence import validate_raw_evidence, write_raw_evidence


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "stage11_reaudit" / "stage11_reaudit_independent_faults.json"
RUN_ID = "stage11-reaudit-fault"


def frame() -> pd.DataFrame:
    close = 1800 + np.arange(48, dtype=float)
    return pd.DataFrame({
        "raw_instrument": "ETH-USDT", "data_provider": "okx_public_api",
        "raw_exchange": "OKX", "instrument_type": "spot", "bar_interval": "1h",
        "confirmed": True, "trade_time": pd.date_range("2026-07-26T00:00:00Z", periods=48, freq="h"),
        "open": close, "high": close + 2, "low": close - 2, "close": close + 1,
        "volume": 10.0, "quote_volume": (close + 1) * 10,
    })


def make(path: Path) -> None:
    write_raw_evidence(path, run_id=RUN_ID, provider="okx_public_api",
                       endpoint="https://www.okx.com/api/v5/market/history-candles",
                       request_parameters={"instId": "ETH-USDT", "bar": "1H"}, response=frame(),
                       identity=ETHUSDT_OKX_SPOT, fetched_at=pd.Timestamp("2026-07-28T00:10:00Z"))


def main() -> int:
    results = []
    with tempfile.TemporaryDirectory(prefix="stage11-reaudit-fault-") as name:
        base = Path(name)
        scenarios = {
            "raw_manifest_omits_required_file": lambda p: _omit(p, "metadata.json"),
            "raw_manifest_duplicate_file_entry": _duplicate,
            "raw_manifest_unexpected_file_entry": _unexpected,
        }
        for case_id, mutate in scenarios.items():
            path = base / case_id
            make(path); mutate(path)
            observed = validate_raw_evidence(path, run_id=RUN_ID, expected=ETHUSDT_OKX_SPOT)
            blocked = observed["status"] == "BLOCKED"
            results.append({"case_id": case_id, "entry": "validate_raw_evidence production entry",
                            "expected": "BLOCKED", "actual_status": observed["status"],
                            "blocked": blocked, "blocking_reasons": observed["blocking_reasons"]})
    payload = {"results": results, "blocked": sum(x["blocked"] for x in results), "total": len(results)}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if all(x["blocked"] for x in results) else 1


def _manifest(path: Path) -> dict:
    return json.loads((path / "manifest.json").read_text(encoding="utf-8"))


def _save(path: Path, value: dict) -> None:
    (path / "manifest.json").write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _omit(path: Path, target: str) -> None:
    value = _manifest(path)
    value["evidence_files"] = [x for x in value["evidence_files"] if x["name"] != target]
    _save(path, value)


def _duplicate(path: Path) -> None:
    value = _manifest(path); value["evidence_files"].append(dict(value["evidence_files"][0])); _save(path, value)


def _unexpected(path: Path) -> None:
    value = _manifest(path); value["evidence_files"][0]["name"] = "../request.json"; _save(path, value)


if __name__ == "__main__":
    raise SystemExit(main())
