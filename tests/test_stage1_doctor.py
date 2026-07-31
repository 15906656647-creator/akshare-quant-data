"""Stage 1: Doctor offline tests — must pass without real network."""

import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


@pytest.fixture
def block_real_network():
    """Replace socket.create_connection to block real network calls."""
    original = socket.create_connection

    def _blocked(address, *args, **kwargs):
        host, port = address
        raise OSError(
            f"Network blocked by test — attempted {host}:{port}"
        )

    socket.create_connection = _blocked
    try:
        yield
    finally:
        socket.create_connection = original


class TestDoctorOffline:
    def test_doctor_runs_offline(self, block_real_network):
        from akshare_data_test.doctor import run_doctor
        result = run_doctor(cli_date="2026-07-27")
        assert result.status == "pass", (
            f"Doctor failed with errors: {result.errors}"
        )

    def test_doctor_checks_python(self, block_real_network):
        from akshare_data_test.doctor import run_doctor
        result = run_doctor(cli_date="2026-07-27")
        assert result.python["64bit"] is True
        assert "version" in result.python
        assert "3." in result.python["version"]

    def test_doctor_checks_packages(self, block_real_network):
        from akshare_data_test.doctor import run_doctor
        result = run_doctor(cli_date="2026-07-27")
        for pkg, ver in result.packages.items():
            assert ver is not None, f"Package '{pkg}' failed to import"
            # ver can be "" for packages without __version__, which is fine

    def test_doctor_checks_configs(self, block_real_network):
        from akshare_data_test.doctor import run_doctor
        result = run_doctor(cli_date="2026-07-27")
        assert result.config_checks.get("universe_parses") is True
        assert result.config_checks.get("stock_count_is_16") is True
        assert result.config_checks.get("metrics_parses") is True

    def test_doctor_checks_duckdb(self, block_real_network):
        from akshare_data_test.doctor import run_doctor
        result = run_doctor(cli_date="2026-07-27")
        assert result.duckdb_check.get("select_1") is True

    def test_doctor_no_system_date_fallback(self, block_real_network):
        from akshare_data_test.doctor import run_doctor
        result = run_doctor(cli_date="2026-07-27")
        assert result.resolved_as_of_date == "2026-07-27"

    def test_doctor_imports_akshare_but_no_data_call(self, block_real_network):
        import akshare
        assert hasattr(akshare, "__version__")
