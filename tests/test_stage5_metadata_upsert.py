from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import duckdb
import pandas as pd

from akshare_data_test.stage5_idempotency import (
    canonical_json,
    prepare_mapping_records,
    prepare_quality_records,
    stable_record_hash,
    upsert_hashed_records,
)

ROOT = Path(__file__).resolve().parents[1]


def _mapping(transform_run_id: str = "run-a") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "transform_run_id": transform_run_id,
                "source_dataset": "source",
                "source_field": "field",
                "canonical_field": "canonical",
                "data_type": "float64",
                "source_unit": "percent_point",
                "target_unit": "decimal",
                "scale_factor": 0.01,
                "nullable": True,
                "required": False,
                "mapping_status": "mapped",
                "mapping_evidence": "documented",
                "notes": "",
            }
        ]
    )


def _quality(
    transform_run_id: str = "run-a",
    *,
    source_row_number: int | None = None,
    issue_scope: str = "dataset",
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "transform_run_id": transform_run_id,
                "dataset_id": "dataset",
                "check_name": "check",
                "severity": "WARN",
                "status": "WARN",
                "issue_count": 1,
                "message": "message",
                "issue_code": "check",
                "symbol": None,
                "field_name": None,
                "business_key_json": json.dumps(
                    {"b": 2, "a": 1}
                ),
                "source_file": "data\\raw\\source\\data.parquet",
                "source_row_number": source_row_number,
                "issue_scope": issue_scope,
            }
        ]
    )


def test_canonical_json_is_stable_and_explicit():
    left = {
        "b": Decimal("1.2300"),
        "a": date(2026, 7, 27),
        "null": None,
        "time": datetime(2026, 7, 27, tzinfo=timezone.utc),
    }
    right = dict(reversed(list(left.items())))
    assert canonical_json(left) == canonical_json(right)
    assert stable_record_hash(left) == stable_record_hash(right)
    assert '"null":null' in canonical_json(left)
    assert '"b":"1.2300"' in canonical_json(left)


def test_path_separator_and_json_key_order_do_not_change_issue_key():
    left = _quality()
    right = _quality()
    right.loc[0, "source_file"] = "data/raw/source/data.parquet"
    right.loc[0, "business_key_json"] = '{"a":1,"b":2}'
    left_prepared = prepare_quality_records(left, ROOT)
    right_prepared = prepare_quality_records(right, ROOT)
    assert left_prepared.loc[0, "issue_key"] == right_prepared.loc[0, "issue_key"]
    assert left_prepared.loc[0, "record_hash"] == right_prepared.loc[0, "record_hash"]


def test_metadata_upsert_skips_identical_and_allows_other_transform(tmp_path):
    database = tmp_path / "metadata.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            (ROOT / "sql/stage5_schema.sql").read_text("utf-8")
        )
        connection.execute(
            (ROOT / "sql/stage5_metadata_indexes.sql").read_text("utf-8")
        )
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT index_name FROM duckdb_indexes()"
            ).fetchall()
        }
        assert {
            "uq_data_quality_issue_issue_key",
            "uq_field_mapping_registry_mapping_key",
        } <= indexes
        mapping = prepare_mapping_records(_mapping(), ROOT)
        quality = prepare_quality_records(_quality(), ROOT)
        assert upsert_hashed_records(
            connection,
            "field_mapping_registry",
            mapping,
            "mapping_key",
        ) == {"inserted": 1, "unchanged": 0}
        assert upsert_hashed_records(
            connection,
            "data_quality_issue",
            quality,
            "issue_key",
        ) == {"inserted": 1, "unchanged": 0}
        assert upsert_hashed_records(
            connection,
            "field_mapping_registry",
            mapping,
            "mapping_key",
        ) == {"inserted": 0, "unchanged": 1}
        assert upsert_hashed_records(
            connection,
            "data_quality_issue",
            quality,
            "issue_key",
        ) == {"inserted": 0, "unchanged": 1}

        other_mapping = prepare_mapping_records(_mapping("run-b"), ROOT)
        other_quality = prepare_quality_records(_quality("run-b"), ROOT)
        upsert_hashed_records(
            connection,
            "field_mapping_registry",
            other_mapping,
            "mapping_key",
        )
        upsert_hashed_records(
            connection,
            "data_quality_issue",
            other_quality,
            "issue_key",
        )
        assert connection.execute(
            "SELECT count(*) FROM field_mapping_registry"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT count(*) FROM data_quality_issue"
        ).fetchone()[0] == 2


def test_issue_location_and_scope_are_part_of_identity():
    dataset_issue = prepare_quality_records(_quality(), ROOT)
    row_issue = prepare_quality_records(
        _quality(source_row_number=7, issue_scope="row"), ROOT
    )
    other_row = prepare_quality_records(
        _quality(source_row_number=8, issue_scope="row"), ROOT
    )
    assert len(
        {
            dataset_issue.loc[0, "issue_key"],
            row_issue.loc[0, "issue_key"],
            other_row.loc[0, "issue_key"],
        }
    ) == 3
