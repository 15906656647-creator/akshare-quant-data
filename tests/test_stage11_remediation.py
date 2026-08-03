from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from akshare_data_test.assets import ETHUSDT, ETHUSDT_OKX_SPOT
from akshare_data_test.crypto_evidence import validate_raw_evidence, write_raw_evidence
from akshare_data_test.crypto_market import normalize_crypto_bars
from akshare_data_test.quality.crypto_checks import run_stage11_quality_checks
from akshare_data_test.stage10_build import analyze_stage10
from akshare_data_test.stage11_build import analyze_stage11, validate_stage11_inputs
from akshare_data_test.storage.crypto_repository import read_stage11_run, write_stage11_run


ROOT = Path(__file__).resolve().parents[1]
AS_OF = pd.Timestamp("2026-07-27")
START = pd.Timestamp("2026-06-18T00:00:00Z")
END = pd.Timestamp("2026-07-28T00:00:00Z")


def raw_frame(periods: int = 960) -> pd.DataFrame:
    times = pd.date_range(START, periods=periods, freq="h")
    close = 1800 + np.arange(periods, dtype=float) / 10
    return pd.DataFrame({
        "raw_instrument": "ETH-USDT", "data_provider": "okx_public_api",
        "raw_exchange": "OKX", "instrument_type": "spot",
        "bar_interval": "1h", "confirmed": True, "trade_time": times,
        "open": close - 1, "high": close + 2, "low": close - 3,
        "close": close, "volume": 10 + np.arange(periods),
        "quote_volume": (10 + np.arange(periods)) * close,
    })


def make_evidence(path: Path, frame: pd.DataFrame, run_id: str = "remediation-run") -> Path:
    write_raw_evidence(
        path, run_id=run_id, provider="okx_public_api",
        endpoint="https://www.okx.com/api/v5/market/history-candles",
        request_parameters={"instId": "ETH-USDT", "bar": "1H"},
        response=frame, identity=ETHUSDT_OKX_SPOT,
        fetched_at=pd.Timestamp("2026-07-28T00:10:00Z"),
    )
    return path


def normalized(frame: pd.DataFrame | None = None, run_id: str = "remediation-run") -> pd.DataFrame:
    return normalize_crypto_bars(
        raw_frame() if frame is None else frame, asset=ETHUSDT, interval="1h",
        local_timezone="Asia/Shanghai", source="okx_public_api", run_id=run_id,
    )


def build_valid_workspace(tmp_path: Path, run_id: str = "remediation-run") -> tuple[Path, Path]:
    (tmp_path / "config").mkdir(parents=True)
    (tmp_path / "sql").mkdir(parents=True)
    shutil.copy2(ROOT / "config/stage11.yml", tmp_path / "config/stage11.yml")
    shutil.copy2(ROOT / "sql/stage11_schema.sql", tmp_path / "sql/stage11_schema.sql")
    frame = raw_frame()
    evidence = make_evidence(tmp_path / "raw", frame, run_id)
    database = tmp_path / "database" / "stage11.duckdb"
    report, code = analyze_stage11(
        root=tmp_path, as_of_date=AS_OF, input_frame=frame, interval="1h",
        source="okx_public_api", config_path=tmp_path / "config/stage11.yml",
        output_database=database, run_id=run_id, raw_evidence_dir=evidence,
    )
    assert code == 0 and report["run_status"] == "PASS"
    return database, evidence


def strict_validate(tmp_path: Path, database: Path, evidence: Path, run_id: str = "remediation-run") -> dict:
    return validate_stage11_inputs(
        config_path=tmp_path / "config/stage11.yml",
        input_csv=tmp_path / "reports/stage11_crypto_price.csv",
        input_json=tmp_path / "reports/stage11_crypto_price.json",
        output_database=database, raw_evidence_dir=evidence,
        run_id=run_id, as_of_date=AS_OF, strict_artifacts=True,
    )


@pytest.mark.parametrize(
    ("column", "value", "reason"),
    [
        ("raw_instrument", "ETH-USD", "raw_instrument"),
        ("raw_instrument", "ETH-USDT-SWAP", "raw_instrument"),
        ("raw_instrument", "ETH-USD-SWAP", "raw_instrument"),
        ("data_provider", "AKShare", "data_provider"),
        ("data_provider", "binance_public_api", "data_provider"),
        ("raw_exchange", "BINANCE", "raw_exchange"),
        ("instrument_type", "swap", "instrument_type"),
        ("bar_interval", "1d", "bar_interval"),
    ],
)
def test_identity_mismatch_is_rejected_before_normalization(column, value, reason):
    frame = raw_frame()
    frame.loc[0, column] = value
    with pytest.raises(ValueError, match=reason):
        normalized(frame)


@pytest.mark.parametrize("column", ["raw_instrument", "data_provider", "raw_exchange", "instrument_type", "bar_interval"])
def test_missing_identity_field_is_rejected(column):
    with pytest.raises(ValueError, match="identity missing fields"):
        normalized(raw_frame().drop(columns=column))


def test_source_argument_cannot_override_provider():
    with pytest.raises(ValueError, match="source argument"):
        normalize_crypto_bars(
            raw_frame(), asset=ETHUSDT, interval="1h", local_timezone="Asia/Shanghai",
            source="AKShare", run_id="wrong-source",
        )


def test_repository_revalidates_identity_before_creating_database(tmp_path):
    source_db, _ = build_valid_workspace(tmp_path / "source")
    frames = read_stage11_run(source_db, "remediation-run")
    frames["raw"].loc[0, "raw_instrument"] = "ETH-USD"
    target = tmp_path / "must-not-exist.duckdb"
    with pytest.raises(ValueError, match="raw_instrument"):
        write_stage11_run(target, schema_path=ROOT / "sql/stage11_schema.sql", frames=frames, run_id="remediation-run")
    assert not target.exists()


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("missing_dir", "directory missing"),
        ("missing_response", "required file missing"),
        ("empty_response", "required file empty"),
        ("damaged_response", "not valid JSON"),
        ("row_count", "response_row_count mismatch"),
        ("schema_hash", "response_schema_hash mismatch"),
        ("content_hash", "content hash mismatch"),
        ("request_instrument", "request requested_instrument mismatch"),
        ("manifest_file", "manifest file missing"),
        ("response_identity", "identity fields missing"),
    ],
)
def test_raw_evidence_contract_fails_closed(tmp_path, mutation, reason):
    evidence = tmp_path / "raw"
    if mutation != "missing_dir":
        make_evidence(evidence, raw_frame())
        if mutation == "missing_response":
            (evidence / "response.json").unlink()
        elif mutation == "empty_response":
            (evidence / "response.json").write_bytes(b"")
        elif mutation == "damaged_response":
            (evidence / "response.json").write_text("{broken", encoding="utf-8")
        elif mutation in {"row_count", "schema_hash"}:
            metadata = json.loads((evidence / "metadata.json").read_text(encoding="utf-8"))
            metadata["response_row_count" if mutation == "row_count" else "response_schema_hash"] = -1 if mutation == "row_count" else "bad"
            (evidence / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
        elif mutation == "content_hash":
            manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
            manifest["response_content_sha256"] = "0" * 64
            (evidence / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        elif mutation == "request_instrument":
            request = json.loads((evidence / "request.json").read_text(encoding="utf-8"))
            request["requested_instrument"] = "ETH-USD"
            (evidence / "request.json").write_text(json.dumps(request), encoding="utf-8")
        elif mutation == "manifest_file":
            manifest = json.loads((evidence / "manifest.json").read_text(encoding="utf-8"))
            manifest["evidence_files"].append({"name": "missing.json", "sha256": "0" * 64})
            (evidence / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        elif mutation == "response_identity":
            response = json.loads((evidence / "response.json").read_text(encoding="utf-8"))
            for row in response:
                row.pop("raw_instrument", None)
            (evidence / "response.json").write_text(json.dumps(response), encoding="utf-8")
    result = validate_raw_evidence(evidence, run_id="remediation-run", expected=ETHUSDT_OKX_SPOT)
    assert result["status"] == "BLOCKED"
    assert any(reason in item for item in result["blocking_reasons"])


def test_strict_validate_only_accepts_untampered_run_and_is_read_only(tmp_path):
    database, evidence = build_valid_workspace(tmp_path)
    before = {p: p.stat().st_mtime_ns for p in [database, *evidence.iterdir(), *list((tmp_path / "reports").iterdir())]}
    result = strict_validate(tmp_path, database, evidence)
    after = {p: p.stat().st_mtime_ns for p in before}
    assert result["status"] == "READY" and result["row_count"] == 960
    assert before == after


@pytest.mark.parametrize(
    ("target", "mutation", "expected_reason"),
    [
        ("csv", "delete_row", "expected_bar_count"),
        ("csv", "modify_close", "canonical row hashes mismatch"),
        ("json", "modify_close", "canonical row hashes mismatch"),
        ("json", "modify_timestamp", "configured_time_range"),
        ("json", "modify_instrument", "identity_invariants"),
        ("json", "modify_exchange", "identity_invariants"),
        ("database", "modify_source", "identity_invariants"),
        ("database", "modify_timestamp", "configured_time_range"),
        ("database", "modify_instrument", "identity_invariants"),
    ],
)
def test_validate_only_blocks_artifact_tampering(tmp_path, target, mutation, expected_reason):
    database, evidence = build_valid_workspace(tmp_path)
    csv_path = tmp_path / "reports/stage11_crypto_price.csv"
    json_path = tmp_path / "reports/stage11_crypto_price.json"
    if target == "csv":
        frame = pd.read_csv(csv_path)
        if mutation == "delete_row":
            frame = frame.iloc[:-1]
        else:
            frame.loc[10, "close"] += 1
        frame.to_csv(csv_path, index=False)
    elif target == "json":
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        if mutation == "modify_close":
            payload[10]["close"] += 1
        elif mutation == "modify_timestamp":
            payload[0]["trade_time"] = "2026-06-18T00:30:00+00:00"
        elif mutation == "modify_instrument":
            payload[0]["raw_instrument"] = "ETH-USD"
        else:
            payload[0]["raw_exchange"] = "BINANCE"
        json_path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        with duckdb.connect(str(database)) as connection:
            if mutation == "modify_source":
                connection.execute("UPDATE clean.crypto_price_fact SET source='AKShare' WHERE trade_time=(SELECT min(trade_time) FROM clean.crypto_price_fact)")
            elif mutation == "modify_timestamp":
                connection.execute("UPDATE clean.crypto_price_fact SET trade_time=trade_time+INTERVAL 30 MINUTE WHERE trade_time=(SELECT min(trade_time) FROM clean.crypto_price_fact)")
            else:
                connection.execute("UPDATE clean.crypto_price_fact SET raw_instrument='ETH-USD' WHERE trade_time=(SELECT min(trade_time) FROM clean.crypto_price_fact)")
    result = strict_validate(tmp_path, database, evidence)
    assert result["status"] == "BLOCKED"
    assert any(expected_reason in item for item in result["blocking_reasons"])


def test_database_constraint_rejects_provider_tampering(tmp_path):
    database, _ = build_valid_workspace(tmp_path)
    with duckdb.connect(str(database)) as connection:
        with pytest.raises(duckdb.ConstraintException):
            connection.execute("UPDATE raw.crypto_market_data SET data_provider='binance_public_api'")


@pytest.mark.parametrize(
    ("mutation", "expected_check"),
    [
        ("infinity", "numeric_finite"), ("negative_infinity", "numeric_finite"),
        ("nan", "numeric_finite"), ("string_numeric", "numeric_finite"),
        ("negative_volume", "volume_non_negative"),
        ("invalid_high", "ohlc_reasonable"), ("invalid_low", "ohlc_reasonable"),
        ("outside_range", "configured_time_range"), ("half_hour", "hour_boundary"),
        ("duplicate", "primary_key_unique"), ("missing", "time_continuity"),
        ("unfinished", "completed_candles"), ("swapped", "time_strictly_increasing"),
    ],
)
def test_numeric_and_time_quality_faults_are_specific(mutation, expected_check):
    bars = normalized()
    if mutation == "infinity": bars.loc[10, "high"] = np.inf
    elif mutation == "negative_infinity": bars.loc[10, "low"] = -np.inf
    elif mutation == "nan": bars.loc[10, "close"] = np.nan
    elif mutation == "string_numeric":
        bars["close"] = bars["close"].astype(object); bars.loc[10, "close"] = "invalid"
    elif mutation == "negative_volume": bars.loc[10, "volume"] = -1
    elif mutation == "invalid_high": bars.loc[10, "high"] = bars.loc[10, "close"] - 1
    elif mutation == "invalid_low": bars.loc[10, "low"] = bars.loc[10, "open"] + 1
    elif mutation == "outside_range":
        extra = bars.iloc[[0]].copy(); extra["trade_time"] -= pd.Timedelta(hours=1); extra["local_trade_time"] -= pd.Timedelta(hours=1)
        bars = pd.concat([extra, bars], ignore_index=True)
    elif mutation == "half_hour": bars.loc[10, "trade_time"] += pd.Timedelta(minutes=30)
    elif mutation == "duplicate": bars.loc[10, "trade_time"] = bars.loc[9, "trade_time"]
    elif mutation == "missing": bars = bars.drop(index=10).reset_index(drop=True)
    elif mutation == "unfinished": bars.loc[10, "confirmed"] = False
    elif mutation == "swapped": bars.iloc[[10, 11]] = bars.iloc[[11, 10]].to_numpy()
    quality = run_stage11_quality_checks(
        bars, run_id="remediation-run", as_of_date=AS_OF, interval="1h",
        expected_symbol="ETHUSDT", checked_at=END,
        expected_start=START, expected_end_exclusive=END,
    ).set_index("check_name")
    assert quality.loc[expected_check, "status"] == "FAIL"
    assert quality.loc[expected_check, "observed_value"] != quality.loc[expected_check, "expected_value"]


def test_quality_failure_does_not_create_database_or_reports(tmp_path):
    (tmp_path / "config").mkdir(); (tmp_path / "sql").mkdir()
    shutil.copy2(ROOT / "config/stage11.yml", tmp_path / "config/stage11.yml")
    shutil.copy2(ROOT / "sql/stage11_schema.sql", tmp_path / "sql/stage11_schema.sql")
    frame = raw_frame(); frame.loc[10, "volume"] = -1
    evidence = make_evidence(tmp_path / "raw", frame)
    database = tmp_path / "database" / "bad.duckdb"
    report, code = analyze_stage11(
        root=tmp_path, as_of_date=AS_OF, input_frame=frame, interval="1h",
        source="okx_public_api", config_path=tmp_path / "config/stage11.yml",
        output_database=database, run_id="remediation-run", raw_evidence_dir=evidence,
    )
    assert code == 1 and report["run_status"] == "BLOCKED"
    assert "volume_non_negative" in report["blocking_reasons"]
    assert not database.exists() and not (tmp_path / "reports").exists()


def test_stage10_crypto_returns_not_applicable_before_any_financial_read(tmp_path, monkeypatch):
    called = {"reads": 0}
    def forbidden(*args, **kwargs):
        called["reads"] += 1
        raise AssertionError("financial read must not occur")
    monkeypatch.setattr("akshare_data_test.stage10_build._read_inputs", forbidden)
    report, code = analyze_stage10(
        root=tmp_path, config_path=tmp_path / "missing.yml",
        input_database=tmp_path / "missing.duckdb", output_database=tmp_path / "out.duckdb",
        as_of_date=AS_OF, asset_type="crypto",
    )
    assert code == 0 and report["status"] == "not_applicable"
    assert report["reason"] and report["financial_results"] == {}
    assert report["financial_adapter_called"] is False and called["reads"] == 0
    assert not (tmp_path / "out.duckdb").exists() and not (tmp_path / "reports").exists()


def test_stage10_unknown_asset_type_never_defaults_to_equity(tmp_path):
    with pytest.raises(ValueError, match="unsupported asset_type"):
        analyze_stage10(
            root=tmp_path, config_path=tmp_path / "missing.yml",
            input_database=tmp_path / "missing.duckdb", output_database=tmp_path / "out.duckdb",
            as_of_date=AS_OF, asset_type="commodity",
        )


def test_stage10_cli_crypto_not_applicable_has_zero_exit(tmp_path):
    environment = os.environ.copy(); environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "run_pipeline.py"), "analyze-fundamental",
         "--as-of-date", "2026-07-27", "--asset-type", "crypto", "--dry-run"],
        cwd=tmp_path, env=environment, text=True, capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert "NOT_APPLICABLE" in completed.stdout and "not_applicable" in completed.stdout
    assert not (tmp_path / "reports").exists()
