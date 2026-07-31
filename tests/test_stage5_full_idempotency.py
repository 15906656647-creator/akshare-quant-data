from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from akshare_data_test.stage5_repair import (
    run_stage5_idempotency_repair,
)

ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_complete_nonempty_stage5_replay_is_fully_idempotent(tmp_path):
    formal_database = ROOT / "database/akshare_data_test.duckdb"
    parent_manifest = (
        ROOT
        / "reports/evidence/stage5"
        / "31635b34-d1ee-46d4-9c0f-32ae3f30d567"
        / "manifest.json"
    )
    database_before = _sha256(formal_database)
    manifest_before = _sha256(parent_manifest)
    feature_files_before = {
        path: _sha256(path)
        for path in (ROOT / "data/feature").rglob("*")
        if path.is_file() and path.name != ".gitkeep"
    }
    output = tmp_path / "reports"
    report, exit_code = run_stage5_idempotency_repair(
        root=ROOT,
        as_of_date=date(2026, 7, 27),
        formal_database=formal_database,
        output_directory=output,
        document_path=tmp_path / "stage5_idempotency_repair.md",
        appendix_path=tmp_path / "manifest.after_repair.json",
    )
    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["complete_inputs"] == {
        "clean_datasets": 10,
        "data_quality_issue": 47,
        "field_mapping_registry": 1024,
        "source_file_manifest": 130,
        "data_lineage": 130,
    }
    assert report["all_twelve_tables_unchanged"] is True
    assert report["transaction"]["status"] == "PASS"
    assert report["conflict_tests"]["status"] == "PASS"
    first = report["first_load"]["snapshot"]
    second = report["second_load"]["snapshot"]
    assert len(first) == len(second) == 12
    assert first == second
    assert first["data_quality_issue"]["row_count"] == 47
    assert first["field_mapping_registry"]["row_count"] == 1024
    assert _sha256(formal_database) == database_before
    assert _sha256(parent_manifest) == manifest_before
    feature_files_after = {
        path: _sha256(path)
        for path in (ROOT / "data/feature").rglob("*")
        if path.is_file() and path.name != ".gitkeep"
    }
    assert feature_files_after == feature_files_before
    assert report["scope_boundary"]["feature_files_unchanged"] is True
