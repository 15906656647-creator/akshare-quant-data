from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from akshare_data_test.config import load_universe
from akshare_data_test.stage13_presentation import build_stage13_presentation, inventory_database


ROOT = Path(__file__).resolve().parents[1]
DATABASE_NAMES = (
    "akshare_data_test_stage5_repaired.duckdb",
    "akshare_features_stage6.duckdb",
    "akshare_features_stage7.duckdb",
)
SYMBOLS = [item.symbol for item in load_universe().stocks]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def inventory_fixture(tmp_path: Path) -> tuple[Path, Path]:
    database = tmp_path / "inventory-types.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE TABLE date_rows(symbol VARCHAR, trade_date DATE)")
        connection.execute("INSERT INTO date_rows VALUES ('000100', DATE '2026-07-27'), ('000100', DATE '2026-07-28')")
        connection.execute("CREATE TABLE timestamp_rows(symbol VARCHAR, trade_date TIMESTAMP)")
        connection.execute("INSERT INTO timestamp_rows VALUES ('000100', TIMESTAMP '2026-07-27 23:59:59'), ('000100', TIMESTAMP '2026-07-28 00:00:00')")
        connection.execute("CREATE TABLE timestamptz_rows(symbol VARCHAR, snapshot_at TIMESTAMPTZ)")
        connection.execute("INSERT INTO timestamptz_rows VALUES ('000100', TIMESTAMPTZ '2026-07-27 23:59:59+08:00'), ('000100', TIMESTAMPTZ '2026-07-28 00:00:00+08:00')")
        connection.execute("CREATE TABLE varchar_rows(symbol VARCHAR, trade_date VARCHAR)")
        connection.execute("INSERT INTO varchar_rows VALUES ('000100', '2026-07-27 12:00:00'), ('000100', '2026-07-28')")
        connection.execute("CREATE TABLE partial_varchar(symbol VARCHAR, announcement_date VARCHAR)")
        connection.execute("INSERT INTO partial_varchar VALUES ('000100', '2026-07-27'), ('000100', 'not-a-date'), ('000100', NULL)")
        connection.execute("CREATE TABLE invalid_varchar(symbol VARCHAR, as_of_date VARCHAR)")
        connection.execute("INSERT INTO invalid_varchar VALUES ('000100', 'bad'), ('000100', 'worse')")
        connection.execute("CREATE TABLE audit_metadata(symbol VARCHAR, created_at VARCHAR)")
        connection.execute("INSERT INTO audit_metadata VALUES ('000100', 'not-a-business-date')")
        connection.execute("CREATE TABLE empty_rows(symbol VARCHAR, trade_date DATE)")
        connection.execute("CREATE TABLE no_date(symbol VARCHAR, payload VARCHAR)")
        connection.execute("INSERT INTO no_date VALUES ('000100', 'x')")
        connection.execute("CREATE TABLE no_symbol(trade_date DATE, payload VARCHAR)")
        connection.execute("INSERT INTO no_symbol VALUES (DATE '2026-07-27', 'x')")
        connection.execute('CREATE TABLE "odd table"(symbol VARCHAR, trade_date DATE)')
        connection.execute('INSERT INTO "odd table" VALUES (\'000100\', DATE \'2026-07-27\')')
        connection.execute("CREATE VIEW date_view AS SELECT * FROM date_rows")
    return tmp_path, database


def _row(frame: pd.DataFrame, table: str) -> pd.Series:
    return frame.loc[frame.table_name.eq(table)].iloc[0]


def test_inventory_is_schema_aware_for_date_timestamp_timestamptz_and_varchar(inventory_fixture):
    root, database = inventory_fixture
    result = inventory_database(root, database, SYMBOLS, pd.Timestamp("2026-07-27"))
    assert _row(result, "date_rows").date_filter_mode == "DATE"
    assert _row(result, "timestamp_rows").date_filter_mode == "TIMESTAMP"
    assert _row(result, "timestamptz_rows").date_filter_mode == "TIMESTAMPTZ"
    assert _row(result, "varchar_rows").date_filter_mode == "TRY_CAST_TIMESTAMP"
    assert all(_row(result, name).row_count == 1 for name in ("date_rows", "timestamp_rows", "timestamptz_rows", "varchar_rows"))
    assert not result.error.str.contains("Binder Error", regex=False).any()


def test_varchar_parse_failures_are_structured_partial_not_blocked(inventory_fixture):
    root, database = inventory_fixture
    result = inventory_database(root, database, SYMBOLS, pd.Timestamp("2026-07-27"))
    partial = _row(result, "partial_varchar")
    invalid = _row(result, "invalid_varchar")
    assert (partial.status, partial.parse_failure_count, partial.row_count) == ("PARTIAL", 1, 1)
    assert (invalid.status, invalid.parse_failure_count, invalid.row_count) == ("PARTIAL", 2, 0)
    assert "could not be parsed" in invalid.error


def test_audit_empty_static_symbol_less_view_and_special_name_contract(inventory_fixture):
    root, database = inventory_fixture
    result = inventory_database(root, database, SYMBOLS, pd.Timestamp("2026-07-27"))
    audit = _row(result, "audit_metadata")
    assert audit.date_filter_column == "created_at"
    assert audit.date_column_type == "VARCHAR"
    assert audit.date_filter_mode == "NOT_APPLICABLE"
    assert audit.status == "AVAILABLE" and audit.row_count == 1
    assert _row(result, "empty_rows").row_count == 0
    assert _row(result, "no_date").date_filter_mode == "NOT_APPLICABLE"
    assert _row(result, "no_symbol").distinct_symbol_count == 0
    assert _row(result, "date_view").table_type == "VIEW"
    assert _row(result, "odd table").status == "AVAILABLE"


def test_all_three_formal_databases_are_complete_read_only_and_unblocked():
    before = {name: _sha256(ROOT / "database" / name) for name in DATABASE_NAMES}
    inventories = [
        inventory_database(ROOT, ROOT / "database" / name, SYMBOLS, pd.Timestamp("2026-07-27"))
        for name in DATABASE_NAMES
    ]
    combined = pd.concat(inventories, ignore_index=True)
    assert [len(frame) for frame in inventories] == [20, 19, 3]
    assert len(combined) == 42
    assert combined.status.eq("AVAILABLE").all()
    lineage = _row(inventories[1], "feature_lineage")
    assert lineage.date_column_type == "VARCHAR"
    assert lineage.date_filter_mode == "NOT_APPLICABLE"
    assert lineage.parse_failure_count == 0
    assert {name: _sha256(ROOT / "database" / name) for name in DATABASE_NAMES} == before


def _copy_stage13_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "config").mkdir(parents=True)
    (root / "database").mkdir()
    shutil.copy2(ROOT / "config/stage13.yml", root / "config/stage13.yml")
    for name in DATABASE_NAMES:
        shutil.copy2(ROOT / "database" / name, root / "database" / name)
    return root


def _inject_inventory_failure(root: Path) -> None:
    database = root / "database/akshare_features_stage6.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute(
            "CREATE VIEW inventory_failure_probe AS "
            "SELECT '000100' AS symbol, CAST(error('forced inventory failure') AS DATE) AS trade_date"
        )


def _build(root: Path):
    return build_stage13_presentation(
        root=root,
        as_of_date=pd.Timestamp("2026-07-27"),
        config_path=root / "config/stage13.yml",
        input_database=root / "database/akshare_data_test_stage5_repaired.duckdb",
        reports_dir=root / "reports/stage13",
        run_id="inventory-propagation",
        symbols=["000100"],
    )


def test_real_inventory_failure_publishes_blocked_diagnostics_when_no_old_report(tmp_path):
    root = _copy_stage13_root(tmp_path)
    _inject_inventory_failure(root)
    before = {name: _sha256(root / "database" / name) for name in DATABASE_NAMES}
    manifest, exit_code = _build(root)
    quality = pd.read_csv(root / "reports/stage13/stage13_quality.csv")
    run = json.loads((root / "reports/stage13/stage13_run.json").read_text(encoding="utf-8"))
    assert exit_code != 0 and manifest["status"] == "BLOCKED"
    assert manifest["inventory_blocked_count"] == 1
    assert "inventory_failure_probe" in "|".join(manifest["blocking_reasons"])
    check = quality.loc[quality.check_name.eq("inventory_no_blocked")].iloc[0]
    assert check.status == "FAIL" and int(check.observed) == 1
    assert run["status"] == "BLOCKED" and run["inventory_blocked_count"] == 1
    assert {name: _sha256(root / "database" / name) for name in DATABASE_NAMES} == before


def test_inventory_failure_preserves_existing_published_report(tmp_path):
    root = _copy_stage13_root(tmp_path)
    reports = root / "reports/stage13"
    reports.mkdir(parents=True)
    marker = reports / "stage13_run.json"
    marker.write_text('{"run_id":"inventory-propagation"}\n', encoding="utf-8")
    before = marker.read_bytes()
    _inject_inventory_failure(root)
    manifest, exit_code = _build(root)
    assert exit_code != 0 and manifest["status"] == "BLOCKED"
    assert marker.read_bytes() == before
    assert not list((root / "reports").glob(".stage13-*"))
