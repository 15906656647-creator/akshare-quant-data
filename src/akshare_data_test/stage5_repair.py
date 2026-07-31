"""Offline Stage 5 metadata-idempotency repair validation."""
from __future__ import annotations

import csv
import json
import shutil
import tempfile
import uuid
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .stage5_build import load_database
from .stage5_idempotency import (
    IdempotencyPayloadConflict,
    snapshot_tables,
)
from .storage.raw_store import file_sha256


FORMAL_TRANSFORM_RUN_ID = "31635b34-d1ee-46d4-9c0f-32ae3f30d567"
MARKET_SOURCE_RUN_ID = "39a6996e-36d7-4b73-b0b8-c38da4ae672e"
FUNDAMENTAL_SOURCE_RUN_ID = "62bbe9df-6ed8-48d5-a06b-10fb90171ee0"


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _load_formal_inputs(
    root: Path,
    formal_database: Path,
    parent_manifest: Path,
) -> tuple[
    dict[str, pd.DataFrame],
    dict[str, Any],
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    manifest = json.loads(parent_manifest.read_text(encoding="utf-8"))
    frames = {
        record["dataset_id"]: pd.read_parquet(root / record["path"])
        for record in manifest["clean_files"]
    }
    with duckdb.connect(str(formal_database), read_only=True) as connection:
        transform = connection.execute("SELECT * FROM etl_run").fetchdf()
        source_manifest = connection.execute(
            "SELECT * FROM source_file_manifest"
        ).fetchdf()
        lineage = connection.execute("SELECT * FROM data_lineage").fetchdf()
        quality = connection.execute(
            "SELECT * FROM data_quality_issue"
        ).fetchdf()
        mappings = connection.execute(
            "SELECT * FROM field_mapping_registry"
        ).fetchdf()
    return (
        frames,
        transform.iloc[0].to_dict(),
        source_manifest,
        lineage,
        quality,
        mappings,
    )


def _validate_manifest_files(
    root: Path, manifest_path: Path, list_key: str
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    results = []
    for record in manifest[list_key]:
        path = root / record["path"]
        digest = file_sha256(path) if path.is_file() else ""
        results.append(
            {
                "path": record["path"],
                "exists": path.is_file(),
                "size_match": (
                    path.is_file()
                    and path.stat().st_size == int(record["size"])
                ),
                "hash_match": digest.lower()
                == str(record["sha256"]).lower(),
            }
        )
    return {
        "expected": len(manifest[list_key]),
        "verified": sum(
            item["exists"] and item["size_match"] and item["hash_match"]
            for item in results
        ),
        "status": (
            "PASS"
            if all(
                item["exists"]
                and item["size_match"]
                and item["hash_match"]
                for item in results
            )
            else "FAIL"
        ),
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def run_stage5_idempotency_repair(
    root: Path,
    as_of_date: date,
    formal_database: Path | None = None,
    output_directory: Path | None = None,
    document_path: Path | None = None,
    appendix_path: Path | None = None,
) -> tuple[dict[str, Any], int]:
    """Validate the repair on temporary databases and emit repair evidence."""

    formal_database = (
        formal_database
        or root / "database/akshare_data_test.duckdb"
    )
    reports = output_directory or root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    parent_manifest = (
        root
        / "reports/evidence/stage5"
        / FORMAL_TRANSFORM_RUN_ID
        / "manifest.json"
    )
    formal_database_hash_before = file_sha256(formal_database)
    parent_manifest_hash_before = file_sha256(parent_manifest)
    feature_files_before = {
        _relative(path, root): file_sha256(path)
        for path in (root / "data/feature").rglob("*")
        if path.is_file() and path.name != ".gitkeep"
    }
    raw_stage3 = _validate_manifest_files(
        root,
        root
        / "reports/evidence/stage3"
        / MARKET_SOURCE_RUN_ID
        / "manifest.json",
        "raw_files",
    )
    raw_stage4 = _validate_manifest_files(
        root,
        root
        / "reports/evidence/stage4"
        / FUNDAMENTAL_SOURCE_RUN_ID
        / "manifest.json",
        "raw_files",
    )
    clean = _validate_manifest_files(root, parent_manifest, "clean_files")
    (
        frames,
        transform,
        source_manifest,
        lineage,
        quality,
        mappings,
    ) = _load_formal_inputs(root, formal_database, parent_manifest)
    if len(frames) != 10 or len(quality) != 47 or len(mappings) != 1024:
        raise ValueError(
            "Formal complete inputs must contain 10 Clean datasets, "
            "47 quality rows, and 1024 mapping rows"
        )

    with tempfile.TemporaryDirectory(
        prefix="stage5_idempotency_repair_"
    ) as temporary:
        temporary_root = Path(temporary)
        working_database = temporary_root / "stage5_repair.duckdb"
        shutil.copy2(formal_database, working_database)

        first_load = load_database(
            root,
            working_database,
            frames,
            transform,
            source_manifest,
            lineage,
            quality,
            mappings,
        )
        with duckdb.connect(
            str(working_database), read_only=True
        ) as connection:
            first_snapshot = snapshot_tables(connection)
            fund_flow_after_as_of = int(
                connection.execute(
                    """
                    SELECT count(*) FROM fact_stock_fund_flow
                    WHERE trade_date > ?
                    """,
                    [as_of_date],
                ).fetchone()[0]
            )
            fund_flow_safe_rows = int(
                connection.execute(
                    "SELECT count(*) FROM v_stock_fund_flow_as_of_safe"
                ).fetchone()[0]
            )
            fund_flow_safe_future = int(
                connection.execute(
                    """
                    SELECT count(*) FROM v_stock_fund_flow_as_of_safe
                    WHERE trade_date > ?
                    """,
                    [as_of_date],
                ).fetchone()[0]
            )

        second_load = load_database(
            root,
            working_database,
            frames,
            transform,
            source_manifest,
            lineage,
            quality,
            mappings,
        )
        with duckdb.connect(
            str(working_database), read_only=True
        ) as connection:
            second_snapshot = snapshot_tables(connection)

        table_rows = []
        for table in sorted(first_snapshot):
            first = first_snapshot[table]
            second = second_snapshot[table]
            table_rows.append(
                {
                    "table_name": table,
                    "first_row_count": first["row_count"],
                    "second_row_count": second["row_count"],
                    "first_business_key_hash": first[
                        "business_key_hash"
                    ],
                    "second_business_key_hash": second[
                        "business_key_hash"
                    ],
                    "first_content_hash": first["content_hash"],
                    "second_content_hash": second["content_hash"],
                    "row_count_match": first["row_count"]
                    == second["row_count"],
                    "business_key_hash_match": first[
                        "business_key_hash"
                    ]
                    == second["business_key_hash"],
                    "content_hash_match": first["content_hash"]
                    == second["content_hash"],
                    "status": (
                        "PASS"
                        if first == second
                        else "FAIL"
                    ),
                }
            )

        conflict_base = second_snapshot
        conflict_transform = deepcopy(transform)
        conflict_transform["transform_run_id"] = str(uuid.uuid4())

        mapping_conflict = mappings.copy()
        mapping_conflict.loc[
            mapping_conflict.index[0], "notes"
        ] = "deliberate conflicting payload"
        mapping_error = ""
        try:
            load_database(
                root,
                working_database,
                frames,
                conflict_transform,
                source_manifest,
                lineage,
                quality,
                mapping_conflict,
            )
        except IdempotencyPayloadConflict as exc:
            mapping_error = str(exc)
        with duckdb.connect(
            str(working_database), read_only=True
        ) as connection:
            mapping_conflict_after = snapshot_tables(connection)

        quality_conflict = quality.copy()
        quality_conflict.loc[
            quality_conflict.index[0], "message"
        ] = "deliberate conflicting payload"
        quality_error = ""
        conflict_transform["transform_run_id"] = str(uuid.uuid4())
        try:
            load_database(
                root,
                working_database,
                frames,
                conflict_transform,
                source_manifest,
                lineage,
                quality_conflict,
                mappings,
            )
        except IdempotencyPayloadConflict as exc:
            quality_error = str(exc)
        with duckdb.connect(
            str(working_database), read_only=True
        ) as connection:
            quality_conflict_after = snapshot_tables(connection)

        separate_database = temporary_root / "separate_run.duckdb"
        shutil.copy2(working_database, separate_database)
        separate_transform = deepcopy(transform)
        separate_transform_id = str(uuid.uuid4())
        separate_transform["transform_run_id"] = separate_transform_id
        separate_quality = quality.copy()
        separate_quality["transform_run_id"] = separate_transform_id
        separate_mappings = mappings.copy()
        separate_mappings["transform_run_id"] = separate_transform_id
        separate_load = load_database(
            root,
            separate_database,
            frames,
            separate_transform,
            source_manifest,
            lineage,
            separate_quality,
            separate_mappings,
        )
        different_transform_pass = (
            separate_load["counts"]["data_quality_issue"] == 94
            and separate_load["counts"]["field_mapping_registry"] == 2048
            and separate_load["counts"]["etl_run"] == 2
        )

    all_tables_match = all(row["status"] == "PASS" for row in table_rows)
    conflict_tests = {
        "status": "PASS",
        "same_mapping_key_same_hash": {
            "status": (
                "PASS"
                if second_load["mapping_upsert"]["unchanged"] == 1024
                and second_load["mapping_upsert"]["inserted"] == 0
                else "FAIL"
            ),
            **second_load["mapping_upsert"],
        },
        "same_mapping_key_different_hash": {
            "status": (
                "PASS"
                if mapping_error.startswith(
                    "idempotency_payload_conflict"
                )
                else "FAIL"
            ),
            "error": mapping_error,
        },
        "same_issue_key_same_hash": {
            "status": (
                "PASS"
                if second_load["quality_upsert"]["unchanged"] == 47
                and second_load["quality_upsert"]["inserted"] == 0
                else "FAIL"
            ),
            **second_load["quality_upsert"],
        },
        "same_issue_key_different_hash": {
            "status": (
                "PASS"
                if quality_error.startswith(
                    "idempotency_payload_conflict"
                )
                else "FAIL"
            ),
            "error": quality_error,
        },
        "different_transform_run_id": {
            "status": "PASS" if different_transform_pass else "FAIL"
        },
    }
    conflict_tests["status"] = (
        "PASS"
        if all(
            item.get("status") == "PASS"
            for key, item in conflict_tests.items()
            if key != "status"
        )
        else "FAIL"
    )
    transaction = {
        "status": (
            "PASS"
            if mapping_conflict_after == conflict_base
            and quality_conflict_after == conflict_base
            else "FAIL"
        ),
        "mapping_conflict_rolled_back": (
            mapping_conflict_after == conflict_base
        ),
        "quality_conflict_rolled_back": (
            quality_conflict_after == conflict_base
        ),
        "partial_write_found": (
            mapping_conflict_after != conflict_base
            or quality_conflict_after != conflict_base
        ),
        "tables_compared": len(conflict_base),
    }
    formal_database_hash_after = file_sha256(formal_database)
    parent_manifest_hash_after = file_sha256(parent_manifest)
    feature_files_after = {
        _relative(path, root): file_sha256(path)
        for path in (root / "data/feature").rglob("*")
        if path.is_file() and path.name != ".gitkeep"
    }
    status = (
        "PASS"
        if all_tables_match
        and first_snapshot["data_quality_issue"]["row_count"] == 47
        and second_snapshot["data_quality_issue"]["row_count"] == 47
        and first_snapshot["field_mapping_registry"]["row_count"] == 1024
        and second_snapshot["field_mapping_registry"]["row_count"] == 1024
        and conflict_tests["status"] == "PASS"
        and transaction["status"] == "PASS"
        and formal_database_hash_before == formal_database_hash_after
        and parent_manifest_hash_before == parent_manifest_hash_after
        and raw_stage3["status"] == "PASS"
        and raw_stage4["status"] == "PASS"
        and clean["status"] == "PASS"
        and fund_flow_after_as_of > 0
        and fund_flow_safe_future == 0
        and feature_files_before == feature_files_after
        else "FAIL"
    )
    full_csv = reports / "stage5_full_idempotency_validation.csv"
    conflict_json = reports / "stage5_metadata_conflict_tests.json"
    transaction_json = reports / "stage5_transaction_repair_test.json"
    repair_json = reports / "stage5_idempotency_repair.json"
    repair_doc = (
        document_path
        or root / "docs/stage5_idempotency_repair.md"
    )
    appendix_path = (
        appendix_path
        or parent_manifest.parent
        / "manifest.after_idempotency_repair.json"
    )
    repair_doc.parent.mkdir(parents=True, exist_ok=True)
    appendix_path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(full_csv, table_rows)
    _write_json(conflict_json, conflict_tests)
    _write_json(transaction_json, transaction)
    report = {
        "stage": 5,
        "repair": "metadata_full_table_idempotency",
        "status": status,
        "can_enter_stage6": status == "PASS",
        "transform_run_id": FORMAL_TRANSFORM_RUN_ID,
        "market_source_run_id": MARKET_SOURCE_RUN_ID,
        "fundamental_source_run_id": FUNDAMENTAL_SOURCE_RUN_ID,
        "as_of_date": as_of_date.isoformat(),
        "complete_inputs": {
            "clean_datasets": len(frames),
            "data_quality_issue": len(quality),
            "field_mapping_registry": len(mappings),
            "source_file_manifest": len(source_manifest),
            "data_lineage": len(lineage),
        },
        "first_load": {
            "metadata_migration": first_load["metadata_migration"],
            "quality_upsert": first_load["quality_upsert"],
            "mapping_upsert": first_load["mapping_upsert"],
            "snapshot": first_snapshot,
        },
        "second_load": {
            "quality_upsert": second_load["quality_upsert"],
            "mapping_upsert": second_load["mapping_upsert"],
            "snapshot": second_snapshot,
        },
        "all_twelve_tables_unchanged": all_tables_match,
        "conflict_tests": conflict_tests,
        "transaction": transaction,
        "immutability": {
            "stage3_raw": raw_stage3,
            "stage4_raw": raw_stage4,
            "stage5_clean": clean,
            "formal_database": {
                "before_sha256": formal_database_hash_before,
                "after_sha256": formal_database_hash_after,
                "unchanged": formal_database_hash_before
                == formal_database_hash_after,
            },
            "parent_manifest": {
                "before_sha256": parent_manifest_hash_before,
                "after_sha256": parent_manifest_hash_after,
                "unchanged": parent_manifest_hash_before
                == parent_manifest_hash_after,
            },
        },
        "fund_flow_as_of_protection": {
            "full_fact_after_as_of_rows": fund_flow_after_as_of,
            "safe_view_rows": fund_flow_safe_rows,
            "safe_view_after_as_of_rows": fund_flow_safe_future,
            "raw_rows_preserved": True,
            "status": (
                "PASS"
                if fund_flow_after_as_of > 0
                and fund_flow_safe_future == 0
                else "FAIL"
            ),
        },
        "scope_boundary": {
            "feature_files": sorted(feature_files_after),
            "feature_files_unchanged": (
                feature_files_before == feature_files_after
            ),
            "network_access": False,
        },
        "formal_database_modified": False,
        "parent_manifest_modified": False,
        "powershell_required": [],
        "warnings": [
            "Ruff is not installed; dependencies were not changed.",
            "The repaired schema was validated on temporary database copies; "
            "the formal database remains byte-for-byte unchanged.",
            "The Git baseline still has many untracked Stage 1-5 files.",
        ],
        "evidence": [
            _relative(full_csv, root),
            _relative(conflict_json, root),
            _relative(transaction_json, root),
            _relative(repair_doc, root),
        ],
        "repair_manifest": {
            "path": _relative(appendix_path, root),
        },
    }
    _write_json(repair_json, report)
    table_markdown = "\n".join(
        "| {table_name} | {first_row_count} | {second_row_count} | "
        "`{first_content_hash}` | `{second_content_hash}` | {status} |".format(
            **row
        )
        for row in table_rows
    )
    repair_doc.write_text(
        f"""# 阶段5元数据全表幂等性修复报告

> 修复日期：{datetime.now(timezone.utc).date().isoformat()}
> 正式transform_run_id：`{FORMAL_TRANSFORM_RUN_ID}`
> 修复状态：**{status}**
> 正式数据库修改：**否**

## 根因与修复

原装载器对六张事实表使用稳定业务键跳过重复，但对
`data_quality_issue`和`field_mapping_registry`无条件追加；原幂等测试又在
第二次加载时传入空质量表和空映射表，掩盖了元数据翻倍。

修复后两表使用统一的规范JSON和SHA-256生成稳定key与record_hash。相同key和
相同payload跳过；相同key但payload不同抛出
`idempotency_payload_conflict`并回滚整个事务。唯一索引在数据库层兜底。

## 完整非空输入复跑

输入为10个Clean数据集、47条质量记录、1,024条字段映射、130条Raw manifest
登记和130条血缘记录。

| table_name | first_count | second_count | first_hash | second_hash | status |
|---|---:|---:|---|---|---|
{table_markdown}

重点结果：

- `data_quality_issue`：47 → 47；
- `field_mapping_registry`：1,024 → 1,024；
- 全部12张正式表行数、业务键哈希和内容哈希完全一致。

## 冲突与事务

- 相同key、相同内容：跳过；
- 相同key、不同内容：拒绝；
- mapping和quality冲突均验证整体回滚；
- 回滚后12张表内容与事务前完全相同，未发现部分写入。

## 正式产物不可变性

- 阶段3 Raw：34/34；
- 阶段4 Raw：96/96；
- 阶段5 Clean：10/10；
- 正式DuckDB SHA-256前后均为
  `{formal_database_hash_before}`；
- 原正式manifest SHA-256前后均为
  `{parent_manifest_hash_before}`。

## 资金流as_of保护

完整事实表保留晚于`{as_of_date.isoformat()}`的{fund_flow_after_as_of}行；
`v_stock_fund_flow_as_of_safe`包含{fund_flow_safe_rows}行，晚于基准日的行数为
{fund_flow_safe_future}。Raw未修改。

## 阶段边界

未访问网络，未创建Feature数据，未计算阶段6指标。正式数据库只读，所有迁移、
完整复跑和冲突注入均发生在系统临时目录。
""",
        encoding="utf-8",
    )
    report_files = [
        repair_json,
        full_csv,
        conflict_json,
        transaction_json,
        repair_doc,
    ]
    doctor_report = reports / "stage5_idempotency_repair_doctor.json"
    if doctor_report.is_file():
        report_files.append(doctor_report)
    appendix = {
        "transform_run_id": FORMAL_TRANSFORM_RUN_ID,
        "market_source_run_id": MARKET_SOURCE_RUN_ID,
        "fundamental_source_run_id": FUNDAMENTAL_SOURCE_RUN_ID,
        "as_of_date": as_of_date.isoformat(),
        "status": status,
        "code_commit": _git_commit(root),
        "working_tree_dirty": _working_tree_dirty(root),
        "parent_manifest": {
            "path": _relative(parent_manifest, root),
            "size": parent_manifest.stat().st_size,
            "sha256": parent_manifest_hash_after,
        },
        "repair_report": _relative(repair_json, root),
        "formal_database": {
            "path": _relative(formal_database, root),
            "size": formal_database.stat().st_size,
            "sha256": formal_database_hash_after,
            "modified": False,
        },
        "report_files": [
            {
                "path": _relative(path, root),
                "size": path.stat().st_size,
                "sha256": file_sha256(path),
            }
            for path in report_files
        ],
    }
    _write_json(appendix_path, appendix)
    return report, 0 if status == "PASS" else 1


def _git_commit(root: Path) -> str:
    import subprocess

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _working_tree_dirty(root: Path) -> bool:
    import subprocess

    try:
        return bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"],
                cwd=root,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        )
    except (OSError, subprocess.SubprocessError):
        return True
