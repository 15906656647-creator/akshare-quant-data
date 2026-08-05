from __future__ import annotations

import subprocess
import sys
import uuid
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_cli(*arguments: str):
    return subprocess.run(
        [sys.executable, str(ROOT / "run_pipeline.py"), *arguments],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False,
    )


def test_required_stage14_help_commands():
    for command in ("smoke-test", "fetch-market", "run-all"):
        result = run_cli(command, "--help")
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout.lower()


def test_run_all_cli_dry_run_order():
    result = run_cli(
        "run-all", "--start", "20250101", "--end", "20250131", "--dry-run"
    )
    assert result.returncode == 0, result.stderr
    positions = [result.stdout.index(task) for task in (
        "smoke-test", "fetch-market", "fetch-financial", "clean",
        "build-features", "quality-check", "build-report",
    )]
    assert positions == sorted(positions)


def test_run_all_invalid_date_has_nonzero_exit():
    result = run_cli(
        "run-all", "--start", "20250201", "--end", "20250131", "--dry-run"
    )
    assert result.returncode != 0
    assert "--start must be earlier" in result.stderr


def test_fetch_market_compact_dates_dry_run():
    result = run_cli(
        "fetch-market", "--start", "20250101", "--end", "20250131", "--dry-run"
    )
    assert result.returncode == 0, result.stderr
    assert "start=2025-01-01 end=2025-01-31" in result.stdout


def test_fetch_market_rejects_partial_compact_date_pair():
    result = run_cli("fetch-market", "--start", "20250101", "--dry-run")
    assert result.returncode == 2
    assert "--start and --end must be provided together" in result.stderr


def test_established_standalone_command_gets_stage14_status_log(tmp_path, monkeypatch):
    from akshare_data_test import cli

    run_id = str(uuid.uuid4())
    monkeypatch.delenv("AKSHARE_STAGE14_CHILD", raising=False)
    monkeypatch.setattr(cli, "project_root", lambda: tmp_path)
    args = Namespace(
        run_id=run_id, as_of_date="2026-07-27", start_date=None,
        start=None, end=None, dry_run=False, log_level="INFO",
        force=False, only_symbol=None,
    )
    assert cli._run_stage14_logged_single("build-features", args, lambda _args: 0) == 0
    status = tmp_path / "logs" / run_id / "task_status.json"
    assert status.is_file()
    assert '"task_name": "build-features"' in status.read_text("utf-8")


def test_established_standalone_exception_is_logged(tmp_path, monkeypatch):
    from akshare_data_test import cli

    run_id = str(uuid.uuid4())
    monkeypatch.delenv("AKSHARE_STAGE14_CHILD", raising=False)
    monkeypatch.setattr(cli, "project_root", lambda: tmp_path)
    args = Namespace(
        run_id=run_id, as_of_date="2026-07-27", start_date=None,
        start=None, end=None, dry_run=False, log_level="INFO",
        force=False, only_symbol=None,
    )

    def fail(_args):
        raise RuntimeError("standalone fault")

    assert cli._run_stage14_logged_single("build-features", args, fail) == 1
    log = tmp_path / "logs" / run_id / "pipeline.log"
    status = tmp_path / "logs" / run_id / "task_status.json"
    assert "Traceback" in log.read_text("utf-8")
    assert '"status": "failed"' in status.read_text("utf-8")


def test_child_env_bypasses_standalone_status_logging(tmp_path, monkeypatch):
    from akshare_data_test import cli

    monkeypatch.setenv("AKSHARE_STAGE14_CHILD", "1")
    monkeypatch.setattr(cli, "project_root", lambda: tmp_path)
    args = Namespace(
        run_id=str(uuid.uuid4()), as_of_date="2026-07-27", start_date=None,
        start=None, end=None, dry_run=False, log_level="INFO",
        force=False, only_symbol=None,
    )
    assert cli._run_stage14_logged_single("build-features", args, lambda _args: 0) == 0
    assert not (tmp_path / "logs").exists()
