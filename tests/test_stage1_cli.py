"""Stage 1: CLI tests — run show-config and doctor subcommands."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PYTHON, "-m", "akshare_data_test.cli"] + args,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )


class TestCLIHelp:
    def test_help_exits_zero(self):
        result = _run(["--help"])
        assert result.returncode == 0

    def test_doctor_help_exits_zero(self):
        result = _run(["doctor", "--help"])
        assert result.returncode == 0

    def test_show_config_help_exits_zero(self):
        result = _run(["show-config", "--help"])
        assert result.returncode == 0


class TestShowConfig:
    def test_exits_zero(self):
        result = _run(["show-config", "--as-of-date", "2026-07-27"])
        assert result.returncode == 0, result.stderr

    def test_shows_stock_count_16(self):
        result = _run(["show-config", "--as-of-date", "2026-07-27"])
        assert "Stock count: 16" in result.stdout

    def test_shows_crypto_pair(self):
        result = _run(["show-config", "--as-of-date", "2026-07-27"])
        assert "ETHUSDT" in result.stdout

    def test_shows_resolved_date(self):
        result = _run(["show-config", "--as-of-date", "2026-07-27"])
        assert "2026-07-27" in result.stdout


class TestDoctor:
    def test_exits_zero_when_pass(self, tmp_path):
        output = tmp_path / "doctor.json"
        result = _run([
            "doctor", "--as-of-date", "2026-07-27",
            "--output", str(output),
        ])
        assert result.returncode == 0, (
            f"stderr: {result.stderr}\nstdout: {result.stdout}"
        )

    def test_generates_json(self, tmp_path):
        output = tmp_path / "doctor.json"
        _run([
            "doctor", "--as-of-date", "2026-07-27",
            "--output", str(output),
        ])
        assert output.exists()
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["status"] == "pass", (
            f"Doctor status: {data['status']}, errors: {data.get('errors', [])}"
        )
        assert "python" in data
        assert "packages" in data
        assert "config_checks" in data
        assert "filesystem_checks" in data
        assert "duckdb_check" in data
        assert "resolved_as_of_date" in data
        assert "errors" in data

    def test_json_has_no_secrets(self, tmp_path):
        output = tmp_path / "doctor.json"
        _run([
            "doctor", "--as-of-date", "2026-07-27",
            "--output", str(output),
        ])
        text = output.read_text(encoding="utf-8").lower()
        for secret_word in ["apikey", "api_key", "token", "password", "cookie"]:
            assert secret_word not in text, f"Found '{secret_word}' in report"

    def test_resolved_date_matches_cli(self, tmp_path):
        output = tmp_path / "doctor.json"
        _run([
            "doctor", "--as-of-date", "2026-07-27",
            "--output", str(output),
        ])
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["resolved_as_of_date"] == "2026-07-27"
