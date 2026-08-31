from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml

from akshare_data_test.config import load_universe
from akshare_data_test.limit_rules import (
    resolve_limit_rule,
    resolve_security_status,
    validate_rule_intervals,
    validate_status_intervals,
)
from akshare_data_test.stage8_authoritative import (
    build_rules_manifest,
    build_status_manifest,
)
from akshare_data_test.stage8_build import load_stage8_config
from akshare_data_test.stage8_manual import (
    RULES_REQUIRED_COLUMNS,
    STATUS_REQUIRED_COLUMNS,
    build_merged_payload,
    validate_combined_datasets,
    validate_manual_dataset,
)


ROOT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 7, 27)
START = date(2025, 7, 27)
END = date(2026, 7, 27)


def _run_id() -> str:
    return str(uuid.uuid4())


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _write_source(dataset_dir: Path, name: str, content: bytes) -> str:
    sources = dataset_dir / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    (sources / name).write_bytes(content)
    return _sha(content)


def _manifest(
    *,
    kind: str,
    dataset_dir: Path,
    sha: str,
    files: list[str],
    as_of: str = "2026-07-27",
    start: str = "2025-07-27",
    end: str = "2026-07-27",
    grade: str = "A",
    review_status: str = "approved",
    review_mode: str = "dual_review",
    reviewer: str = "张三/李四（双人复核）",
    waiver_reason: str = "",
    waiver_approver: str = "",
    waiver_at: str = "",
    waiver_document: str = "",
    dataset_version: str = "test-v1",
) -> dict:
    return {
        "dataset_name": (
            "authoritative_limit_rules"
            if kind == "rules"
            else "authoritative_security_status_history"
        ),
        "dataset_version": dataset_version,
        "schema_version": "1.0.0",
        "generated_at": "2026-08-05T10:00:00+08:00",
        "as_of_date": as_of,
        "coverage_start": start,
        "coverage_end": end,
        "review_status": review_status,
        "review_mode": review_mode,
        "verified_by_dual_review": review_status == "approved",
        "waiver_reason": waiver_reason,
        "waiver_approver": waiver_approver,
        "waiver_at": waiver_at,
        "waiver_document": waiver_document,
        "reviewed_at": "2026-08-05",
        "reviewer": reviewer,
        "sources": [
            {
                "file": name,
                "document_id": f"DOC-{index}",
                "document_date": "2026-07-01",
                "source_name": "测试官方来源",
                "reference": "https://example.invalid/doc",
                "retrieved_at": "2026-08-01T10:00:00+08:00",
                "grade": grade,
                "sha256": sha,
                "note": "测试文件",
            }
            for index, name in enumerate(files)
        ],
    }


def _rule_row(
    *,
    exchange: str,
    board: str,
    rule_type: str,
    ratio: str,
    sha: str,
    record_id: str,
    start_date: str = "2020-01-01",
    end_date: str = "",
    symbol: str = "",
    limit_down: str = "",
    source_reference: str = "https://example.invalid/doc",
    source_name: str = "测试官方来源",
    source_document_id: str = "DOC-0",
    review_status: str = "approved",
    review_mode: str = "dual_review",
    waiver_reason: str = "",
    waiver_approver: str = "",
    waiver_at: str = "",
    waiver_document: str = "",
) -> dict:
    return {
        "record_id": record_id,
        "market": exchange,
        "exchange": exchange,
        "board": board,
        "security_type": "A_SHARE",
        "rule_type": rule_type,
        "limit_ratio": ratio,
        "limit_down_ratio": limit_down,
        "effective_from": start_date,
        "effective_to": end_date,
        "symbol": symbol,
        "source_name": source_name,
        "source_document_id": source_document_id,
        "source_document_date": "2026-07-01",
        "source_reference": source_reference,
        "retrieved_at": "2026-08-01T10:00:00+08:00",
        "raw_file": "sources/rules.txt",
        "source_sha256": sha,
        "review_status": review_status,
        "review_mode": review_mode,
        "waiver_reason": waiver_reason,
        "waiver_approver": waiver_approver,
        "waiver_at": waiver_at,
        "waiver_document": waiver_document,
        "reviewer": "张三/李四",
        "notes": "测试记录",
    }


def _default_rule_rows(sha: str) -> list[dict]:
    combos = [
        ("SZ", "main", "price_limit", "0.10"),
        ("SZ", "main", "st_price_limit", "0.05"),
        ("SH", "main", "price_limit", "0.10"),
        ("SH", "main", "st_price_limit", "0.05"),
        ("SZ", "growth", "price_limit", "0.10"),
        ("SZ", "growth", "st_price_limit", "0.05"),
    ]
    return [
        _rule_row(
            exchange=exchange,
            board=board,
            rule_type=rule_type,
            ratio=ratio,
            sha=sha,
            record_id=f"rule-{exchange}-{board}-{rule_type}",
        )
        for exchange, board, rule_type, ratio in combos
    ]


def _waiver_rule_rows(sha: str) -> list[dict]:
    rows = _default_rule_rows(sha)
    for row in rows:
        row.update(
            {
                "review_status": "approved_with_waiver",
                "review_mode": "waiver",
                "reviewer": "",
                "waiver_reason": "无法在截止前完成双人独立复核",
                "waiver_approver": "项目负责人",
                "waiver_at": "2026-08-06T10:00:00+08:00",
                "waiver_document": "docs/stage8_rule_review_waiver.md",
            }
        )
    return rows


def _write_rules_dataset(
    root: Path,
    *,
    rows: list[dict] | None = None,
    sha: str | None = None,
    grade: str = "A",
    review_status: str = "approved",
    review_mode: str = "dual_review",
    reviewer: str = "张三/李四（双人复核）",
    waiver_reason: str = "",
    waiver_approver: str = "",
    waiver_at: str = "",
    waiver_document: str = "",
    examples_only: bool = False,
) -> Path:
    dataset_dir = root / "limit_rules"
    (dataset_dir / "sources").mkdir(parents=True, exist_ok=True)
    if sha is None:
        sha = _write_source(dataset_dir, "rules.txt", b"official rule source\n")
    elif not (dataset_dir / "sources" / "rules.txt").is_file():
        _write_source(dataset_dir, "rules.txt", b"official rule source\n")
    if examples_only:
        (dataset_dir / "dataset.example.yml").write_text(
            yaml.safe_dump(
                _manifest(kind="rules", dataset_dir=dataset_dir, sha=sha, files=[]),
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        (dataset_dir / "limit_rules.example.csv").write_text(
            "record_id,market\n", encoding="utf-8-sig"
        )
        return dataset_dir
    manifest = _manifest(
        kind="rules",
        dataset_dir=dataset_dir,
        sha=sha,
        files=["sources/rules.txt"],
        grade=grade,
        review_status=review_status,
        review_mode=review_mode,
        reviewer=reviewer,
        waiver_reason=waiver_reason,
        waiver_approver=waiver_approver,
        waiver_at=waiver_at,
        waiver_document=waiver_document,
    )
    (dataset_dir / "dataset.yml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    frame = pd.DataFrame(rows or _default_rule_rows(sha))
    frame.to_csv(dataset_dir / "limit_rules.csv", index=False, encoding="utf-8-sig")
    return dataset_dir


def _status_row(
    *,
    symbol: str,
    exchange: str,
    board: str,
    status_type: str,
    status_value: str,
    sha: str,
    record_id: str,
    start_date: str = "2025-07-27",
    end_date: str = "",
    announcement: str = "2025-07-25",
    source_reference: str = "https://example.invalid/status",
    review_status: str = "approved",
    review_mode: str = "dual_review",
    waiver_reason: str = "",
    waiver_approver: str = "",
    waiver_at: str = "",
    waiver_document: str = "",
) -> dict:
    return {
        "record_id": record_id,
        "symbol": symbol,
        "exchange": exchange,
        "board": board,
        "status_type": status_type,
        "status_value": status_value,
        "effective_from": start_date,
        "effective_to": end_date,
        "announcement_date": announcement,
        "source_name": "测试官方状态来源",
        "source_document_id": "DOC-STATUS",
        "source_reference": source_reference,
        "retrieved_at": "2026-08-01T10:00:00+08:00",
        "raw_file": "sources/status.txt",
        "source_sha256": sha,
        "review_status": review_status,
        "review_mode": review_mode,
        "waiver_reason": waiver_reason,
        "waiver_approver": waiver_approver,
        "waiver_at": waiver_at,
        "waiver_document": waiver_document,
        "reviewer": "张三/李四",
        "notes": "测试状态",
    }


def _default_status_rows(sha: str) -> list[dict]:
    rows: list[dict] = []
    universe = load_universe()
    for item in universe.stocks:
        board = "growth" if item.symbol.startswith("30") else "main"
        rows.append(
            _status_row(
                symbol=item.symbol,
                exchange=item.exchange,
                board=board,
                status_type="ST",
                status_value="NON_ST",
                sha=sha,
                record_id=f"status-{item.symbol}-st",
            )
        )
        rows.append(
            _status_row(
                symbol=item.symbol,
                exchange=item.exchange,
                board=board,
                status_type="LISTING",
                status_value="LISTED",
                sha=sha,
                record_id=f"status-{item.symbol}-listing",
            )
        )
    return rows


def _waiver_status_rows(sha: str) -> list[dict]:
    rows = _default_status_rows(sha)
    for row in rows:
        row.update(
            {
                "review_status": "approved_with_waiver",
                "review_mode": "waiver",
                "reviewer": "",
                "waiver_reason": "状态来源文档为官方公告证据包",
                "waiver_approver": "项目负责人",
                "waiver_at": "2026-08-06T10:00:00+08:00",
                "waiver_document": "docs/stage8_rule_review_waiver.md",
            }
        )
    return rows


def _write_status_dataset(
    root: Path,
    *,
    rows: list[dict] | None = None,
    sha: str | None = None,
    grade: str = "A",
    review_status: str = "approved",
    review_mode: str = "dual_review",
    reviewer: str = "张三/李四（双人复核）",
    waiver_reason: str = "",
    waiver_approver: str = "",
    waiver_at: str = "",
    waiver_document: str = "",
    examples_only: bool = False,
) -> Path:
    dataset_dir = root / "security_status"
    (dataset_dir / "sources").mkdir(parents=True, exist_ok=True)
    if sha is None:
        sha = _write_source(dataset_dir, "status.txt", b"official status source\n")
    elif not (dataset_dir / "sources" / "status.txt").is_file():
        _write_source(dataset_dir, "status.txt", b"official status source\n")
    if examples_only:
        (dataset_dir / "dataset.example.yml").write_text(
            yaml.safe_dump(
                _manifest(
                    kind="status", dataset_dir=dataset_dir, sha=sha, files=[]
                ),
                allow_unicode=True,
            ),
            encoding="utf-8",
        )
        (dataset_dir / "security_status_history.example.csv").write_text(
            "record_id,symbol\n", encoding="utf-8-sig"
        )
        return dataset_dir
    manifest = _manifest(
        kind="status",
        dataset_dir=dataset_dir,
        sha=sha,
        files=["sources/status.txt"],
        grade=grade,
        review_status=review_status,
        review_mode=review_mode,
        reviewer=reviewer,
        waiver_reason=waiver_reason,
        waiver_approver=waiver_approver,
        waiver_at=waiver_at,
        waiver_document=waiver_document,
    )
    (dataset_dir / "dataset.yml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    frame = pd.DataFrame(rows or _default_status_rows(sha))
    frame.to_csv(
        dataset_dir / "security_status_history.csv",
        index=False,
        encoding="utf-8-sig",
    )
    return dataset_dir


def _validate_rules(tmp_path: Path, **kwargs) -> dict:
    dataset_dir = _write_rules_dataset(tmp_path, **kwargs)
    return validate_manual_dataset(
        kind="rules",
        dataset_dir=dataset_dir,
        as_of_date=AS_OF,
        coverage_start=START,
        coverage_end=END,
        run_id=_run_id(),
    )


def _validate_status(tmp_path: Path, **kwargs) -> dict:
    dataset_dir = _write_status_dataset(tmp_path, **kwargs)
    return validate_manual_dataset(
        kind="status",
        dataset_dir=dataset_dir,
        as_of_date=AS_OF,
        coverage_start=START,
        coverage_end=END,
        run_id=_run_id(),
    )


def test_valid_rules_dataset_passes():
    import tempfile

    with tempfile.TemporaryDirectory(prefix="stage8_test_") as temporary:
        result = _validate_rules(Path(temporary))
        assert result["valid"] is True
        assert result["status"] == "READY"
        assert result["record_count"] == 6
        assert result["verified_record_count"] == 6
        assert all(stage["status"] == "PASS" for stage in result["stages"])


def test_approved_with_waiver_rules_passes_validate_only(tmp_path):
    sha = _sha(b"official rule source\n")
    rows = _waiver_rule_rows(sha)
    result = _validate_rules(
        tmp_path,
        rows=rows,
        sha=sha,
        review_status="approved_with_waiver",
        review_mode="waiver",
        reviewer="",
        waiver_reason="无法在截止前完成双人独立复核",
        waiver_approver="项目负责人",
        waiver_at="2026-08-06T10:00:00+08:00",
        waiver_document="docs/stage8_rule_review_waiver.md",
    )
    assert result["valid"] is True
    assert result["status"] == "READY"
    assert result["review_status"] == "approved_with_waiver"
    assert result["review_mode"] == "waiver"
    assert result["verified_by_dual_review"] is False
    dataset_dir = _write_rules_dataset(
        tmp_path / "waiver-rules",
        rows=rows,
        sha=sha,
        review_status="approved_with_waiver",
        review_mode="waiver",
        reviewer="",
        waiver_reason="无法在截止前完成双人独立复核",
        waiver_approver="项目负责人",
        waiver_at="2026-08-06T10:00:00+08:00",
        waiver_document="docs/stage8_rule_review_waiver.md",
    )
    out = tmp_path / "waiver-validate-out"
    report, exit_code = build_rules_manifest(
        dataset_dir=dataset_dir,
        output_dir=out,
        as_of_date=AS_OF,
        run_id=_run_id(),
        validate_only=True,
    )
    assert exit_code == 0
    assert report["status"] == "READY"
    assert report["outputs_written"] is False
    assert not out.exists()


def test_approved_with_waiver_status_dataset_passes(tmp_path):
    sha = _sha(b"official status source\n")
    rows = _waiver_status_rows(sha)
    result = _validate_status(
        tmp_path,
        rows=rows,
        sha=sha,
        review_status="approved_with_waiver",
        review_mode="waiver",
        reviewer="",
        waiver_reason="状态来源文档为官方公告证据包",
        waiver_approver="项目负责人",
        waiver_at="2026-08-06T10:00:00+08:00",
        waiver_document="docs/stage8_rule_review_waiver.md",
    )
    assert result["valid"] is True
    assert result["review_status"] == "approved_with_waiver"
    assert result["review_mode"] == "waiver"
    assert result["verified_by_dual_review"] is False


def test_waiver_missing_reason_fails(tmp_path):
    sha = _sha(b"x")
    rows = _waiver_rule_rows(sha)
    for row in rows:
        row["waiver_reason"] = ""
    result = _validate_rules(
        tmp_path,
        rows=rows,
        sha=sha,
        review_status="approved_with_waiver",
        review_mode="waiver",
        reviewer="",
        waiver_reason="",
        waiver_approver="项目负责人",
        waiver_at="2026-08-06T10:00:00+08:00",
        waiver_document="docs/stage8_rule_review_waiver.md",
    )
    assert result["valid"] is False
    assert any("waiver_reason_required" in error for error in result["errors"])


def test_waiver_missing_approver_fails(tmp_path):
    sha = _sha(b"x")
    rows = _waiver_rule_rows(sha)
    for row in rows:
        row["waiver_approver"] = ""
    result = _validate_rules(
        tmp_path,
        rows=rows,
        sha=sha,
        review_status="approved_with_waiver",
        review_mode="waiver",
        reviewer="",
        waiver_reason="无法完成双人复核",
        waiver_approver="",
        waiver_at="2026-08-06T10:00:00+08:00",
        waiver_document="docs/stage8_rule_review_waiver.md",
    )
    assert result["valid"] is False
    assert any("waiver_approver_required" in error for error in result["errors"])


def test_waiver_invalid_at_fails(tmp_path):
    sha = _sha(b"x")
    rows = _waiver_rule_rows(sha)
    for row in rows:
        row["waiver_at"] = "2026-08-06T10:00:00"
    result = _validate_rules(
        tmp_path,
        rows=rows,
        sha=sha,
        review_status="approved_with_waiver",
        review_mode="waiver",
        reviewer="",
        waiver_reason="无法完成双人复核",
        waiver_approver="项目负责人",
        waiver_at="2026-08-06T10:00:00",
        waiver_document="docs/stage8_rule_review_waiver.md",
    )
    assert result["valid"] is False
    assert any("timezone" in error for error in result["errors"])


def test_waiver_document_missing_fails(tmp_path):
    sha = _sha(b"x")
    rows = _waiver_rule_rows(sha)
    for row in rows:
        row["waiver_document"] = "docs/does_not_exist.md"
    result = _validate_rules(
        tmp_path,
        rows=rows,
        sha=sha,
        review_status="approved_with_waiver",
        review_mode="waiver",
        reviewer="",
        waiver_reason="无法完成双人复核",
        waiver_approver="项目负责人",
        waiver_at="2026-08-06T10:00:00+08:00",
        waiver_document="docs/does_not_exist.md",
    )
    assert result["valid"] is False
    assert any(
        "waiver_document_must_be" in error
        or "waiver_document_missing" in error
        for error in result["errors"]
    )


def test_waiver_wrong_review_mode_fails(tmp_path):
    sha = _sha(b"x")
    rows = _waiver_rule_rows(sha)
    for row in rows:
        row["review_mode"] = "dual_review"
    result = _validate_rules(
        tmp_path,
        rows=rows,
        sha=sha,
        review_status="approved_with_waiver",
        review_mode="dual_review",
        reviewer="",
        waiver_reason="无法完成双人复核",
        waiver_approver="项目负责人",
        waiver_at="2026-08-06T10:00:00+08:00",
        waiver_document="docs/stage8_rule_review_waiver.md",
    )
    assert result["valid"] is False
    assert any("review_mode_must_be_waiver" in error for error in result["errors"])


def test_approved_without_reviewer_fails(tmp_path):
    rows = _default_rule_rows(_sha(b"x"))
    for row in rows:
        row["reviewer"] = ""
    result = _validate_rules(tmp_path, rows=rows)
    assert result["valid"] is False
    assert any("reviewer_required" in error for error in result["errors"])


def test_valid_status_dataset_passes():
    import tempfile

    with tempfile.TemporaryDirectory(prefix="stage8_test_") as temporary:
        result = _validate_status(Path(temporary))
        assert result["valid"] is True
        assert result["status"] == "READY"
        assert result["record_count"] == 32
        assert all(stage["status"] == "PASS" for stage in result["stages"])


def test_missing_source_field_fails(tmp_path):
    rows = _default_rule_rows(_sha(b"x"))
    rows[0].pop("source_name")
    result = _validate_rules(tmp_path, rows=rows)
    assert result["valid"] is False
    assert any("source_name_required" in error for error in result["errors"])


def test_raw_source_file_missing_fails(tmp_path):
    dataset_dir = _write_rules_dataset(tmp_path)
    (dataset_dir / "sources" / "rules.txt").unlink()
    result = validate_manual_dataset(
        kind="rules",
        dataset_dir=dataset_dir,
        as_of_date=AS_OF,
        coverage_start=START,
        coverage_end=END,
        run_id=_run_id(),
    )
    assert result["valid"] is False
    assert any("source_file_missing" in error for error in result["errors"])


def test_sha256_mismatch_fails(tmp_path):
    dataset_dir = _write_rules_dataset(tmp_path)
    payload = yaml.safe_load(
        (dataset_dir / "dataset.yml").read_text(encoding="utf-8")
    )
    payload["sources"][0]["sha256"] = "f" * 64
    (dataset_dir / "dataset.yml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    result = validate_manual_dataset(
        kind="rules",
        dataset_dir=dataset_dir,
        as_of_date=AS_OF,
        coverage_start=START,
        coverage_end=END,
        run_id=_run_id(),
    )
    assert result["valid"] is False
    assert any("source_sha256_mismatch" in error for error in result["errors"])


def test_unapproved_data_fails(tmp_path):
    rows = _default_rule_rows(_sha(b"x"))
    rows[0]["review_status"] = "pending"
    result = _validate_rules(tmp_path, rows=rows)
    assert result["valid"] is False
    assert any("review_not_approved" in error for error in result["errors"])


def test_invalid_date_fails(tmp_path):
    rows = _default_rule_rows(_sha(b"x"))
    rows[0]["effective_from"] = "2026/07/27"
    result = _validate_rules(tmp_path, rows=rows)
    assert result["valid"] is False
    assert any("effective_from" in error for error in result["errors"])


def test_overlapping_intervals_fail(tmp_path):
    rows = _default_rule_rows(_sha(b"x"))
    rows.append(
        _rule_row(
            exchange="SZ",
            board="main",
            rule_type="price_limit",
            ratio="0.20",
            sha=rows[0]["source_sha256"],
            record_id="overlap-rule",
            start_date="2026-01-01",
        )
    )
    result = _validate_rules(tmp_path, rows=rows)
    assert result["valid"] is False
    assert any("Overlapping limit-rule intervals" in error for error in result["errors"])


def test_conflicting_rules_fail(tmp_path):
    rows = _default_rule_rows(_sha(b"x"))
    rows.append(
        _rule_row(
            exchange="SZ",
            board="main",
            rule_type="price_limit",
            ratio="0.12",
            sha=rows[0]["source_sha256"],
            record_id="conflict-rule",
            start_date="2020-01-01",
        )
    )
    result = _validate_rules(tmp_path, rows=rows)
    assert result["valid"] is False
    assert any("Overlapping" in error for error in result["errors"])


def test_current_snapshot_masquerading_as_history_fails(tmp_path):
    rows = _default_status_rows(_sha(b"x"))
    rows = [
        row
        for row in rows
        if row["record_id"] == "status-002067-st"
    ]
    rows[0]["effective_from"] = "2026-07-27"
    rows[0]["effective_to"] = "2026-07-27"
    result = _validate_status(tmp_path, rows=rows)
    assert result["valid"] is False
    assert any("coverage_status" in error for error in result["errors"])


def test_former_name_inference_fails(tmp_path):
    rows = _default_status_rows(_sha(b"x"))
    rows[0]["source_reference"] = (
        "https://example.invalid/stock_info_change_name"
    )
    result = _validate_status(tmp_path, rows=rows)
    assert result["valid"] is False
    assert any(
        "former_name_inference_not_authoritative" in error
        for error in result["errors"]
    )


def test_grade_b_source_fails(tmp_path):
    result = _validate_status(tmp_path, grade="B")
    assert result["valid"] is False
    assert any(
        "source_grade_not_authoritative" in error for error in result["errors"]
    )


def test_example_files_never_enter_formal_build(tmp_path):
    dataset_dir = _write_rules_dataset(
        tmp_path, sha=_sha(b"x"), examples_only=True
    )
    result = validate_manual_dataset(
        kind="rules",
        dataset_dir=dataset_dir,
        as_of_date=AS_OF,
        coverage_start=START,
        coverage_end=END,
        run_id=_run_id(),
    )
    assert result["valid"] is False
    assert result["status"] == "FAILED"
    assert any("dataset_manifest_missing" in error for error in result["errors"])
    assert not list((tmp_path / "out").glob("*"))
    report, exit_code = build_rules_manifest(
        dataset_dir=dataset_dir,
        output_dir=tmp_path / "out",
        as_of_date=AS_OF,
        run_id=_run_id(),
    )
    assert exit_code == 1
    assert report["status"] == "FAILED"
    assert not (tmp_path / "out").exists()


def test_validate_only_does_not_publish(tmp_path):
    dataset_dir = _write_rules_dataset(tmp_path)
    out = tmp_path / "must-not-exist"
    report, exit_code = build_rules_manifest(
        dataset_dir=dataset_dir,
        output_dir=out,
        as_of_date=AS_OF,
        run_id=_run_id(),
        validate_only=True,
    )
    assert exit_code == 0
    assert report["status"] == "READY"
    assert not out.exists()


def test_formal_build_is_atomic_and_leaves_no_half_products(tmp_path):
    dataset_dir = _write_rules_dataset(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "rules_manifest.json").mkdir()
    with pytest.raises(OSError):
        build_rules_manifest(
            dataset_dir=dataset_dir,
            output_dir=out,
            as_of_date=AS_OF,
            run_id=_run_id(),
            output_config=tmp_path / "stage8_config.yml",
        )
    assert not (out / "rules_manifest.csv").exists()
    assert not (out / "rules_manifest.json").is_file()
    assert not (tmp_path / "stage8_config.yml").exists()


def test_build_failure_leaves_no_outputs(tmp_path):
    dataset_dir = _write_rules_dataset(
        tmp_path, grade="C"
    )
    out = tmp_path / "blocked-out"
    report, exit_code = build_rules_manifest(
        dataset_dir=dataset_dir,
        output_dir=out,
        as_of_date=AS_OF,
        run_id=_run_id(),
    )
    assert exit_code == 1
    assert report["status"] == "FAILED"
    assert not out.exists()


def test_windows_chinese_path(tmp_path):
    root = tmp_path / "中文路径" / "涨跌停规则数据集"
    dataset_dir = _write_rules_dataset(root)
    result = validate_manual_dataset(
        kind="rules",
        dataset_dir=dataset_dir,
        as_of_date=AS_OF,
        coverage_start=START,
        coverage_end=END,
        run_id=_run_id(),
    )
    assert result["valid"] is True
    out = root / "输出目录"
    report, exit_code = build_rules_manifest(
        dataset_dir=dataset_dir,
        output_dir=out,
        as_of_date=AS_OF,
        run_id=_run_id(),
    )
    assert exit_code == 0
    assert report["status"] == "PASS"
    assert (out / "rules_manifest.csv").is_file()
    json.loads((out / "rules_manifest.json").read_text(encoding="utf-8"))


def test_status_merge_and_interval_validation(tmp_path):
    dataset_dir = _write_status_dataset(tmp_path)
    result = validate_manual_dataset(
        kind="status",
        dataset_dir=dataset_dir,
        as_of_date=AS_OF,
        coverage_start=START,
        coverage_end=END,
        run_id=_run_id(),
    )
    from akshare_data_test.stage8_manual import _internal_statuses

    statuses = _internal_statuses(result["records"], result["manifest"])
    validate_status_intervals(statuses)
    merged = resolve_security_status(statuses, "002067", date(2026, 1, 1))
    assert merged.listing_status == "listed"
    assert merged.is_st is False


def test_rules_and_statuses_resolve_together(tmp_path):
    rules_dir = _write_rules_dataset(tmp_path / "r")
    status_dir = _write_status_dataset(tmp_path / "s")
    rules_result = validate_manual_dataset(
        kind="rules",
        dataset_dir=rules_dir,
        as_of_date=AS_OF,
        coverage_start=START,
        coverage_end=END,
        run_id=_run_id(),
    )
    status_result = validate_manual_dataset(
        kind="status",
        dataset_dir=status_dir,
        as_of_date=AS_OF,
        coverage_start=START,
        coverage_end=END,
        run_id=_run_id(),
    )
    from akshare_data_test.stage8_manual import _internal_rules, _internal_statuses

    rules = _internal_rules(rules_result["records"], rules_result["manifest"])
    statuses = _internal_statuses(
        status_result["records"], status_result["manifest"]
    )
    validate_rule_intervals(rules)
    status = resolve_security_status(statuses, "002067", date(2026, 1, 1))
    rule = resolve_limit_rule(rules, status, date(2026, 1, 1))
    assert rule.limit_up_ratio is not None


def test_combined_datasets_and_merged_payload(tmp_path):
    rules_dir = _write_rules_dataset(tmp_path / "rules")
    status_dir = _write_status_dataset(tmp_path / "status")
    combined = validate_combined_datasets(
        rules_dir=rules_dir,
        status_dir=status_dir,
        as_of_date=AS_OF,
        coverage_start=START,
        coverage_end=END,
        run_id=_run_id(),
    )
    assert combined["valid"] is True
    assert combined["status"] == "READY"
    payload = build_merged_payload(
        rules_result=combined["components"]["rules"],
        status_result=combined["components"]["security_status_history"],
        run_id=_run_id(),
    )
    config_path = tmp_path / "merged.yml"
    config_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    raw, rules, statuses = load_stage8_config(config_path)
    assert len(rules) == 6
    assert len(statuses) == 32
    assert raw["dataset_manifest"]["source_files"]
    assert raw["dataset_manifest"]["record_counts"]
    assert raw["dataset_manifest"]["date_coverage"]


def test_merged_payload_keeps_waiver_markers(tmp_path):
    sha = _sha(b"official rule source\n")
    rules_dir = _write_rules_dataset(
        tmp_path / "rules-waiver",
        rows=_waiver_rule_rows(sha),
        sha=sha,
        review_status="approved_with_waiver",
        review_mode="waiver",
        reviewer="",
        waiver_reason="规则无法在截止前完成双人复核",
        waiver_approver="项目负责人",
        waiver_at="2026-08-06T10:00:00+08:00",
        waiver_document="docs/stage8_rule_review_waiver.md",
    )
    status_dir = _write_status_dataset(tmp_path / "status-approved")
    combined = validate_combined_datasets(
        rules_dir=rules_dir,
        status_dir=status_dir,
        as_of_date=AS_OF,
        coverage_start=START,
        coverage_end=END,
        run_id=_run_id(),
    )
    assert combined["valid"] is True
    payload = build_merged_payload(
        rules_result=combined["components"]["rules"],
        status_result=combined["components"]["security_status_history"],
        run_id=_run_id(),
    )
    manifest = payload["dataset_manifest"]
    assert manifest["review_status"] == "approved_with_waiver"
    assert manifest["review_mode"] == "waiver"
    assert manifest["verified_by_dual_review"] is False
    assert manifest["waiver_document"] == "docs/stage8_rule_review_waiver.md"
    config_path = tmp_path / "merged-waiver.yml"
    config_path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    raw, rules, statuses = load_stage8_config(config_path)
    assert raw["dataset_manifest"]["review_status"] == "approved_with_waiver"
    assert raw["dataset_manifest"]["review_mode"] == "waiver"
    assert all(item.review_status == "approved_with_waiver" for item in rules)
    assert all(item.review_mode == "waiver" for item in rules)
    assert all(item.evidence_status == "verified" for item in rules)
    assert len(statuses) == 32


def test_rules_build_dataset_roundtrip(tmp_path):
    dataset_dir = _write_rules_dataset(tmp_path)
    out = tmp_path / "out"
    config = tmp_path / "stage8_rules.yml"
    report, exit_code = build_rules_manifest(
        dataset_dir=dataset_dir,
        output_dir=out,
        as_of_date=AS_OF,
        run_id=_run_id(),
        output_config=config,
    )
    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["dataset_validation"]["valid"] is True
    assert len(report["record_ids"]) == 6
    assert report["provenance"]["source_files"] == ["sources/rules.txt"]
    assert (out / "rules_manifest.csv").is_file()
    assert (out / "rules_dataset_validation.json").is_file()
    assert (out / "rules_dataset_provenance.json").is_file()
    frame = pd.read_csv(out / "rules_manifest.csv", dtype=str)
    assert "record_id" in frame.columns
    assert "source_sha256" not in frame.columns
    raw, rules, statuses = load_stage8_config(config)
    assert len(rules) == 6
    assert raw["dataset_manifest"]["review_status"] == "approved"
    assert raw["dataset_manifest"]["review_mode"] == "dual_review"
    assert raw["dataset_manifest"]["verified_by_dual_review"] is True


def test_status_build_dataset_roundtrip(tmp_path):
    dataset_dir = _write_status_dataset(tmp_path)
    out = tmp_path / "out"
    config = tmp_path / "stage8_status.yml"
    report, exit_code = build_status_manifest(
        dataset_dir=dataset_dir,
        output_dir=out,
        as_of_date=AS_OF,
        run_id=_run_id(),
        output_config=config,
    )
    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["dataset_validation"]["valid"] is True
    assert len(report["record_ids"]) == 32
    assert (out / "status_manifest.csv").is_file()
    assert (out / "status_dataset_validation.json").is_file()
    assert (out / "status_dataset_provenance.json").is_file()
    raw, rules, statuses = load_stage8_config(config)
    assert len(statuses) == 32
    assert raw["dataset_manifest"]["record_counts"][
        "authoritative_security_status_history"
    ] == 32


def test_manifest_as_of_date_must_match(tmp_path):
    dataset_dir = _write_rules_dataset(tmp_path)
    payload = yaml.safe_load(
        (dataset_dir / "dataset.yml").read_text(encoding="utf-8")
    )
    payload["as_of_date"] = "2026-07-28"
    (dataset_dir / "dataset.yml").write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    result = validate_manual_dataset(
        kind="rules",
        dataset_dir=dataset_dir,
        as_of_date=AS_OF,
        coverage_start=START,
        coverage_end=END,
        run_id=_run_id(),
    )
    assert result["valid"] is False
    assert any("dataset_as_of_date_mismatch" in error for error in result["errors"])


def test_unknown_columns_fail(tmp_path):
    dataset_dir = _write_rules_dataset(tmp_path)
    frame = pd.read_csv(dataset_dir / "limit_rules.csv", dtype=str)
    frame["surprise_column"] = "x"
    frame.to_csv(
        dataset_dir / "limit_rules.csv", index=False, encoding="utf-8-sig"
    )
    result = validate_manual_dataset(
        kind="rules",
        dataset_dir=dataset_dir,
        as_of_date=AS_OF,
        coverage_start=START,
        coverage_end=END,
        run_id=_run_id(),
    )
    assert result["valid"] is False
    assert any("records_csv_unknown_columns" in error for error in result["errors"])


def test_committed_example_headers_match_contracts():
    rules_example = (
        ROOT
        / "data/manual/stage8/limit_rules/limit_rules.example.csv"
    )
    status_example = (
        ROOT
        / "data/manual/stage8/security_status/security_status_history.example.csv"
    )
    rules_frame = pd.read_csv(rules_example, dtype=str)
    status_frame = pd.read_csv(status_example, dtype=str)
    assert set(RULES_REQUIRED_COLUMNS).issubset(rules_frame.columns)
    assert set(STATUS_REQUIRED_COLUMNS).issubset(status_frame.columns)
    assert "review_mode" in rules_frame.columns
    assert "review_mode" in status_frame.columns
    assert "waiver_document" in rules_frame.columns
    assert "waiver_document" in status_frame.columns


def test_default_cli_accepts_audited_rule_dataset_without_publishing_it():
    result = subprocess.run(
        [
            sys.executable,
            "run_pipeline.py",
            "stage8-rules-build",
            "--as-of-date",
            "2026-07-27",
            "--validate-only",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "READY"
    assert payload["dataset_validation"]["review_status"] == "approved_with_waiver"
    assert payload["outputs_written"] is False
    assert "Traceback" not in result.stdout + result.stderr
