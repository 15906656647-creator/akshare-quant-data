from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from akshare_data_test.stage18_4_config import load_stage18_4_config
from akshare_data_test.stage18_4_load import run_stage18_4_load
from akshare_data_test.stage18_audit import Stage18Blocked
from test_stage18_4_load import _mini_database


ROOT = Path(__file__).resolve().parents[1]


def test_transaction_rolls_back_all_six_tables_on_validation_failure(monkeypatch, tmp_path):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    connection, config, datasets = _mini_database(source_dir)
    connection.close()
    config = replace(
        config,
        database_root=tmp_path / "transaction_db",
        reports_root=tmp_path / "transaction_reports",
    )
    monkeypatch.setattr("akshare_data_test.stage18_4_load.load_stage18_4_config", lambda _path: config)
    monkeypatch.setattr("akshare_data_test.stage18_4_load._verify_upstream", lambda *_args: ({"ok": True}, datasets))
    monkeypatch.setattr("akshare_data_test.stage18_4_load._protected_state", lambda *_args: {})
    monkeypatch.setattr("akshare_data_test.stage18_4_load.frozen_hashes", lambda *_args: {})
    empty = pd.DataFrame()
    monkeypatch.setattr(
        "akshare_data_test.stage18_4_load._validation_frames",
        lambda *_args: (empty, empty, empty, empty, empty, ["forced_failure"]),
    )
    run_id = "88888888-8888-4888-8888-888888888888"
    with pytest.raises(Stage18Blocked, match="transactional validation failed"):
        run_stage18_4_load(
            root=ROOT, config_path=ROOT / "config/stage18_4.yml",
            as_of_date=date(2026, 7, 27), run_id=run_id,
        )
    database = config.database_root / f"run_id={run_id}" / config.database_filename
    with duckdb.connect(str(database), read_only=True) as check:
        assert check.execute("SHOW TABLES").fetchall() == []
    interrupted = config.reports_root / run_id / "stage18_4_interrupted.json"
    assert json.loads(interrupted.read_text(encoding="utf-8"))["stage18_5_authorized"] is False
