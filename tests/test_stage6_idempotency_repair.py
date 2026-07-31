from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from akshare_data_test.stage6_build import (
    BUSINESS_KEYS,
    DATASET_TABLES,
    _atomic_parquet,
    _create_database,
    _rollback_preserving_original,
)
from akshare_data_test.stage6_persistence import (
    Stage6ArtifactIdentityConflictError,
    Stage6IncompleteArtifactError,
    Stage6PayloadConflictError,
    resolve_existing_artifact_action,
    stable_dataframe_hash,
)

ROOT = Path(__file__).resolve().parents[1]
FORMAL_DATABASE = (
    ROOT
    / "database"
    / "stage6"
    / "feature_run_id=48af48ca-2707-4c53-ad51-745a17b6295d"
    / "akshare_features.duckdb"
)


@pytest.fixture(scope="module")
def complete_inputs():
    connection = duckdb.connect(str(FORMAL_DATABASE), read_only=True)
    try:
        frames = {
            group: connection.execute(f'SELECT * FROM "{table}"').fetchdf()
            for group, table in DATASET_TABLES.items()
        }
        metadata = {
            name: connection.execute(f'SELECT * FROM "{name}"').fetchdf()
            for name in [
                "feature_run",
                "feature_definition_registry",
                "feature_file_manifest",
                "feature_lineage",
                "feature_quality_issue",
            ]
        }
    finally:
        connection.close()
    assert len(frames) == 9
    assert all(not frame.empty for frame in frames.values())
    assert len(metadata["feature_definition_registry"]) == 109
    assert len(metadata["feature_file_manifest"]) == 9
    assert len(metadata["feature_lineage"]) == 9
    assert not metadata["feature_quality_issue"].empty
    return frames, metadata


def _persist(path: Path, frames, metadata):
    return _create_database(
        path,
        frames,
        metadata["feature_definition_registry"],
        metadata["feature_file_manifest"],
        metadata["feature_lineage"],
        metadata["feature_quality_issue"],
        metadata["feature_run"],
    )


def test_canonical_dataframe_hash_normalizes_order_null_and_signed_zero():
    first = pd.DataFrame(
        {
            "key": [2, 1],
            "value": [float("nan"), -0.0],
            "when": [
                pd.Timestamp("2026-07-27 08:00:00+08:00"),
                pd.Timestamp("2026-07-27 00:00:00+00:00"),
            ],
        }
    )
    second = first.iloc[::-1].reset_index(drop=True)
    second.loc[second["key"].eq(1), "value"] = 0.0
    assert stable_dataframe_hash(first, ["key"]) == stable_dataframe_hash(
        second, ["key"]
    )


def test_feature_file_reuses_logically_identical_payload(tmp_path):
    path = tmp_path / "price_daily" / "feature_run_id=run" / "data.parquet"
    frame = pd.DataFrame(
        {
            "feature_run_id": ["run", "run"],
            "symbol": ["000100", "000101"],
            "trade_date": pd.to_datetime(["2026-07-27", "2026-07-27"]),
            "value": [1.0, 2.0],
        }
    )
    first_sha, first_existing = _atomic_parquet(
        path, frame, ["feature_run_id", "symbol", "trade_date"]
    )
    first_mtime = path.stat().st_mtime_ns
    second_sha, second_existing = _atomic_parquet(
        path,
        frame.iloc[::-1].reset_index(drop=True),
        ["feature_run_id", "symbol", "trade_date"],
    )
    assert first_existing is False
    assert second_existing is True
    assert first_sha == second_sha
    assert path.stat().st_mtime_ns == first_mtime


def test_full_nonempty_same_run_same_path_is_idempotent(
    tmp_path, complete_inputs
):
    frames, metadata = complete_inputs
    path = tmp_path / "features.duckdb"
    first = _persist(path, frames, metadata)
    first_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    first_mtime = path.stat().st_mtime_ns
    second = _persist(path, frames, metadata)
    second_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    assert first["persistence_status"] == "created"
    assert second["persistence_status"] == "idempotent_reuse"
    assert second["inserted"] == 0
    assert second["updated"] == 0
    assert second["overwritten"] == 0
    assert len(second["table_hashes"]) == 14
    assert first_sha == second_sha
    assert path.stat().st_mtime_ns == first_mtime


def test_database_payload_conflict_preserves_clear_error(
    tmp_path, complete_inputs
):
    frames, metadata = complete_inputs
    path = tmp_path / "features.duckdb"
    _persist(path, frames, metadata)
    changed = {name: frame.copy(deep=True) for name, frame in frames.items()}
    changed["price_daily"].loc[
        changed["price_daily"].index[0], "close_qfq"
    ] += 1.0
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(Stage6PayloadConflictError) as captured:
        _persist(path, changed, metadata)
    assert captured.value.error_code == "feature_payload_conflict"
    assert captured.value.table_name == "feat_price_daily"
    assert "cannot rollback - no transaction is active" not in str(captured.value)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_different_run_same_database_path_is_rejected(
    tmp_path, complete_inputs
):
    frames, metadata = complete_inputs
    path = tmp_path / "features.duckdb"
    _persist(path, frames, metadata)
    changed_metadata = {
        name: frame.copy(deep=True) for name, frame in metadata.items()
    }
    changed_metadata["feature_run"].loc[:, "feature_run_id"] = str(uuid.uuid4())
    with pytest.raises(Stage6ArtifactIdentityConflictError) as captured:
        _persist(path, frames, changed_metadata)
    assert captured.value.error_code == "feature_run_path_conflict"


def test_different_run_new_path_can_be_created(tmp_path, complete_inputs):
    frames, metadata = complete_inputs
    new_run = str(uuid.uuid4())
    changed_frames = {
        name: frame.copy(deep=True) for name, frame in frames.items()
    }
    for frame in changed_frames.values():
        frame.loc[:, "feature_run_id"] = new_run
    changed_metadata = {
        name: frame.copy(deep=True) for name, frame in metadata.items()
    }
    for name in ["feature_run", "feature_file_manifest", "feature_lineage"]:
        changed_metadata[name].loc[:, "feature_run_id"] = new_run
    result = _persist(tmp_path / new_run / "features.duckdb", changed_frames, changed_metadata)
    assert result["persistence_status"] == "created"
    assert result["status"] == "PASS"


def test_rollback_failure_is_secondary_and_never_replaces_original():
    class FailedRollback:
        def execute(self, sql):
            raise RuntimeError("cannot rollback - no transaction is active")

    original = Stage6PayloadConflictError(
        "original payload conflict",
        artifact_type="feature_database",
        table_name="feat_price_daily",
    )
    _rollback_preserving_original(FailedRollback(), original, True)
    assert original.error_code == "feature_payload_conflict"
    assert any(
        "secondary rollback failure" in note
        for note in getattr(original, "__notes__", [])
    )


def test_no_rollback_is_attempted_before_begin():
    class MustNotExecute:
        def execute(self, sql):
            raise AssertionError("rollback must not execute")

    original = RuntimeError("before begin")
    _rollback_preserving_original(MustNotExecute(), original, False)
    assert str(original) == "before begin"


@pytest.mark.parametrize(
    "setup",
    ["directory_only", "partial_parquet", "database_only", "manifest_only"],
)
def test_partial_artifact_sets_are_rejected(tmp_path, setup):
    paths = [
        tmp_path / group / "feature_run_id=run" / "data.parquet"
        for group in DATASET_TABLES
    ]
    database = tmp_path / "database" / "features.duckdb"
    manifest = tmp_path / "evidence" / "run" / "manifest.json"
    if setup == "directory_only":
        paths[0].parent.mkdir(parents=True)
    elif setup == "partial_parquet":
        paths[0].parent.mkdir(parents=True)
        paths[0].write_bytes(b"partial")
    elif setup == "database_only":
        database.parent.mkdir(parents=True)
        database.write_bytes(b"partial")
    else:
        manifest.parent.mkdir(parents=True)
        manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(Stage6IncompleteArtifactError):
        resolve_existing_artifact_action(paths, database, manifest)


def test_database_missing_tables_is_incomplete(tmp_path, complete_inputs):
    frames, metadata = complete_inputs
    path = tmp_path / "incomplete.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute("CREATE TABLE feature_run(feature_run_id VARCHAR)")
    connection.execute(
        "INSERT INTO feature_run VALUES (?)",
        [metadata["feature_run"]["feature_run_id"].iloc[0]],
    )
    connection.close()
    with pytest.raises(Stage6IncompleteArtifactError):
        _persist(path, frames, metadata)


def test_failed_new_database_transaction_leaves_no_partial_artifact(
    tmp_path, complete_inputs
):
    frames, metadata = complete_inputs
    invalid = {name: frame.copy(deep=True) for name, frame in frames.items()}
    invalid["price_daily"] = pd.concat(
        [invalid["price_daily"], invalid["price_daily"].iloc[[0]]],
        ignore_index=True,
    )
    path = tmp_path / "rollback-probe.duckdb"
    with pytest.raises(Exception):
        _persist(path, invalid, metadata)
    assert not path.exists()
    assert not list(tmp_path.glob("rollback-probe.duckdb.tmp-*"))
