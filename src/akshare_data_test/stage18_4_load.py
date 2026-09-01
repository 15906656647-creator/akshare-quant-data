"""Offline Stage 18.4 transactional DuckDB load and consistency acceptance."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import duckdb
import pandas as pd

from .stage18_3_transform import HISTORY_CATEGORIES, _json_object
from .stage18_4_config import EXPECTED_CATEGORIES, Stage184Config, load_stage18_4_config
from .stage18_audit import Stage18Blocked, _atomic_csv, _atomic_text, frozen_hashes
from .stage18_reaudit import _verify_records
from .storage.raw_store import file_record, file_sha256


DATE_COLUMNS = ("report_date", "announcement_date", "update_date")
LINEAGE_COLUMNS = (
    "symbol", "market", "data_category", "provider", "source_interface",
    "source_variant", "pit_status", "eligible_for_as_of_date_analysis",
    "source_run_id", "clean_run_id", "schema_version",
)


def _sql_path(path: Path) -> str:
    return "'" + str(path.resolve()).replace("'", "''") + "'"


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _parquet_sql(path: Path) -> str:
    return f"read_parquet({_sql_path(path)}, hive_partitioning=false)"


def _tree_fingerprint(paths: list[Path], root: Path) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for target in paths:
        if target.is_file():
            candidates = [target]
        elif target.is_dir():
            candidates = sorted(item for item in target.rglob("*") if item.is_file())
        else:
            candidates = []
        for item in candidates:
            records.append(file_record(item, root))
    records.sort(key=lambda item: item["path"])
    digest = hashlib.sha256()
    for item in records:
        digest.update(f"{item['path']}|{item['size']}|{item['sha256']}\n".encode("utf-8"))
    return {"file_count": len(records), "tree_sha256": digest.hexdigest()}


def _protected_state(root: Path, config: Stage184Config) -> dict[str, Any]:
    stage182 = [root / "data/raw/stage18" / category for category in EXPECTED_CATEGORIES]
    return {
        "stage17_raw": _tree_fingerprint([root / "data/raw/stage17"], root),
        "stage18_1_audit_raw": _tree_fingerprint([
            root / "data/raw/stage18/interface_audit",
            root / "data/raw/stage18/valuation_provider_audit",
        ], root),
        "stage18_2_raw": _tree_fingerprint(stage182, root),
        "stage18_3_clean": _tree_fingerprint([root / config.clean_run_root], root),
    }


def _count_files(path: Path) -> int:
    return sum(1 for item in path.rglob("*") if item.is_file()) if path.exists() else 0


def _verify_upstream(root: Path, config: Stage184Config) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    run_path = root / config.source_run_path
    manifest_path = root / config.source_manifest_path
    run = _json_object(run_path)
    manifest = _json_object(manifest_path)
    if (
        run.get("run_id") != config.source_run_id
        or run.get("status") != "PASS"
        or run.get("stage18_4_authorized") is not True
        or run.get("stage18_4_started") is not False
        or run.get("upstream_stage18_2_run_id") != config.source_stage18_2_run_id
        or manifest.get("run_id") != config.source_run_id
        or manifest.get("status") != "PASS"
        or manifest.get("manifest_closed_world") is not True
    ):
        raise Stage18Blocked("Stage 18.3 PASS/authorization/upstream evidence differs")
    datasets = manifest.get("clean_datasets")
    files = manifest.get("files")
    if not isinstance(datasets, list) or len(datasets) != 6 or not isinstance(files, list):
        raise Stage18Blocked("Stage 18.3 manifest is not a closed six-dataset inventory")
    manifest_tree = _verify_records(root, files, size_key="size")
    by_category: dict[str, dict[str, Any]] = {}
    for item in datasets:
        category = str(item.get("category"))
        if category not in config.expected_rows or category in by_category:
            raise Stage18Blocked("Stage 18.3 manifest category set differs")
        expected_data = root / config.clean_run_root / category / "data.parquet"
        expected_metadata = root / config.clean_run_root / category / "metadata.json"
        if root / str(item.get("data_path")) != expected_data or root / str(item.get("metadata_path")) != expected_metadata:
            raise Stage18Blocked(f"Stage 18.3 Clean path differs: {category}")
        metadata = _json_object(expected_metadata)
        if (
            int(item.get("row_count", -1)) != config.expected_rows[category]
            or item.get("data_sha256") != file_sha256(expected_data)
            or metadata.get("run_id") != config.source_run_id
            or metadata.get("category") != category
            or metadata.get("status") != "PASS"
            or metadata.get("asset_role") != "fundamental_clean"
            or metadata.get("source_stage18_2_run_id") != config.source_stage18_2_run_id
            or int(metadata.get("row_count", -1)) != config.expected_rows[category]
            or metadata.get("data_sha256") != item.get("data_sha256")
            or metadata.get("schema_hash") != item.get("schema_hash")
        ):
            raise Stage18Blocked(f"Stage 18.3 Clean metadata/hash differs: {category}")
        by_category[category] = {**item, "metadata": metadata, "data_file": expected_data}
    if tuple(by_category) != EXPECTED_CATEGORIES:
        raise Stage18Blocked("Stage 18.3 category order or coverage differs")
    if sum(config.expected_rows.values()) != config.expected_total_rows:
        raise Stage18Blocked("Stage 18.4 frozen row-count total differs")
    return ({
        "run_id": config.source_run_id,
        "run_sha256": file_sha256(run_path),
        "manifest_sha256": file_sha256(manifest_path),
        "manifest_tree_sha256": manifest_tree,
        "manifest_file_count": len(files),
        "clean_dataset_count": len(datasets),
    }, by_category)


def _describe(connection: duckdb.DuckDBPyConnection, relation: str) -> list[tuple[Any, ...]]:
    return connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()


def _difference_count(connection: duckdb.DuckDBPyConnection, left: str, right: str, columns: str = "*") -> int:
    sql = f"SELECT count(*) FROM ((SELECT {columns} FROM {left} EXCEPT ALL SELECT {columns} FROM {right}) UNION ALL (SELECT {columns} FROM {right} EXCEPT ALL SELECT {columns} FROM {left}))"
    return int(connection.execute(sql).fetchone()[0])


def _scalar(connection: duckdb.DuckDBPyConnection, sql: str) -> int:
    return int(connection.execute(sql).fetchone()[0])


def _validation_frames(
    connection: duckdb.DuckDBPyConnection,
    config: Stage184Config,
    datasets: dict[str, dict[str, Any]],
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    row_rows: list[dict[str, Any]] = []
    schema_rows: list[dict[str, Any]] = []
    lineage_rows: list[dict[str, Any]] = []
    pit_rows: list[dict[str, Any]] = []
    integrity_rows: list[dict[str, Any]] = []
    failures: list[str] = []

    for category in EXPECTED_CATEGORIES:
        table = config.tables[category]
        source = _parquet_sql(datasets[category]["data_file"])
        source_count = _scalar(connection, f"SELECT count(*) FROM {source}")
        database_count = _scalar(connection, f'SELECT count(*) FROM "{table}"')
        status = "PASS" if source_count == database_count == config.expected_rows[category] else "FAIL"
        row_rows.append({"category": category, "table_name": table, "expected_rows": config.expected_rows[category], "source_rows": source_count, "database_rows": database_count, "difference": database_count-source_count, "status": status})
        if status == "FAIL": failures.append(f"row_count:{category}")

        source_schema = _describe(connection, source)
        database_schema = _describe(connection, f'"{table}"')
        width = max(len(source_schema), len(database_schema))
        for index in range(width):
            src = source_schema[index] if index < len(source_schema) else (None, None, None)
            db = database_schema[index] if index < len(database_schema) else (None, None, None)
            ok = src[:3] == db[:3]
            schema_rows.append({"category": category, "ordinal": index+1, "source_column": src[0], "database_column": db[0], "source_type": src[1], "database_type": db[1], "source_nullable": src[2], "database_nullable": db[2], "status": "PASS" if ok else "FAIL"})
            if not ok: failures.append(f"schema:{category}:{index+1}")

        full_diff = _difference_count(connection, source, f'"{table}"')
        lineage_rows.append({"category": category, "check_name": "full_row_multiset_equality", "source_value": 0, "database_value": full_diff, "sample_size": database_count, "status": "PASS" if full_diff == 0 else "FAIL"})
        if full_diff: failures.append(f"full_row_equality:{category}")
        available = {row[0] for row in source_schema}
        selected = [column for column in LINEAGE_COLUMNS if column in available]
        if category in HISTORY_CATEGORIES:
            selected.extend(column for column in ("canonical_key", "source_dataset_id", "source_sha256", "report_date", "announcement_date", "update_date") if column in available)
            key = "canonical_key"
        else:
            selected.extend(column for column in ("snapshot_time", "analysis_as_of_date", "source_dataset_ids", "source_sha256s", "pe_source_interface", "pb_source_interface", "market_cap_source_interface") if column in available)
            key = "symbol"
        quoted = ", ".join(f'"{column}"' for column in dict.fromkeys(selected))
        key_diff = _difference_count(connection, source, f'"{table}"', quoted)
        lineage_rows.append({"category": category, "check_name": "governance_lineage_multiset_equality", "source_value": 0, "database_value": key_diff, "sample_size": database_count, "status": "PASS" if key_diff == 0 else "FAIL"})
        if key_diff: failures.append(f"lineage:{category}")
        sample = min(config.sample_rows, database_count)
        source_sample = f"(SELECT {quoted} FROM {source} ORDER BY hash(\"{key}\") LIMIT {sample})"
        db_sample = f"(SELECT {quoted} FROM \"{table}\" ORDER BY hash(\"{key}\") LIMIT {sample})"
        sample_diff = _difference_count(connection, source_sample, db_sample)
        lineage_rows.append({"category": category, "check_name": "deterministic_key_field_sample", "source_value": 0, "database_value": sample_diff, "sample_size": sample, "status": "PASS" if sample_diff == 0 else "FAIL"})
        if sample_diff: failures.append(f"sample:{category}")

        if category in HISTORY_CATEGORIES:
            src_dupes = _scalar(connection, f"SELECT count(*)-count(DISTINCT canonical_key) FROM {source}")
            db_dupes = _scalar(connection, f'SELECT count(*)-count(DISTINCT canonical_key) FROM "{table}"')
        else:
            src_dupes = _scalar(connection, f"SELECT count(*)-count(DISTINCT symbol) FROM {source}")
            db_dupes = _scalar(connection, f'SELECT count(*)-count(DISTINCT symbol) FROM "{table}"')
        ok = src_dupes == db_dupes == 0
        integrity_rows.append({"check_name": f"unique_key:{category}", "expected": 0, "observed": db_dupes, "source_observed": src_dupes, "status": "PASS" if ok else "FAIL"})
        if not ok: failures.append(f"unique_key:{category}")

        for column in DATE_COLUMNS:
            if column not in available:
                continue
            src_null = _scalar(connection, f'SELECT count(*) FILTER (WHERE "{column}" IS NULL) FROM {source}')
            db_null = _scalar(connection, f'SELECT count(*) FILTER (WHERE "{column}" IS NULL) FROM "{table}"')
            ok = src_null == db_null
            pit_rows.append({"category": category, "check_name": f"null_count:{column}", "dimension": column, "source_count": src_null, "database_count": db_null, "status": "PASS" if ok else "FAIL"})
            if not ok: failures.append(f"date_null:{category}:{column}")
        groups = connection.execute(f"SELECT pit_status, eligible_for_as_of_date_analysis, count(*) FROM {source} GROUP BY ALL ORDER BY ALL").fetchall()
        db_groups = connection.execute(f'SELECT pit_status, eligible_for_as_of_date_analysis, count(*) FROM "{table}" GROUP BY ALL ORDER BY ALL').fetchall()
        all_groups = sorted(set(groups) | set(db_groups), key=str)
        src_map = {(row[0], row[1]): int(row[2]) for row in groups}
        db_map = {(row[0], row[1]): int(row[2]) for row in db_groups}
        for pit_status, eligible, *_ in all_groups:
            src_value = src_map.get((pit_status, eligible), 0)
            db_value = db_map.get((pit_status, eligible), 0)
            ok = src_value == db_value
            pit_rows.append({"category": category, "check_name": "pit_status_and_eligibility", "dimension": f"{pit_status}|{eligible}", "source_count": src_value, "database_count": db_value, "status": "PASS" if ok else "FAIL"})
            if not ok: failures.append(f"pit:{category}:{pit_status}:{eligible}")

    history = sum(row["database_rows"] for row in row_rows if row["category"] in HISTORY_CATEGORIES)
    total = sum(row["database_rows"] for row in row_rows)
    for name, expected, observed in (("history_row_total", config.expected_history_rows, history), ("all_fact_row_total", config.expected_total_rows, total)):
        ok = expected == observed
        integrity_rows.append({"check_name": name, "expected": expected, "observed": observed, "source_observed": expected, "status": "PASS" if ok else "FAIL"})
        if not ok: failures.append(name)

    unions = " UNION ALL ".join(f'SELECT symbol, market FROM "{config.tables[c]}"' for c in EXPECTED_CATEGORIES)
    scope = connection.execute(f"SELECT count(*), count(*) FILTER (WHERE market='A'), count(*) FILTER (WHERE market='HK') FROM (SELECT DISTINCT symbol, market FROM ({unions}))").fetchone()
    for name, expected, observed in (("security_count", 23, int(scope[0])), ("a_share_count", 16, int(scope[1])), ("h_share_count", 7, int(scope[2]))):
        ok = expected == observed
        integrity_rows.append({"check_name": name, "expected": expected, "observed": observed, "source_observed": expected, "status": "PASS" if ok else "FAIL"})
        if not ok: failures.append(name)
    valuation = config.tables["valuation_snapshot"]
    valuation_false = _scalar(connection, f'SELECT count(*) FROM "{valuation}" WHERE eligible_for_as_of_date_analysis IS FALSE')
    valuation_other = _scalar(connection, f'SELECT count(*) FROM "{valuation}" WHERE eligible_for_as_of_date_analysis IS DISTINCT FROM FALSE')
    ok = valuation_false == 23 and valuation_other == 0
    integrity_rows.append({"check_name": "valuation_eligibility_false", "expected": 23, "observed": valuation_false, "source_observed": 23, "status": "PASS" if ok else "FAIL"})
    if not ok: failures.append("valuation_eligibility")

    query_checks = {
        "query_filter_symbol": f'SELECT count(*) FROM "{config.tables["financial_abstract"]}" WHERE symbol=(SELECT min(symbol) FROM "{config.tables["financial_abstract"]}")',
        "query_filter_market": f'SELECT count(*) FROM "{config.tables["financial_indicator"]}" WHERE market=\'A\'',
        "query_filter_report_date": f'SELECT count(*) FROM "{config.tables["balance_sheet"]}" WHERE report_date IS NOT NULL',
        "query_filter_pit_status": f'SELECT count(*) FROM "{config.tables["income_statement"]}" WHERE pit_status IS NOT NULL',
        "query_category_table": f'SELECT count(*) FROM "{config.tables["cash_flow_statement"]}" WHERE data_category=\'cash_flow_statement\'',
    }
    for name, sql in query_checks.items():
        observed = _scalar(connection, sql)
        ok = observed > 0
        integrity_rows.append({"check_name": name, "expected": ">0", "observed": observed, "source_observed": "n/a", "status": "PASS" if ok else "FAIL"})
        if not ok: failures.append(name)
    return tuple(pd.DataFrame(rows) for rows in (row_rows, schema_rows, lineage_rows, pit_rows, integrity_rows)) + (failures,)


def run_stage18_4_load(
    *, root: str | Path | None = None, config_path: str | Path = "config/stage18_4.yml",
    as_of_date: date, upstream_run_id: str | None = None, run_id: str | None = None,
    validate_only: bool = False, dry_run: bool = False,
    clock: Callable[[], datetime] | None = None,
) -> tuple[dict[str, Any], int]:
    project_root = Path(root or Path.cwd()).resolve()
    config_file = Path(config_path)
    if not config_file.is_absolute(): config_file = project_root / config_file
    config = load_stage18_4_config(config_file)
    if as_of_date != config.as_of_date:
        raise Stage18Blocked("Stage 18.4 as-of date differs from frozen configuration")
    if upstream_run_id is not None and upstream_run_id != config.source_run_id:
        raise Stage18Blocked("Stage 18.4 upstream run id differs from the sole formal Stage 18.3 run")
    stage0_before = frozen_hashes(project_root)
    upstream_before, datasets = _verify_upstream(project_root, config)
    protected_before = _protected_state(project_root, config)
    if validate_only or dry_run:
        return ({"stage": 18, "substage": "18.4", "status": "VALIDATED" if validate_only else "DRY_RUN", "upstream": upstream_before, "database_writes": 0}, 0)

    active_run = run_id or str(uuid.uuid4())
    try:
        uuid.UUID(active_run)
    except ValueError as exc:
        raise Stage18Blocked("Stage 18.4 run_id must be a UUID") from exc
    report_dir = project_root / config.reports_root / active_run
    database_dir = project_root / config.database_root / f"run_id={active_run}"
    database_path = database_dir / config.database_filename
    if report_dir.exists() or database_dir.exists():
        raise Stage18Blocked("Stage 18.4 run/report or database path already exists; append-only policy blocks overwrite")
    now = clock or (lambda: datetime.now(timezone.utc))
    started_at = now().astimezone(timezone.utc).isoformat()
    report_dir.mkdir(parents=True, exist_ok=False)
    database_dir.mkdir(parents=True, exist_ok=False)
    frames: tuple[pd.DataFrame, ...] | None = None
    try:
        with duckdb.connect(str(database_path)) as connection:
            connection.execute("BEGIN TRANSACTION")
            try:
                for category in EXPECTED_CATEGORIES:
                    table = config.tables[category]
                    source = _parquet_sql(datasets[category]["data_file"])
                    connection.execute(f'CREATE TABLE "{table}" AS SELECT * FROM {source}')
                frames = _validation_frames(connection, config, datasets)
                failures = frames[-1]
                if failures:
                    raise Stage18Blocked("Stage 18.4 transactional validation failed: " + ", ".join(failures[:10]))
                connection.execute("COMMIT")
            except Exception:
                connection.execute("ROLLBACK")
                raise
            connection.execute("CHECKPOINT")
        if frames is None:
            raise Stage18Blocked("Stage 18.4 validation frames were not produced")
        row_frame, schema_frame, lineage_frame, pit_frame, integrity_frame, failures = frames
        with duckdb.connect(str(database_path), read_only=True) as connection:
            tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
            expected_tables = set(config.tables.values())
            reopen_ok = tables == expected_tables and _scalar(connection, f'SELECT count(*) FROM "{config.tables["valuation_snapshot"]}"') == 23
        integrity_frame = pd.concat([integrity_frame, pd.DataFrame([{"check_name": "read_only_reopen_and_table_set", "expected": 6, "observed": len(tables), "source_observed": 6, "status": "PASS" if reopen_ok else "FAIL"}])], ignore_index=True)
        if not reopen_ok: failures.append("read_only_reopen")
        residuals = sorted(item.name for item in database_dir.iterdir() if item.name.endswith((".tmp", ".wal")))
        integrity_frame = pd.concat([integrity_frame, pd.DataFrame([{"check_name": "temporary_or_wal_residuals", "expected": 0, "observed": len(residuals), "source_observed": 0, "status": "PASS" if not residuals else "FAIL"}])], ignore_index=True)
        if residuals: failures.append("database_residuals")

        for name, frame in (("table_row_counts.csv", row_frame), ("schema_validation.csv", schema_frame), ("lineage_validation.csv", lineage_frame), ("pit_validation.csv", pit_frame), ("database_integrity.csv", integrity_frame)):
            _atomic_csv(report_dir / name, frame, must_not_exist=True)
        database_sha = file_sha256(database_path)
        database_size = database_path.stat().st_size
        stage0_after = frozen_hashes(project_root)
        upstream_after, _ = _verify_upstream(project_root, config)
        protected_after = _protected_state(project_root, config)
        feature_count = _count_files(project_root / "data/features/stage18")
        stage19_count = _count_files(project_root / "data/raw/stage19") + _count_files(project_root / "reports/stage19")
        blockers = list(failures)
        if stage0_before != stage0_after: blockers.append("stage0_frozen_hashes_changed")
        if upstream_before != upstream_after: blockers.append("stage18_3_upstream_evidence_changed")
        if protected_before != protected_after: blockers.append("protected_upstream_assets_changed")
        if feature_count: blockers.append("stage18_feature_assets_exist")
        if stage19_count: blockers.append("stage19_assets_exist")
        status = "PASS" if not blockers else "BLOCKED"
        finished_at = now().astimezone(timezone.utc).isoformat()
        run_report = {
            "stage": 18, "substage": "18.4", "run_id": active_run,
            "status": status, "stage18_4_status": status,
            "started_at": started_at, "finished_at": finished_at,
            "analysis_as_of_date": config.as_of_date.isoformat(),
            "upstream_stage18_3_run_id": config.source_run_id,
            "upstream_stage18_2_run_id": config.source_stage18_2_run_id,
            "database_path": _display_path(database_path, project_root),
            "database_size_bytes": database_size, "database_sha256": database_sha,
            "table_row_counts": {row["category"]: int(row["database_rows"]) for row in row_frame.to_dict("records")},
            "history_row_count": config.expected_history_rows, "total_row_count": config.expected_total_rows,
            "table_count": 6, "security_count": 23,
            "canonical_key_duplicate_count": int(sum(row["observed"] for row in integrity_frame.to_dict("records") if str(row["check_name"]).startswith("unique_key:"))),
            "schema_validation_fail_count": int((schema_frame["status"] == "FAIL").sum()),
            "lineage_validation_fail_count": int((lineage_frame["status"] == "FAIL").sum()),
            "pit_validation_fail_count": int((pit_frame["status"] == "FAIL").sum()),
            "valuation_ineligible_count": 23,
            "stage0_hashes_before": stage0_before, "stage0_hashes_after": stage0_after, "stage0_hashes_unchanged": stage0_before == stage0_after,
            "protected_assets_before": protected_before, "protected_assets_after": protected_after, "protected_assets_unchanged": protected_before == protected_after,
            "upstream_evidence_before": upstream_before, "upstream_evidence_after": upstream_after, "upstream_evidence_unchanged": upstream_before == upstream_after,
            "feature_file_count": feature_count, "stage19_asset_count": stage19_count,
            "tmp_wal_residual_count": len(residuals), "blockers": blockers,
            "stage18_5_authorized": status == "PASS", "stage18_5_started": False,
            "known_test_debt": {"node_id": "tests/test_stage8_manual_import.py::test_default_cli_fails_closed_without_real_dataset", "signature": "expected returncode 1, observed returncode 0"},
        }
        run_path = report_dir / "stage18_4_run.json"
        _atomic_text(run_path, json.dumps(run_report, ensure_ascii=False, indent=2, default=str) + "\n", must_not_exist=True)
        artifact_paths = [database_path, config_file, run_path] + [report_dir / name for name in ("table_row_counts.csv", "schema_validation.csv", "lineage_validation.csv", "pit_validation.csv", "database_integrity.csv")]
        for doc in (project_root / "docs/stage18_4_implementation.md", project_root / "docs/stage18_4_acceptance.md"):
            if doc.is_file(): artifact_paths.append(doc)
        records = [file_record(path, project_root) for path in artifact_paths]
        manifest = {
            "stage": 18, "substage": "18.4", "run_id": active_run, "status": status,
            "upstream_stage18_3_run_id": config.source_run_id,
            "database": {"path": _display_path(database_path, project_root), "size": database_size, "sha256": database_sha},
            "tables": [{"category": row["category"], "table_name": row["table_name"], "row_count": int(row["database_rows"])} for row in row_frame.to_dict("records")],
            "files": records, "manifest_closed_world": status == "PASS",
        }
        manifest_path = report_dir / "stage18_4_manifest.json"
        _atomic_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", must_not_exist=True)
        tree_hash = _verify_records(project_root, records, size_key="size")
        if file_sha256(database_path) != database_sha:
            raise Stage18Blocked("Stage 18.4 database hash changed after close")
        run_report["manifest_path"] = _display_path(manifest_path, project_root)
        run_report["manifest_file_count"] = len(records)
        run_report["manifest_tree_sha256"] = tree_hash
        return run_report, 0 if status == "PASS" else 1
    except Exception as exc:
        interrupted = {"stage": 18, "substage": "18.4", "run_id": active_run, "status": "BLOCKED", "started_at": started_at, "failed_at": now().astimezone(timezone.utc).isoformat(), "blocker": str(exc), "database_path": _display_path(database_path, project_root), "stage18_5_authorized": False}
        path = report_dir / "stage18_4_interrupted.json"
        if not path.exists(): _atomic_text(path, json.dumps(interrupted, ensure_ascii=False, indent=2) + "\n", must_not_exist=True)
        raise
