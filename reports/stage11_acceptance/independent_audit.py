"""Independent Stage 11 acceptance audit; does not reuse project indicator formulas."""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "stage11_acceptance"
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

RUN_ID = "stage11-ethusdt-20260727"
AS_OF = pd.Timestamp("2026-07-27")
DB_PATH = ROOT / "database" / "akshare_crypto_stage11.duckdb"
CSV_PATH = ROOT / "reports" / "stage11_crypto_price.csv"
JSON_PATH = ROOT / "reports" / "stage11_crypto_price.json"
RAW_DIR = ROOT / "data" / "raw" / "crypto_js_spot" / f"run_id={RUN_ID}"
CONFIG_PATH = ROOT / "config" / "stage11.yml"
SCHEMA_PATH = ROOT / "sql" / "stage11_schema.sql"

KEYS = ["symbol", "exchange", "market", "interval", "trade_time", "run_id"]
NUMERIC = ["open", "high", "low", "close", "volume", "quote_volume"]
COMPARE = KEYS + NUMERIC + ["source"]
TABLES = {
    "raw": "raw.crypto_market_data",
    "clean": "clean.crypto_price_fact",
    "indicators": "feature.crypto_indicator",
    "profile": "analysis.crypto_profile",
    "quality": "quality.stage11_quality_result",
    "audit": "audit.stage11_run",
}


def scalar(value: Any) -> Any:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (pd.Timestamp, datetime)):
        stamp = pd.Timestamp(value)
        stamp = stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")
        return stamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value.item() if hasattr(value, "item") else value


def decimal_value(value: Any) -> Decimal | None:
    value = scalar(value)
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame[COMPARE].copy()
    times = pd.to_datetime(out["trade_time"], errors="coerce", utc=True)
    out["trade_time"] = times.dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ").where(times.notna(), None)
    for column in NUMERIC:
        out[column] = out[column].map(decimal_value)
    for column in [c for c in COMPARE if c not in NUMERIC + ["trade_time"]]:
        out[column] = out[column].astype("string").where(out[column].notna(), None)
    return out.sort_values(KEYS, kind="mergesort", na_position="first").reset_index(drop=True)


def rounded_hash(frame: pd.DataFrame) -> str:
    rows = []
    quantum = Decimal("1e-12")
    for record in normalize_frame(frame).to_dict("records"):
        row = {}
        for key, value in record.items():
            if isinstance(value, Decimal):
                row[key] = str(value.quantize(quantum))
            else:
                row[key] = scalar(value)
        rows.append(row)
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compare_pair(name: str, left: pd.DataFrame, right: pd.DataFrame) -> list[dict[str, Any]]:
    a, b = normalize_frame(left), normalize_frame(right)
    rows: list[dict[str, Any]] = []
    key_a = set(tuple(row) for row in a[KEYS].itertuples(index=False, name=None))
    key_b = set(tuple(row) for row in b[KEYS].itertuples(index=False, name=None))
    merged = a.merge(b, on=KEYS, how="outer", suffixes=("_left", "_right"), indicator=True)
    for column in NUMERIC + ["source"]:
        mismatch = 0
        max_abs = Decimal(0)
        max_rel = Decimal(0)
        for _, row in merged.iterrows():
            if row["_merge"] != "both":
                mismatch += 1
                continue
            lv, rv = row[f"{column}_left"], row[f"{column}_right"]
            if column in NUMERIC:
                if lv is None or rv is None:
                    mismatch += int(lv != rv)
                    continue
                difference = abs(lv - rv)
                relative = difference / max(abs(lv), abs(rv), Decimal("1e-30"))
                max_abs, max_rel = max(max_abs, difference), max(max_rel, relative)
                if difference > Decimal("1e-12") and relative > Decimal("1e-12"):
                    mismatch += 1
            elif lv != rv:
                mismatch += 1
        rows.append({
            "comparison": name, "field": column, "left_rows": len(a), "right_rows": len(b),
            "key_set_equal": key_a == key_b, "mismatch_count": mismatch,
            "max_absolute_error": str(max_abs) if column in NUMERIC else "",
            "max_relative_error": str(max_rel) if column in NUMERIC else "",
            "tolerance": "1e-12", "left_sha256_rounded": rounded_hash(left),
            "right_sha256_rounded": rounded_hash(right),
            "status": "PASS" if len(a) == len(b) and key_a == key_b and mismatch == 0 else "FAIL",
        })
    return rows


def read_sources() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    csv = pd.read_csv(CSV_PATH, dtype={"symbol": "string", "run_id": "string"})
    raw_json = json.loads(JSON_PATH.read_text(encoding="utf-8"), parse_float=Decimal, parse_int=Decimal)
    js = pd.DataFrame(raw_json)
    with duckdb.connect(str(DB_PATH), read_only=True) as connection:
        db = connection.execute("SELECT * FROM clean.crypto_price_fact WHERE run_id=? ORDER BY trade_time", [RUN_ID]).fetchdf()
        tables = {key: connection.execute(f"SELECT * FROM {table} WHERE run_id=?", [RUN_ID]).fetchdf() for key, table in TABLES.items()}
    return csv, js, db, tables


def data_quality(frame: pd.DataFrame) -> dict[str, Any]:
    times = pd.to_datetime(frame["trade_time"], errors="coerce", utc=True)
    ordered = times.sort_values().reset_index(drop=True)
    differences = ordered.diff().dropna()
    numeric = frame[["open", "high", "low", "close", "volume", "quote_volume"]].apply(pd.to_numeric, errors="coerce")
    finite = np.isfinite(numeric.to_numpy(dtype=float))
    ohlc = (
        numeric["high"].ge(numeric[["open", "close", "low"]].max(axis=1))
        & numeric["low"].le(numeric[["open", "close", "high"]].min(axis=1))
        & numeric[["open", "high", "low", "close"]].gt(0).all(axis=1)
    )
    return {
        "row_count": len(frame), "min_timestamp": ordered.min().isoformat(),
        "max_timestamp": ordered.max().isoformat(), "unique_timestamps": int(times.nunique()),
        "missing_intervals": sum(int(d / pd.Timedelta(hours=1)) - 1 for d in differences if d > pd.Timedelta(hours=1)),
        "non_hour_differences": int(differences.ne(pd.Timedelta(hours=1)).sum()),
        "duplicated_timestamps": int(times.duplicated().sum()),
        "invalid_ohlc_count": int((~ohlc).sum()),
        "negative_volume_count": int(numeric[["volume", "quote_volume"]].lt(0).sum().sum()),
        "non_finite_numeric_count": int((~finite).sum()), "invalid_timestamp_count": int(times.isna().sum()),
        "provider_distribution": frame["source"].astype(str).value_counts().to_dict(),
        "instrument_distribution": frame["symbol"].astype(str).value_counts().to_dict(),
        "exchange_distribution": frame["exchange"].astype(str).value_counts().to_dict(),
        "market_distribution": frame["market"].astype(str).value_counts().to_dict(),
        "bar_interval_distribution": frame["interval"].astype(str).value_counts().to_dict(),
        "utc_day_counts": {stamp.isoformat(): int(count) for stamp, count in times.dt.floor("D").value_counts().sort_index().items()},
    }


def regression(values: np.ndarray) -> tuple[float, float]:
    x, y = np.arange(len(values), dtype=float), np.log(values.astype(float))
    slope, intercept = np.polyfit(x, y, 1)
    fitted = slope * x + intercept
    total = float(((y - y.mean()) ** 2).sum())
    residual = float(((y - fitted) ** 2).sum())
    return float(np.expm1(slope)), 1.0 if total == 0 else float(max(0.0, 1.0 - residual / total))


def independent_metrics(clean: pd.DataFrame, project: pd.DataFrame, profile: pd.DataFrame) -> list[dict[str, Any]]:
    frame = clean.sort_values("trade_time", kind="mergesort").reset_index(drop=True).copy()
    for column in ["open", "high", "low", "close"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    close = frame["close"]
    returns = close.pct_change()
    realized = returns.rolling(20, min_periods=20).std(ddof=1)
    annualized = realized * math.sqrt(8760)
    previous = close.shift(1)
    tr = pd.concat([(frame.high-frame.low), (frame.high-previous).abs(), (frame.low-previous).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14, min_periods=14).mean()
    middle = close.rolling(20, min_periods=20).mean()
    std = close.rolling(20, min_periods=20).std(ddof=0)
    upper, lower = middle + 2 * std, middle - 2 * std
    bandwidth = (upper - lower) / middle
    slopes = close.rolling(20, min_periods=20).apply(lambda x: regression(x)[0], raw=True)
    r2 = close.rolling(20, min_periods=20).apply(lambda x: regression(x)[1], raw=True)
    box_high = frame.high.shift(1).rolling(20, min_periods=20).max()
    box_low = frame.low.shift(1).rolling(20, min_periods=20).min()
    false_up = pd.Series(False, index=frame.index)
    false_down = pd.Series(False, index=frame.index)
    for index in range(len(frame) - 3):
        future = close.iloc[index+1:index+4]
        if close.iloc[index] > box_high.iloc[index] and future.le(box_high.iloc[index]).any():
            false_up.iloc[index] = True
        if close.iloc[index] < box_low.iloc[index] and future.ge(box_low.iloc[index]).any():
            false_down.iloc[index] = True
    independent = {
        "return_1bar": returns.iloc[-1], "realized_volatility": realized.iloc[-1],
        "annualized_volatility": annualized.iloc[-1], "true_range": tr.iloc[-1],
        "atr": atr.iloc[-1], "atr_ratio": atr.iloc[-1] / close.iloc[-1],
        "bollinger_middle": middle.iloc[-1], "bollinger_upper": upper.iloc[-1],
        "bollinger_lower": lower.iloc[-1], "bollinger_band_width": bandwidth.iloc[-1],
        "trend_slope": slopes.iloc[-1], "trend_r_squared": r2.iloc[-1],
        "box_high": box_high.iloc[-1], "box_low": box_low.iloc[-1],
        "box_width": box_high.iloc[-1] / box_low.iloc[-1] - 1,
        "false_breakout_count": int((false_up | false_down).loc[middle.notna()].sum()),
    }
    latest = project.sort_values("trade_time").iloc[-1]
    prof = profile.iloc[-1]
    rows = []
    for name, calculated in independent.items():
        project_value = prof[name] if name == "false_breakout_count" else latest[name]
        difference = abs(float(project_value) - float(calculated))
        relative = difference / max(abs(float(project_value)), abs(float(calculated)), 1e-30)
        rows.append({
            "metric": name, "project_value": project_value, "independent_value": calculated,
            "absolute_difference": difference, "relative_difference": relative,
            "tolerance": 1e-12, "status": "PASS" if difference <= 1e-12 or relative <= 1e-12 else "FAIL",
            "definition": {
                "realized_volatility": "rolling 20 return std ddof=1",
                "annualized_volatility": "realized_volatility * sqrt(8760)",
                "atr": "rolling 14 mean of true range",
                "bollinger_band_width": "(upper-lower)/middle; rolling 20 std ddof=0",
                "trend_slope": "expm1(OLS slope of log(close) over 20 bars)",
                "box_width": "prior 20 high / prior 20 low - 1",
                "false_breakout_count": "prior-20 box break then return inside within next 3 bars",
            }.get(name, "direct formula component"),
        })
    return rows


def quality_blocks(frame: pd.DataFrame) -> tuple[bool, str]:
    from akshare_data_test.quality.crypto_checks import run_stage11_quality_checks

    try:
        result = run_stage11_quality_checks(
            frame, run_id=RUN_ID, as_of_date=AS_OF, interval="1h", expected_symbol="ETHUSDT",
            checked_at=pd.Timestamp("2026-08-02T00:00:00Z"),
        )
        failures = result.loc[result["status"].eq("FAIL"), "check_name"].tolist()
        return bool(failures), ",".join(failures) if failures else "overall PASS"
    except Exception as exc:
        return True, f"exception:{type(exc).__name__}:{exc}"


def build_dry(frame: pd.DataFrame, source: str, root: Path) -> tuple[bool, str]:
    from akshare_data_test.stage11_build import analyze_stage11

    try:
        report, exit_code = analyze_stage11(
            root=root, as_of_date=AS_OF, input_frame=frame, interval="1h", source=source,
            config_path=CONFIG_PATH, output_database=root / "unused.duckdb",
            run_id="fault-run", dry_run=True,
        )
        return exit_code != 0, f"status={report['run_status']};exit={exit_code};blockers={report['blocking_reasons']}"
    except Exception as exc:
        return True, f"exception:{type(exc).__name__}:{exc}"


def fault_rows(clean: pd.DataFrame) -> list[dict[str, Any]]:
    from akshare_data_test.stage11_build import validate_stage11_inputs

    rows: list[dict[str, Any]] = []
    temp_root = Path(tempfile.mkdtemp(prefix="stage11-accept-fault-"))
    try:
        def add(fid: str, category: str, mutation: str, expected: str, blocked: bool, actual: str) -> None:
            rows.append({
                "id": fid, "category": category, "injected_fault": mutation,
                "expected_gate": expected, "actual_result": actual,
                "exit_code": 1 if blocked else 0, "blocked": blocked,
                "status": "PASS" if blocked else "FAIL",
            })

        tests: list[tuple[str, str, Any]] = []
        missing = clean.drop(index=100).reset_index(drop=True)
        tests.append(("A1", "delete middle bar", missing))
        duplicate = pd.concat([clean, clean.iloc[[100]]], ignore_index=True)
        tests.append(("A2", "duplicate one bar", duplicate))
        offset = clean.copy(); offset.loc[100, "trade_time"] = pd.Timestamp(offset.loc[100, "trade_time"]) + pd.Timedelta(minutes=30)
        tests.append(("A3", "offset timestamp 30 minutes", offset))
        swapped = clean.copy(); swapped.iloc[[100, 101]] = swapped.iloc[[101, 100]].to_numpy()
        tests.append(("A4", "swap adjacent input rows", swapped))
        earlier = pd.concat([clean.iloc[[0]].assign(trade_time=pd.Timestamp(clean.iloc[0].trade_time)-pd.Timedelta(hours=1)), clean], ignore_index=True)
        tests.append(("A5", "prepend bar outside configured 40-day range", earlier))
        for fid, mutation, frame in tests:
            blocked, actual = quality_blocks(frame)
            add(fid, "time", mutation, "BLOCKED", blocked, actual)

        raw = clean.drop(columns=[c for c in clean.columns if c not in {"trade_time", "open", "high", "low", "close", "volume", "quote_volume", "symbol", "exchange", "market", "source"}]).copy()
        mutations = []
        ethusd = raw.copy(); ethusd.loc[0, "symbol"] = "ETH-USD"; mutations.append(("B1", "input symbol ETH-USD", ethusd, "provided_csv"))
        swap = raw.copy(); swap.loc[0, "symbol"] = "ETH-USDT-SWAP"; swap.loc[0, "market"] = "swap"; mutations.append(("B2", "input derivative ETH-USDT-SWAP", swap, "provided_csv"))
        mutations.append(("B3", "source argument AKShare", raw, "AKShare"))
        mutations.append(("B4", "source argument Binance", raw, "binance_public_api"))
        no_symbol = raw.drop(columns=["symbol"]); mutations.append(("B5", "remove original symbol field", no_symbol, "provided_csv"))
        mixed = raw.copy(); mixed.loc[0, "exchange"] = "OTHER"; mutations.append(("B6", "mix another exchange", mixed, "provided_csv"))
        for fid, mutation, frame, source in mutations:
            blocked, actual = build_dry(frame, source, temp_root)
            add(fid, "identity_source", mutation, "BLOCKED", blocked, actual)

        ohlc_tests = []
        high = clean.copy(); high.loc[0, "high"] = high.loc[0, "close"] - 1; ohlc_tests.append(("C1", "high < close", high))
        low = clean.copy(); low.loc[0, "low"] = low.loc[0, "open"] + 1; ohlc_tests.append(("C2", "low > open", low))
        neg = clean.copy(); neg.loc[0, "volume"] = -1; ohlc_tests.append(("C3", "negative volume", neg))
        nan = clean.copy(); nan.loc[0, "close"] = np.nan; ohlc_tests.append(("C4", "NaN close", nan))
        inf = clean.copy(); inf.loc[0, "high"] = np.inf; ohlc_tests.append(("C5", "Infinity high", inf))
        text = clean.copy(); text["close"] = text["close"].astype(object); text.loc[0, "close"] = "invalid"; ohlc_tests.append(("C6", "string close", text))
        for fid, mutation, frame in ohlc_tests:
            blocked, actual = quality_blocks(frame)
            add(fid, "ohlcv", mutation, "BLOCKED", blocked, actual)

        dummy_csv = temp_root / "input.csv"
        clean.to_csv(dummy_csv, index=False)
        consistency_cases = [
            ("D1", "CSV delete row"), ("D2", "JSON modify close"),
            ("D3", "DuckDB modify provider"), ("D4", "timestamp timezone/hour changed"),
        ]
        for fid, mutation in consistency_cases:
            result = validate_stage11_inputs(config_path=CONFIG_PATH, input_csv=dummy_csv, output_database=temp_root / "tampered.duckdb")
            blocked = result["status"] != "READY"
            add(fid, "three_format", mutation, "BLOCKED", blocked, f"validate-only status={result['status']}; artifacts are not inputs")

        raw_cases = [
            ("E1", "Raw directory missing"), ("E2", "Raw response missing"),
            ("E3", "Raw response empty"), ("E4", "metadata row count mismatch"),
            ("E5", "schema hash mismatch"),
        ]
        for fid, mutation in raw_cases:
            result = validate_stage11_inputs(config_path=CONFIG_PATH, input_csv=None, output_database=temp_root / "raw-check.duckdb")
            blocked = result["status"] != "READY"
            add(fid, "raw_evidence", mutation, "BLOCKED", blocked, f"validate-only status={result['status']}; no Raw parameter/check")

        from akshare_data_test.fundamental_analysis import FundamentalAnalysisNotApplicable, require_equity_asset
        try:
            require_equity_asset("crypto")
            add("F1", "fundamental", "crypto helper", "not_applicable", False, "no exception")
        except FundamentalAnalysisNotApplicable as exc:
            add("F1", "fundamental", "crypto helper", "not_applicable", True, f"{exc.status}:{exc}")
        try:
            require_equity_asset("equity")
            rows.append({"id":"F2","category":"fundamental","injected_fault":"equity helper","expected_gate":"unchanged","actual_result":"accepted","exit_code":0,"blocked":False,"status":"PASS"})
        except Exception as exc:
            rows.append({"id":"F2","category":"fundamental","injected_fault":"equity helper","expected_gate":"unchanged","actual_result":str(exc),"exit_code":1,"blocked":True,"status":"FAIL"})
        from akshare_data_test import stage10_build
        signature = str(inspect.signature(stage10_build.analyze_stage10))
        guard_integrated = "asset_type" in signature
        rows.append({
            "id":"F3","category":"fundamental","injected_fault":"crypto through Stage 10 production entry",
            "expected_gate":"not_applicable before financial reads",
            "actual_result":f"signature={signature}; require_equity_asset not called by Stage10",
            "exit_code":0,"blocked":guard_integrated,"status":"PASS" if guard_integrated else "FAIL",
        })
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)
    return rows


def table_hash(frame: pd.DataFrame) -> str:
    copy = frame.copy()
    columns = sorted(copy.columns)
    copy = copy[columns].astype("string").fillna("<NULL>").sort_values(columns, kind="mergesort")
    return hashlib.sha256(copy.to_csv(index=False, lineterminator="\n").encode()).hexdigest()


def idempotency(tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    from akshare_data_test.storage.crypto_repository import read_stage11_run, write_stage11_run

    temp_root = Path(tempfile.mkdtemp(prefix="stage11-accept-idem-"))
    try:
        database = temp_root / "copy.duckdb"
        shutil.copy2(DB_PATH, database)
        frames = {key: value.copy() for key, value in tables.items()}
        before = read_stage11_run(database, RUN_ID)
        write_stage11_run(database, schema_path=SCHEMA_PATH, frames=frames, run_id=RUN_ID)
        first = read_stage11_run(database, RUN_ID)
        write_stage11_run(database, schema_path=SCHEMA_PATH, frames=frames, run_id=RUN_ID)
        second = read_stage11_run(database, RUN_ID)
        counts_stable = all(len(before[k]) == len(first[k]) == len(second[k]) for k in TABLES)
        hashes_stable = all(table_hash(first[k]) == table_hash(second[k]) for k in TABLES)
        duplicate_counts = {}
        with duckdb.connect(str(database), read_only=True) as connection:
            for key, table in TABLES.items():
                keys = {
                    "raw":["run_id","symbol","exchange","interval","trade_time"],
                    "clean":["run_id","symbol","exchange","interval","trade_time"],
                    "indicators":["run_id","symbol","exchange","interval","trade_time"],
                    "profile":["run_id","symbol","exchange","interval"],
                    "quality":["run_id","check_name"], "audit":["run_id"],
                }[key]
                group = ",".join(keys)
                duplicate_counts[key] = int(connection.execute(f"SELECT count(*) FROM (SELECT {group},count(*) n FROM {table} GROUP BY {group} HAVING n>1)").fetchone()[0])
        other_frames = {}
        for key, frame in frames.items():
            changed = frame.copy(); changed["run_id"] = "acceptance-other-run"; other_frames[key] = changed
        write_stage11_run(database, schema_path=SCHEMA_PATH, frames=other_frames, run_id="acceptance-other-run")
        write_stage11_run(database, schema_path=SCHEMA_PATH, frames=frames, run_id=RUN_ID)
        with duckdb.connect(str(database), read_only=True) as connection:
            other_preserved = all(connection.execute(f"SELECT count(*) FROM {table} WHERE run_id='acceptance-other-run'").fetchone()[0] == len(other_frames[key]) for key, table in TABLES.items())
        pre_failure = {k: table_hash(v) for k, v in read_stage11_run(database, RUN_ID).items()}
        broken = {k: v.copy() for k, v in frames.items()}; broken["raw"] = broken["raw"].drop(columns=["symbol"])
        failure_raised = False
        try:
            write_stage11_run(database, schema_path=SCHEMA_PATH, frames=broken, run_id=RUN_ID)
        except Exception:
            failure_raised = True
        post_failure = {k: table_hash(v) for k, v in read_stage11_run(database, RUN_ID).items()}
        return {
            "counts_before": {k:len(v) for k,v in before.items()},
            "counts_after_first": {k:len(v) for k,v in first.items()},
            "counts_after_second": {k:len(v) for k,v in second.items()},
            "counts_stable": counts_stable, "hashes_stable": hashes_stable,
            "duplicate_key_counts": duplicate_counts, "other_run_preserved": other_preserved,
            "failure_raised": failure_raised, "rollback_preserved": pre_failure == post_failure,
            "status": "PASS" if counts_stable and hashes_stable and not any(duplicate_counts.values()) and other_preserved and failure_raised and pre_failure == post_failure else "FAIL",
        }
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def akshare_raw() -> dict[str, Any]:
    parquet = RAW_DIR / "crypto_spot.parquet"
    metadata_path = RAW_DIR / "metadata.json"
    result: dict[str, Any] = {"directory_exists": RAW_DIR.is_dir(), "response_exists": parquet.is_file(), "metadata_exists": metadata_path.is_file()}
    if not parquet.is_file() or not metadata_path.is_file():
        return result
    frame = pd.read_parquet(parquet)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    text = frame.astype("string").fillna("")
    eth = text.apply(lambda column: column.str.contains("ETH", case=False, regex=False)).any(axis=1)
    tokens = text.map(lambda value: "".join(ch for ch in str(value).upper() if ch.isalnum()))
    exact = tokens.eq("ETHUSDT").any(axis=1)
    required_metadata = ["fetched_at", "akshare_version", "parameters", "columns", "schema_hash", "row_count", "interface"]
    result.update({
        "row_count": len(frame), "column_count": len(frame.columns), "columns": list(frame.columns),
        "eth_related_rows": int(eth.sum()), "exact_ethusdt_rows": int(exact.sum()),
        "eth_records": frame.loc[eth].to_dict("records"), "metadata": metadata,
        "metadata_missing_fields": [name for name in required_metadata if name not in metadata],
        "metadata_row_count_matches": metadata.get("row_count") == len(frame),
        "parquet_sha256": hashlib.sha256(parquet.read_bytes()).hexdigest(),
        "independent_status": "unsupported" if int(exact.sum()) == 0 else "success",
    })
    return result


def database_summary(tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
    result = {"counts": {k: len(v) for k, v in tables.items()}}
    with duckdb.connect(str(DB_PATH), read_only=True) as connection:
        result["run_ids"] = connection.execute("SELECT run_id,count(*) FROM clean.crypto_price_fact GROUP BY run_id").fetchall()
        result["source_distribution"] = connection.execute("SELECT source,count(*) FROM clean.crypto_price_fact GROUP BY source").fetchall()
        result["symbol_distribution"] = connection.execute("SELECT symbol,count(*) FROM clean.crypto_price_fact GROUP BY symbol").fetchall()
        result["exchange_distribution"] = connection.execute("SELECT exchange,count(*) FROM clean.crypto_price_fact GROUP BY exchange").fetchall()
        result["market_distribution"] = connection.execute("SELECT market,count(*) FROM clean.crypto_price_fact GROUP BY market").fetchall()
        result["interval_distribution"] = connection.execute("SELECT interval,count(*) FROM clean.crypto_price_fact GROUP BY interval").fetchall()
        result["time_range"] = connection.execute("SELECT min(trade_time)::VARCHAR,max(trade_time)::VARCHAR FROM clean.crypto_price_fact").fetchone()
    return result


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    csv, js, db, tables = read_sources()
    reconciliation = compare_pair("CSV_vs_DuckDB", csv, db) + compare_pair("JSON_vs_DuckDB", js, db) + compare_pair("CSV_vs_JSON", csv, js)
    pd.DataFrame(reconciliation).to_csv(OUT / "stage11_data_reconciliation.csv", index=False, encoding="utf-8-sig")
    metrics = independent_metrics(db, tables["indicators"], tables["profile"])
    pd.DataFrame(metrics).to_csv(OUT / "stage11_metric_recalculation.csv", index=False, encoding="utf-8-sig")
    faults = fault_rows(db)
    pd.DataFrame(faults).to_csv(OUT / "stage11_fault_injection.csv", index=False, encoding="utf-8-sig")
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_quality": data_quality(db), "database": database_summary(tables),
        "reconciliation": {
            "checks": len(reconciliation), "failed": sum(row["status"] == "FAIL" for row in reconciliation),
            "rounded_hashes": {"csv": rounded_hash(csv), "json": rounded_hash(js), "duckdb": rounded_hash(db)},
        },
        "metrics": {"checks": len(metrics), "failed": sum(row["status"] == "FAIL" for row in metrics)},
        "fault_injection": {"checks": len(faults), "blocked": sum(bool(row["blocked"]) for row in faults), "failed": sum(row["status"] == "FAIL" for row in faults)},
        "idempotency": idempotency(tables), "akshare_raw": akshare_raw(),
    }
    (OUT / "independent_audit_evidence.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=scalar) + "\n", encoding="utf-8")
    print(json.dumps({
        "data_rows": result["data_quality"]["row_count"],
        "reconciliation_failed": result["reconciliation"]["failed"],
        "metric_failed": result["metrics"]["failed"],
        "fault_failed": result["fault_injection"]["failed"],
        "idempotency": result["idempotency"]["status"],
    }, indent=2))


if __name__ == "__main__":
    main()
