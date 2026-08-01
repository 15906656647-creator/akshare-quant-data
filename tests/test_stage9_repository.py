from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from akshare_data_test.quality.style_checks import run_stage9_quality_checks
from akshare_data_test.storage.style_repository import read_stage9_counts, upsert_stage9_results
from akshare_data_test.style_classification import build_style_profiles
from akshare_data_test.style_features import compute_style_features
from test_style_features import CONFIG, daily


ROOT = Path(__file__).resolve().parents[1]


def frames(run_id="style-run", created=None):
    created = created or pd.Timestamp("2026-07-27", tz="UTC")
    source = daily()
    features = compute_style_features(source, CONFIG, as_of_date=source.trade_date.max())
    profiles = build_style_profiles(features, CONFIG)
    features["run_id"] = profiles["run_id"] = run_id
    features["created_at"] = profiles["created_at"] = created
    quality = run_stage9_quality_checks(
        source, features, profiles, run_id=run_id, as_of_date=source.trade_date.max(),
        expected_symbols=["000001"], expected_windows=[20, 40, 60],
        config_hash="a" * 64, expected_config_hash="a" * 64, checked_at=created,
    )
    report = {
        "run_id": run_id, "run_status": "PASS", "publication_status": "research_only",
        "feature_row_count": 3, "profile_row_count": 1, "config_hash": "a" * 64,
    }
    run = {
        "run_id": run_id, "run_status": "PASS", "publication_status": "research_only",
        "started_at": created, "completed_at": created, "input_database": "fixture.duckdb",
        "input_table": "main.fact_stock_daily", "output_database": "style.duckdb",
        "as_of_date": source.trade_date.max().date(), "window_start": source.trade_date.min().date(),
        "window_end": source.trade_date.max().date(), "symbol_count": 1,
        "feature_row_count": 3, "profile_row_count": 1,
        "quality_passed": int(quality.status.eq("PASS").sum()),
        "quality_failed": int(quality.status.eq("FAIL").sum()),
        "blocking_reasons": [], "config_hash": "a" * 64, "code_version": "fixture",
        "output_type": "fixture", "stage8_publication_status": "blocked",
        "manifest": report, "created_at": created,
    }
    return features, profiles, quality, run


def write(database, values):
    features, profiles, quality, run = values
    upsert_stage9_results(
        database, ROOT / "sql/stage9_schema.sql", features=features,
        profiles=profiles, quality=quality, run=run,
    )


def test_same_run_is_idempotent_and_different_runs_preserve_history(tmp_path):
    database = tmp_path / "stage9.duckdb"
    first = frames("run-one", pd.Timestamp("2026-07-26", tz="UTC"))
    write(database, first)
    write(database, first)
    assert read_stage9_counts(database) == {"features": 3, "profiles": 1, "runs": 1}
    second = frames("run-two", pd.Timestamp("2026-07-27", tz="UTC"))
    write(database, second)
    assert read_stage9_counts(database) == {"features": 6, "profiles": 2, "runs": 2}
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT DISTINCT run_id FROM analysis.v_latest_stage9_style_profile").fetchone()[0] == "run-two"


def test_primary_key_rejects_duplicate_and_transaction_rolls_back(tmp_path):
    database = tmp_path / "stage9.duckdb"
    values = frames()
    write(database, values)
    with duckdb.connect(str(database)) as connection:
        with pytest.raises(duckdb.ConstraintException):
            connection.execute("INSERT INTO feature.stage9_style_feature SELECT * FROM feature.stage9_style_feature LIMIT 1")

    broken = tmp_path / "broken.duckdb"
    features, profiles, quality, run = frames()
    quality["checked_at"] = "invalid-timestamp"
    with pytest.raises(duckdb.ConversionException):
        write(broken, (features, profiles, quality, run))
    with duckdb.connect(str(broken), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('feature','analysis','quality','audit')").fetchone()[0] == 0


def test_latest_view_ignores_blocked_run(tmp_path):
    database = tmp_path / "stage9.duckdb"
    write(database, frames("pass-run", pd.Timestamp("2026-07-26", tz="UTC")))
    blocked = list(frames("blocked-run", pd.Timestamp("2026-07-27", tz="UTC")))
    blocked[3]["run_status"] = "BLOCKED"
    write(database, tuple(blocked))
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute("SELECT DISTINCT run_id FROM analysis.v_latest_stage9_style_profile").fetchone()[0] == "pass-run"

