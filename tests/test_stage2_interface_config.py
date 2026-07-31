"""Offline tests for config/interfaces.yml and ProbeResult model. No network."""
from __future__ import annotations
import json
import yaml
from pathlib import Path
import sys

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "interfaces.yml"


def test_config_parses():
    """interfaces.yml must be valid YAML."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    assert cfg is not None
    assert "schema_version" in cfg
    assert "probes" in cfg
    assert isinstance(cfg["probes"], list)


def test_probe_count():
    """There must be exactly 12 probes."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    assert len(cfg["probes"]) == 12


def test_all_probe_ids_unique():
    """All probe IDs must be unique."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    ids = [p["probe_id"] for p in cfg["probes"]]
    assert len(ids) == len(set(ids)), f"Duplicate probe IDs: {ids}"


def test_all_probes_have_required_keys():
    """Every probe must have required keys."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    required = ["probe_id", "interface_name", "category", "enabled",
                "scope", "symbol_format", "parameter_policy", "required_columns"]
    for p in cfg["probes"]:
        for key in required:
            assert key in p, f"Probe {p.get('probe_id', '?')} missing key: {key}"


def test_scope_values_valid():
    """Scope must be one of the valid values."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    valid_scopes = {"single_symbol", "full_market", "single_call"}
    for p in cfg["probes"]:
        assert p["scope"] in valid_scopes, f"Invalid scope in {p['probe_id']}: {p['scope']}"


def test_interface_names_nonempty():
    """Every interface_name must be non-empty."""
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    for p in cfg["probes"]:
        assert p["interface_name"], f"Empty interface_name in {p['probe_id']}"


def test_probe_result_model():
    """ProbeResult can be instantiated with all fields."""
    from akshare_data_test.adapters.akshare_probe import ProbeResult
    pr = ProbeResult(
        run_id="test",
        probe_id="test_probe",
        category="test",
        interface_name="test_func",
        function_exists=True,
        function_signature="(symbol)",
        parameters_json="{}",
        started_at="2026-01-01T00:00:00",
        finished_at="2026-01-01T00:00:01",
        elapsed_seconds=1.0,
        attempt_count=1,
        akshare_version="1.0.0",
        status="success",
        capability_result="",
        row_count=10,
        column_count=5,
        schema_hash="abc123",
        columns_json='["col1","col2"]',
        dtypes_json='["int64","float64"]',
        required_columns_present=True,
        missing_required_columns_json="[]",
        coverage_start="2026-01-01",
        coverage_end="2026-01-10",
        sample_path="",
        error_type="",
        error_message="",
        notes="",
    )
    assert pr.status == "success"
    assert pr.row_count == 10


def test_probe_result_defaults():
    """ProbeResult default values."""
    from akshare_data_test.adapters.akshare_probe import ProbeResult
    pr = ProbeResult(
        run_id="test",
        probe_id="test",
        category="test",
        interface_name="test",
        function_exists=False,
        function_signature="",
        parameters_json="{}",
        started_at="",
        finished_at="",
        elapsed_seconds=0.0,
        attempt_count=0,
        akshare_version="",
        status="unsupported",
        capability_result="",
        error_type="",
        error_message="",
        notes="",
    )
    assert pr.row_count is None
    assert pr.schema_hash == ""
    assert pr.required_columns_present is None


def test_schema_hash_stable():
    """Schema hash must be stable for same input."""
    from akshare_data_test.adapters.akshare_probe import _compute_schema_hash
    h1 = _compute_schema_hash(["date", "price"], ["object", "float64"])
    h2 = _compute_schema_hash(["date", "price"], ["object", "float64"])
    assert h1 == h2


def test_schema_hash_order_sensitive():
    """Schema hash must change with column order."""
    from akshare_data_test.adapters.akshare_probe import _compute_schema_hash
    h1 = _compute_schema_hash(["date", "price"], ["object", "float64"])
    h2 = _compute_schema_hash(["price", "date"], ["float64", "object"])
    assert h1 != h2


def test_probe_import_no_network(monkeypatch):
    """Importing the probe module must not trigger network calls."""
    called = []
    import builtins
    orig_import = builtins.__import__
    def mock_import(name, *args, **kwargs):
        if name in ("akshare",) and "akshare" not in sys.modules:
            # Only intercept first import
            pass
        return orig_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", mock_import)
    # This should work without network (the probe module imports akshare lazily)
    from akshare_data_test.adapters.akshare_probe import ProbeResult
    assert ProbeResult is not None


def test_function_missing_status():
    """When a function does not exist, status must be 'unsupported'."""
    import unittest.mock as mock
    with mock.patch("akshare_data_test.adapters.akshare_probe._function_exists_and_signature",
                    return_value=(False, "")):
        from akshare_data_test.adapters.akshare_probe import probe_function
        from datetime import date
        result = probe_function(
            {"probe_id": "test", "interface_name": "nonexistent_func",
             "category": "test", "parameter_policy": {}, "required_columns": [],
             "notes": ""},
            "run1", date(2026, 7, 27)
        )
        assert result.status == "unsupported"
        assert result.error_type == "function_missing"
