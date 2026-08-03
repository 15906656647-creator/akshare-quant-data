from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from akshare_data_test.adapters.crypto_exchange import OkxPublicKlineAdapter
from akshare_data_test.assets import ETHUSDT_OKX_SPOT
from akshare_data_test.crypto_evidence import write_raw_evidence
from akshare_data_test.stage11_build import analyze_stage11


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "stage11_reaudit" / "stage11_reaudit_live.json"
RUN_ID = "stage11-independent-reaudit-20260727"
START = pd.Timestamp("2026-06-18T00:00:00Z")
END = pd.Timestamp("2026-07-28T00:00:00Z")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    adapter = OkxPublicKlineAdapter()
    raw = adapter.fetch(
        symbol="ETHUSDT", interval="1h", start_time=START.to_pydatetime(),
        end_time=END.to_pydatetime(), limit=100, timeout=30,
    )
    times = pd.to_datetime(raw["trade_time"], utc=True)
    numeric = raw[["open", "high", "low", "close", "volume", "quote_volume"]].apply(pd.to_numeric, errors="raise")
    independent = {
        "row_count": len(raw),
        "first_utc": times.min().isoformat(), "last_utc": times.max().isoformat(),
        "unique_timestamps": int(times.nunique()),
        "hourly_deltas_only": bool(times.sort_values().diff().dropna().eq(pd.Timedelta(hours=1)).all()),
        "all_utc": str(times.dt.tz) == "UTC",
        "weekend_rows": int((times.dt.dayofweek >= 5).sum()),
        "hours_present": sorted(times.dt.hour.unique().astype(int).tolist()),
        "ohlc_reasonable": bool(((numeric.high >= numeric[["open", "close", "low"]].max(axis=1)) &
                                  (numeric.low <= numeric[["open", "close", "high"]].min(axis=1))).all()),
        "volume_non_negative": bool((numeric[["volume", "quote_volume"]] >= 0).all().all()),
        "confirmed": bool(raw["confirmed"].all()),
        "identity": {name: sorted(raw[name].astype(str).unique().tolist()) for name in
                     ("raw_instrument", "data_provider", "raw_exchange", "instrument_type", "bar_interval")},
    }
    with tempfile.TemporaryDirectory(prefix="stage11-reaudit-") as temp_name:
        work = Path(temp_name)
        (work / "config").mkdir(); (work / "sql").mkdir()
        shutil.copy2(ROOT / "config/stage11.yml", work / "config/stage11.yml")
        shutil.copy2(ROOT / "sql/stage11_schema.sql", work / "sql/stage11_schema.sql")
        evidence = work / "raw" / f"run_id={RUN_ID}"
        write_raw_evidence(
            evidence, run_id=RUN_ID, provider="okx_public_api", endpoint=adapter.endpoint,
            request_parameters={"instId": "ETH-USDT", "bar": "1H", "start": START.isoformat(), "end": END.isoformat()},
            response=raw, identity=ETHUSDT_OKX_SPOT, fetched_at=END + pd.Timedelta(minutes=10),
        )
        db = work / "database" / "stage11.duckdb"
        kwargs = dict(root=work, as_of_date=pd.Timestamp("2026-07-27"), input_frame=raw,
                      interval="1h", source="okx_public_api", config_path=work / "config/stage11.yml",
                      output_database=db, run_id=RUN_ID, raw_evidence_dir=evidence)
        first, first_code = analyze_stage11(**kwargs)
        stable_paths = [*evidence.iterdir(), work / "reports/stage11_crypto_price.csv", work / "reports/stage11_crypto_price.json"]
        first_hashes = {str(p.relative_to(work)): sha(p) for p in stable_paths}
        second, second_code = analyze_stage11(**kwargs)
        second_hashes = {str(p.relative_to(work)): sha(p) for p in stable_paths}
        command = [sys.executable, str(ROOT / "run_pipeline.py"), "validate-crypto", "--as-of-date", "2026-07-27",
                   "--config", str(work / "config/stage11.yml"), "--input-csv", str(work / "reports/stage11_crypto_price.csv"),
                   "--input-json", str(work / "reports/stage11_crypto_price.json"), "--raw-evidence-dir", str(evidence),
                   "--reports-dir", str(work / "reports"), "--output-database", str(db), "--run-id", RUN_ID, "--validate-only"]
        before_validate = {str(p.relative_to(work)): (sha(p), p.stat().st_mtime_ns) for p in [db, *evidence.iterdir(), *(work / "reports").iterdir()]}
        cli = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        after_validate = {str(p.relative_to(work)): (sha(p), p.stat().st_mtime_ns) for p in [db, *evidence.iterdir(), *(work / "reports").iterdir()]}
        old_db = ROOT / "database" / "akshare_crypto_stage11.duckdb"
        old_before = sha(old_db)
        old_command = command.copy()
        old_command[old_command.index(str(db))] = str(old_db)
        old_cli = subprocess.run(old_command, cwd=ROOT, text=True, capture_output=True)
        old_after = sha(old_db)
        with duckdb.connect(str(db), read_only=True) as con:
            counts = {table: int(con.execute(f"SELECT count(*) FROM {table} WHERE run_id=?", [RUN_ID]).fetchone()[0]) for table in
                      ("raw.crypto_market_data", "clean.crypto_price_fact", "feature.crypto_indicator", "analysis.crypto_profile", "quality.stage11_quality_result", "audit.stage11_run")}
            close = con.execute("SELECT close FROM clean.crypto_price_fact WHERE run_id=? ORDER BY trade_time", [RUN_ID]).fetchnumpy()["close"]
            db_profile = con.execute("SELECT annualized_volatility FROM analysis.crypto_profile WHERE run_id=?", [RUN_ID]).fetchone()[0]
        independent_vol = float(pd.Series(close).pct_change().rolling(20, min_periods=20).std(ddof=1).iloc[-1] * np.sqrt(8760))
        result = {
            "source": "OKX public history-candles via production adapter", "endpoint": adapter.endpoint,
            "independent_data_checks": independent,
            "first_run": {"exit_code": first_code, "status": first["run_status"], "artifact_hash": first["artifact_hash"]},
            "second_run": {"exit_code": second_code, "status": second["run_status"], "artifact_hash": second["artifact_hash"]},
            "same_run_rerun_idempotent": first_code == second_code == 0 and first["artifact_hash"] == second["artifact_hash"] and first_hashes == second_hashes,
            "database_counts": counts,
            "independent_annualized_hourly_volatility": independent_vol,
            "database_annualized_hourly_volatility": float(db_profile),
            "volatility_absolute_error": abs(independent_vol - float(db_profile)),
            "validate_only": {"exit_code": cli.returncode, "stdout": cli.stdout, "stderr": cli.stderr,
                              "read_only": before_validate == after_validate},
            "old_database": {"exit_code": old_cli.returncode, "stdout": old_cli.stdout,
                             "stderr": old_cli.stderr, "rejected": old_cli.returncode != 0,
                             "unchanged": old_before == old_after, "sha256": old_after},
            "temporary_workspace_removed_after_run": True,
        }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
