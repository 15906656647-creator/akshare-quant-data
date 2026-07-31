from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from akshare_data_test.limit_event_detection import detect_limit_events
from akshare_data_test.quality.limit_event_checks import run_stage8_quality_checks
from akshare_data_test.stage8_analysis import summarize_annual_events
from akshare_data_test.storage.limit_event_repository import (
    read_raw_daily,
    read_stage8_counts,
    upsert_stage8_results,
)
from test_limit_event_detection import bars
from test_limit_rules import rule, status


ROOT = Path(__file__).resolve().parents[1]


def frames():
    created = pd.Timestamp("2026-07-27T00:00:00Z")
    observations = detect_limit_events(
        bars([10, 11]), [rule()], [status()], run_id="repo-run", created_at=created
    )
    summary, _, blockers = summarize_annual_events(
        observations,
        start_date=pd.Timestamp("2025-07-27"),
        end_date=pd.Timestamp("2026-07-27"),
    )
    summary["run_id"] = "repo-run"
    summary["created_at"] = created
    quality = run_stage8_quality_checks(
        observations, summary, run_id="repo-run", created_at=created
    )
    run = {
        "run_id": "repo-run",
        "as_of_date": pd.Timestamp("2026-07-27").date(),
        "period_start": pd.Timestamp("2025-07-27").date(),
        "price_adjust_type": "raw",
        "source_database": "fixture.duckdb",
        "output_database": "stage8.duckdb",
        "status": "BLOCKED",
        "formal_event_count": 1,
        "provisional_count": 0,
        "unresolved_count": 1,
        "blockers": blockers,
        "created_at": created,
    }
    return observations, summary, quality, run


def test_repository_upsert_is_idempotent_and_unique(tmp_path):
    database = tmp_path / "stage8.duckdb"
    observations, summary, quality, run = frames()
    kwargs = dict(
        database_path=database,
        schema_sql_path=ROOT / "sql/stage8_schema.sql",
        rules=[rule()],
        statuses=[status()],
        observations=observations,
        summary=summary,
        quality=quality,
        run=run,
    )
    upsert_stage8_results(**kwargs)
    upsert_stage8_results(**kwargs)
    assert read_stage8_counts(database) == {
        "observations": 2,
        "formal_events": 1,
        "summaries": 1,
    }


def test_different_runs_preserve_history_and_latest_view(tmp_path):
    database = tmp_path / "stage8-history.duckdb"
    for run_id in ("run-one", "run-two"):
        observations, summary, quality, run = frames()
        observations["run_id"] = run_id
        summary["run_id"] = run_id
        quality["run_id"] = run_id
        run["run_id"] = run_id
        run["status"] = "PASS"
        run["created_at"] = pd.Timestamp(
            "2026-07-26T00:00:00Z"
            if run_id == "run-one"
            else "2026-07-27T00:00:00Z"
        )
        upsert_stage8_results(
            database_path=database,
            schema_sql_path=ROOT / "sql/stage8_schema.sql",
            rules=[rule()],
            statuses=[status()],
            observations=observations,
            summary=summary,
            quality=quality,
            run=run,
        )
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT count(DISTINCT run_id) FROM analysis.fact_limit_event"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT count(DISTINCT run_id) "
            "FROM analysis.limit_event_annual_summary"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT DISTINCT run_id FROM analysis.v_latest_limit_event"
        ).fetchone()[0] == "run-two"
        assert connection.execute(
            "SELECT count(*) FROM audit.stage8_run"
        ).fetchone()[0] == 2


def test_database_primary_key_rejects_duplicate_event(tmp_path):
    database = tmp_path / "stage8.duckdb"
    observations, summary, quality, run = frames()
    upsert_stage8_results(
        database_path=database,
        schema_sql_path=ROOT / "sql/stage8_schema.sql",
        rules=[rule()],
        statuses=[status()],
        observations=observations,
        summary=summary,
        quality=quality,
        run=run,
    )
    with duckdb.connect(str(database)) as connection:
        try:
            connection.execute(
                "INSERT INTO analysis.fact_limit_event "
                "SELECT * FROM analysis.fact_limit_event LIMIT 1"
            )
        except duckdb.ConstraintException:
            pass
        else:
            raise AssertionError("Expected primary-key constraint")


def test_transaction_failure_rolls_back_event_rows(tmp_path):
    database = tmp_path / "stage8-rollback.duckdb"
    observations, summary, quality, run = frames()
    invalid_quality = quality.copy()
    invalid_quality["checked_at"] = "not-a-timestamp"
    try:
        upsert_stage8_results(
            database_path=database,
            schema_sql_path=ROOT / "sql/stage8_schema.sql",
            rules=[rule()],
            statuses=[status()],
            observations=observations,
            summary=summary,
            quality=invalid_quality,
            run=run,
        )
    except duckdb.ConversionException:
        pass
    else:
        raise AssertionError("Expected invalid quality row to fail")
    with duckdb.connect(str(database), read_only=True) as connection:
        assert connection.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_schema IN ('analysis', 'audit', 'quality')"
        ).fetchone()[0] == 0


def test_raw_reader_rejects_implicit_qfq_substitution(tmp_path):
    database = tmp_path / "source.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "CREATE TABLE fact_stock_daily(symbol VARCHAR, exchange VARCHAR, "
            "trade_date DATE, adjust_type VARCHAR, open DOUBLE, high DOUBLE, "
            "low DOUBLE, close DOUBLE)"
        )
        connection.execute(
            "INSERT INTO fact_stock_daily VALUES "
            "('000001','SZ',DATE '2026-01-01','qfq',10,10,10,10)"
        )
    try:
        read_raw_daily(
            database,
            start_date=pd.Timestamp("2025-07-27"),
            end_date=pd.Timestamp("2026-07-27"),
        )
    except RuntimeError as exc:
        assert "no raw daily prices" in str(exc)
    else:
        raise AssertionError("qfq-only database must not be accepted")
