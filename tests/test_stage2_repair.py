"""Offline tests for the Stage 2 repair. All network behavior is mocked."""
from __future__ import annotations

import argparse
import csv
import json
import socket
import ssl
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml

from akshare_data_test.adapters.akshare_probe import (
    ProbeResult,
    _classify_error,
    _root_exception,
    probe_function,
)
from akshare_data_test.cli import _pool_date_arg
from akshare_data_test.network_preflight import (
    _classify_layer_error,
    run_network_preflight,
)
from akshare_data_test.smoke import (
    _resolve_pool_date_from_raw_probe,
    run_smoke_tests,
)


def _probe_config(
    probe_id: str,
    interface_name: str,
    *,
    policy: dict | None = None,
    scope: str = "single_symbol",
) -> dict:
    return {
        "probe_id": probe_id,
        "interface_name": interface_name,
        "category": "limit_event" if "pool" in probe_id else "history",
        "enabled": True,
        "scope": scope,
        "symbol_format": "none",
        "parameter_policy": policy or {},
        "required_columns": [],
        "notes": "offline test",
    }


def _result(probe_id: str, status: str, coverage_end: str = "") -> ProbeResult:
    return ProbeResult(
        run_id="test-run",
        probe_id=probe_id,
        category="test",
        interface_name="test",
        function_exists=True,
        function_signature="()",
        parameters_json="{}",
        started_at="",
        finished_at="",
        elapsed_seconds=0,
        attempt_count=1,
        akshare_version="test",
        status=status,
        capability_result="",
        coverage_end=coverage_end,
    )


def test_pool_date_valid():
    assert _pool_date_arg("2026-07-24") == "2026-07-24"


@pytest.mark.parametrize("value", ["20260724", "2026-7-24", "2026-02-30"])
def test_pool_date_invalid(value):
    with pytest.raises(argparse.ArgumentTypeError):
        _pool_date_arg(value)


def test_invalid_pool_date_cli_exits_nonzero(monkeypatch):
    from akshare_data_test.cli import main

    monkeypatch.setattr(
        sys,
        "argv",
        ["akshare-data-test", "smoke-test", "--pool-date", "2026-02-30"],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code != 0


def test_cli_date_has_priority_over_raw_date(monkeypatch):
    calls = []
    configs = [
        _probe_config("stock_daily_raw", "raw"),
        _probe_config(
            "limit_up_pool",
            "pool",
            policy={"date": "resolve_pool_date"},
            scope="full_market",
        ),
    ]

    def fake_probe(config, run_id, as_of, pool_date, pool_date_source, max_sample_rows):
        calls.append((config["probe_id"], pool_date, pool_date_source))
        return _result(
            config["probe_id"],
            "success",
            coverage_end="2026-07-23" if config["probe_id"] == "stock_daily_raw" else "",
        )

    monkeypatch.setattr(
        "akshare_data_test.smoke.load_interfaces_config",
        lambda: {"probes": configs},
    )
    monkeypatch.setattr("akshare_data_test.smoke.probe_function", fake_probe)
    run_smoke_tests(
        date(2026, 7, 27),
        "600763",
        pool_date="2026-07-24",
    )
    assert calls[-1] == ("limit_up_pool", "2026-07-24", "cli")


def test_raw_date_resolution_and_future_rejection():
    raw = _result("stock_daily_raw", "success", "2026-07-24")
    assert _resolve_pool_date_from_raw_probe(raw, date(2026, 7, 27)) == "2026-07-24"
    raw.coverage_end = "2026-07-28"
    assert _resolve_pool_date_from_raw_probe(raw, date(2026, 7, 27)) is None
    raw.probe_id = "stock_daily_qfq"
    raw.coverage_end = "2026-07-24"
    assert _resolve_pool_date_from_raw_probe(raw, date(2026, 7, 27)) is None


def test_explicit_pool_date_decouples_both_pools(monkeypatch):
    seen = []
    configs = [
        _probe_config("stock_daily_raw", "raw"),
        _probe_config(
            "limit_up_pool", "up", policy={"date": "resolve_pool_date"}, scope="full_market"
        ),
        _probe_config(
            "limit_down_pool", "down", policy={"date": "resolve_pool_date"}, scope="full_market"
        ),
    ]

    def fake_probe(config, run_id, as_of, pool_date, pool_date_source, max_sample_rows):
        seen.append((config["probe_id"], pool_date, pool_date_source))
        status = "failed" if config["probe_id"] == "stock_daily_raw" else "empty"
        result = _result(config["probe_id"], status)
        result.pool_date = pool_date or ""
        result.pool_date_source = pool_date_source
        return result

    monkeypatch.setattr(
        "akshare_data_test.smoke.load_interfaces_config",
        lambda: {"probes": configs},
    )
    monkeypatch.setattr("akshare_data_test.smoke.probe_function", fake_probe)
    results, _, _ = run_smoke_tests(
        date(2026, 7, 27),
        "600763",
        pool_date="2026-07-24",
    )
    assert [item.probe_id for item in results] == [
        "stock_daily_raw",
        "limit_up_pool",
        "limit_down_pool",
    ]
    assert seen[1:] == [
        ("limit_up_pool", "2026-07-24", "cli"),
        ("limit_down_pool", "2026-07-24", "cli"),
    ]


def test_unresolved_pool_date_skips_without_call(monkeypatch):
    import akshare

    calls = []
    monkeypatch.setattr("akshare_data_test.adapters.akshare_probe.time.sleep", lambda _: None)

    def should_not_run(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame()

    monkeypatch.setattr(akshare, "stock_zt_pool_em", should_not_run)
    config = _probe_config(
        "limit_up_pool",
        "stock_zt_pool_em",
        policy={"date": "resolve_pool_date"},
        scope="full_market",
    )
    result = probe_function(
        config,
        "run",
        date(2026, 7, 27),
        None,
        pool_date_source="unresolved",
    )
    assert result.status == "skipped"
    assert result.error_type == "dependency_failure"
    assert result.pool_date_source == "unresolved"
    assert calls == []


def test_pool_interfaces_called_once_each(monkeypatch):
    configs = [
        _probe_config(
            "limit_up_pool", "up", policy={"date": "resolve_pool_date"}, scope="full_market"
        ),
        _probe_config(
            "limit_down_pool", "down", policy={"date": "resolve_pool_date"}, scope="full_market"
        ),
    ]
    calls = {"limit_up_pool": 0, "limit_down_pool": 0}

    def fake_probe(config, run_id, as_of, pool_date, pool_date_source, max_sample_rows):
        calls[config["probe_id"]] += 1
        return _result(config["probe_id"], "empty")

    monkeypatch.setattr(
        "akshare_data_test.smoke.load_interfaces_config",
        lambda: {"probes": configs + configs},
    )
    monkeypatch.setattr("akshare_data_test.smoke.probe_function", fake_probe)
    run_smoke_tests(date(2026, 7, 27), "600763", pool_date="2026-07-24")
    assert calls == {"limit_up_pool": 1, "limit_down_pool": 1}


def test_network_failure_retries_only_once(monkeypatch):
    import akshare

    attempts = 0

    def fail(**kwargs):
        nonlocal attempts
        attempts += 1
        raise ConnectionError("connection refused")

    monkeypatch.setattr(akshare, "stock_zh_a_hist", fail)
    monkeypatch.setattr("akshare_data_test.adapters.akshare_probe.time.sleep", lambda _: None)
    result = probe_function(
        _probe_config("stock_daily_raw", "stock_zh_a_hist"),
        "run",
        date(2026, 7, 27),
    )
    assert attempts == 2
    assert result.attempt_count == 2
    assert result.retry_reason == "connection_error"


def test_root_exception_is_recorded(monkeypatch):
    import akshare

    root = socket.gaierror(11001, "getaddrinfo failed")
    outer = ConnectionError("wrapper")
    outer.__cause__ = root

    def fail(**kwargs):
        raise outer

    monkeypatch.setattr(akshare, "stock_zh_a_hist", fail)
    monkeypatch.setattr("akshare_data_test.adapters.akshare_probe.time.sleep", lambda _: None)
    result = probe_function(
        _probe_config("stock_daily_raw", "stock_zh_a_hist"),
        "run",
        date(2026, 7, 27),
    )
    assert _root_exception(outer) is root
    assert result.root_exception_class == "gaierror"
    assert result.error_type == "dns_error"


def test_dns_tcp_tls_errors_are_distinct():
    assert _classify_layer_error(socket.gaierror("dns"), "dns") == "dns_error"
    assert _classify_layer_error(ConnectionRefusedError(), "tcp") == "connection_error"
    assert _classify_layer_error(ssl.SSLError("tls"), "tls") == "ssl_error"


def test_parameter_error_is_not_connection_error(monkeypatch):
    import akshare

    def fail(**kwargs):
        raise TypeError("unexpected keyword argument 'bad'")

    monkeypatch.setattr(akshare, "stock_zh_a_hist", fail)
    result = probe_function(
        _probe_config("stock_daily_raw", "stock_zh_a_hist"),
        "run",
        date(2026, 7, 27),
    )
    assert result.error_type == "invalid_parameter"
    assert result.attempt_count == 1
    assert _classify_error(TypeError("unexpected keyword")) == "invalid_parameter"


def test_empty_dataframe_and_unexpected_return_are_distinct(monkeypatch):
    import akshare

    config = _probe_config("stock_daily_raw", "stock_zh_a_hist")
    monkeypatch.setattr(akshare, "stock_zh_a_hist", lambda **kwargs: pd.DataFrame())
    empty = probe_function(config, "run", date(2026, 7, 27))
    assert empty.status == "empty"
    assert empty.error_type == "empty_result"
    assert empty.row_count == 0

    monkeypatch.setattr(akshare, "stock_zh_a_hist", lambda **kwargs: None)
    unexpected = probe_function(config, "run", date(2026, 7, 27))
    assert unexpected.status == "failed"
    assert unexpected.error_type == "unexpected_return_type"
    assert unexpected.row_count is None


def test_csv_and_manifest_redact_proxy_credentials(monkeypatch, tmp_path):
    import akshare

    secret_proxy = "http://user:password@proxy.invalid:8080"
    monkeypatch.setenv("HTTPS_PROXY", secret_proxy)
    monkeypatch.setattr("akshare_data_test.adapters.akshare_probe.time.sleep", lambda _: None)

    def fail(**kwargs):
        raise ConnectionError(f"failed through {secret_proxy}")

    monkeypatch.setattr(akshare, "stock_zh_a_hist", fail)
    config = _probe_config("stock_daily_raw", "stock_zh_a_hist")
    monkeypatch.setattr(
        "akshare_data_test.smoke.load_interfaces_config",
        lambda: {"probes": [config]},
    )
    csv_path = tmp_path / "result.csv"
    evidence = tmp_path / "evidence"
    run_smoke_tests(
        date(2026, 7, 27),
        "600763",
        output_path=csv_path,
        evidence_dir=evidence,
    )
    combined = csv_path.read_text("utf-8-sig")
    manifest = next(evidence.glob("*/manifest.json"))
    combined += manifest.read_text("utf-8")
    assert secret_proxy not in combined
    assert "user:password" not in combined


def test_twelve_probes_map_to_eleven_unique_functions():
    config_path = Path(__file__).resolve().parents[1] / "config" / "interfaces.yml"
    config = yaml.safe_load(config_path.read_text("utf-8"))
    assert len(config["probes"]) == 12
    assert len({item["interface_name"] for item in config["probes"]}) == 11


def test_preflight_blocked_does_not_fabricate_success(monkeypatch):
    failure = {
        "host": "example.invalid",
        "dns_status": "fail",
        "resolved_addresses": [],
        "tcp_443_status": "not_tested",
        "tls_status": "not_tested",
        "error_layer": "dns",
        "error_type": "dns_error",
        "error_summary": "not found",
    }
    monkeypatch.setattr(
        "akshare_data_test.network_preflight._check_host",
        lambda host, timeout: {**failure, "host": host},
    )
    report = run_network_preflight(hosts=("one.invalid", "two.invalid"))
    assert report["overall_status"] == "BLOCKED"
    assert all(item["dns_status"] == "fail" for item in report["hosts"])
    assert "success" not in json.dumps(report).lower()


def test_success_sample_gets_evidence_path(monkeypatch, tmp_path):
    config = _probe_config("stock_daily_raw", "raw")

    def fake_probe(config, run_id, as_of, pool_date, pool_date_source, max_sample_rows):
        result = _result(config["probe_id"], "success", "2026-07-24")
        result.columns_json = '["日期","收盘"]'
        result.dtypes_json = '["object","float64"]'
        result.schema_hash = "hash"
        result.sample_records_json = '[{"日期":"2026-07-24","收盘":1.0}]'
        result.row_count = 1
        result.column_count = 2
        return result

    monkeypatch.setattr(
        "akshare_data_test.smoke.load_interfaces_config",
        lambda: {"probes": [config]},
    )
    monkeypatch.setattr("akshare_data_test.smoke.probe_function", fake_probe)
    csv_path = tmp_path / "result.csv"
    evidence = tmp_path / "evidence"
    run_smoke_tests(
        date(2026, 7, 27),
        "600763",
        output_path=csv_path,
        evidence_dir=evidence,
    )
    row = next(csv.DictReader(csv_path.open(encoding="utf-8-sig")))
    assert row["sample_path"].endswith("stock_daily_raw.sample.json")
    assert Path(row["sample_path"]).exists()
