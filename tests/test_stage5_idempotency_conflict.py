from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from akshare_data_test.stage5_idempotency import (
    IdempotencyPayloadConflict,
    prepare_mapping_records,
    prepare_quality_records,
    upsert_hashed_records,
)

ROOT = Path(__file__).resolve().parents[1]


def _mapping(notes: str = "") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "transform_run_id": "run-a",
                "source_dataset": "source",
                "source_field": "field",
                "canonical_field": "canonical",
                "data_type": "float64",
                "source_unit": "unknown",
                "target_unit": "unknown",
                "scale_factor": 1.0,
                "nullable": True,
                "required": False,
                "mapping_status": "passthrough",
                "mapping_evidence": "raw",
                "notes": notes,
            }
        ]
    )


def _quality(message: str = "original") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "transform_run_id": "run-a",
                "dataset_id": "dataset",
                "check_name": "check",
                "severity": "WARN",
                "status": "WARN",
                "issue_count": 1,
                "message": message,
            }
        ]
    )


@pytest.mark.parametrize(
    ("table", "key", "base", "conflict"),
    [
        (
            "field_mapping_registry",
            "mapping_key",
            lambda: prepare_mapping_records(_mapping(), ROOT),
            lambda: prepare_mapping_records(_mapping("changed"), ROOT),
        ),
        (
            "data_quality_issue",
            "issue_key",
            lambda: prepare_quality_records(_quality(), ROOT),
            lambda: prepare_quality_records(_quality("changed"), ROOT),
        ),
    ],
)
def test_payload_conflict_rolls_back_entire_transaction(
    tmp_path, table, key, base, conflict
):
    database = tmp_path / f"{table}.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            (ROOT / "sql/stage5_schema.sql").read_text("utf-8")
        )
        connection.execute(
            (ROOT / "sql/stage5_metadata_indexes.sql").read_text("utf-8")
        )
        upsert_hashed_records(connection, table, base(), key)
        connection.execute("BEGIN")
        connection.execute(
            """
            INSERT INTO dim_security VALUES
            ('000001', 'SZ', 'SZ000001', 'sz', 'A_SHARE', 'CNY', true)
            """
        )
        with pytest.raises(
            IdempotencyPayloadConflict,
            match="idempotency_payload_conflict",
        ):
            upsert_hashed_records(connection, table, conflict(), key)
        connection.execute("ROLLBACK")
        assert connection.execute(
            "SELECT count(*) FROM dim_security"
        ).fetchone()[0] == 0
        assert connection.execute(
            f"SELECT count(*) FROM {table}"
        ).fetchone()[0] == 1
