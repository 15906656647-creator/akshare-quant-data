from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import duckdb
import pandas as pd
import pytest
import yaml

from akshare_data_test.limit_rules import (
    LimitRule,
    RuleResolutionError,
    SecurityStatus,
    SecurityStatusResolutionError,
    calculate_limit_price,
    resolve_limit_rule,
    resolve_security_status,
    validate_rule_intervals,
    validate_status_intervals,
)
from akshare_data_test.stage8_authoritative import (
    build_rules_manifest,
    build_status_manifest,
    verify_s14,
)
from akshare_data_test.stage8_build import load_stage8_config


ROOT = Path(__file__).resolve().parents[1]


def rule(**overrides) -> LimitRule:
    values = {
        "exchange": "SZ",
        "board": "main",
        "is_st": False,
        "effective_start": date(2020, 1, 1),
        "effective_end": None,
        "limit_up_ratio": Decimal("0.10"),
        "limit_down_ratio": Decimal("0.10"),
        "no_limit_flag": False,
        "tick_size": Decimal("0.01"),
        "price_precision": 2,
        "rounding_rule": "half_up",
        "rule_version": "test-rule-v1",
        "source_reference": "fixture://verified-rule",
        "source_name": "test fixture",
        "verified_at": date(2026, 7, 27),
        "evidence_status": "verified",
    }
    values.update(overrides)
    return LimitRule(**values)


def status(**overrides) -> SecurityStatus:
    values = {
        "symbol": "000001",
        "effective_start": date(2020, 1, 1),
        "effective_end": None,
        "exchange": "SZ",
        "board": "main",
        "is_st": False,
        "listing_status": "listed",
        "listing_date": date(1991, 1, 1),
        "delisting_date": None,
        "no_limit_reason": None,
        "source_reference": "fixture://verified-status",
        "source_name": "test fixture",
        "status_version": "test-status-v1",
        "evidence_status": "verified",
    }
    values.update(overrides)
    return SecurityStatus(**values)


def test_per_symbol_rule_overrides_board_rule():
    rules = [
        rule(rule_version="board-rule"),
        rule(
            symbol="000001",
            rule_version="symbol-rule",
            effective_start=date(2019, 1, 1),
        ),
    ]
    assert resolve_limit_rule(rules, status(), date(2021, 1, 1)).rule_version == (
        "symbol-rule"
    )


def test_per_symbol_rule_does_not_apply_to_other_symbols():
    rules = [
        rule(rule_version="board-rule"),
        rule(
            symbol="000002",
            rule_version="other-symbol-rule",
            effective_start=date(2019, 1, 1),
        ),
    ]
    assert resolve_limit_rule(rules, status(), date(2021, 1, 1)).rule_version == (
        "board-rule"
    )


def test_duplicate_matching_rules_still_fail_closed():
    rules = [
        rule(rule_version="board-a"),
        rule(rule_version="board-b"),
    ]
    with pytest.raises(RuleResolutionError, match="found 2"):
        resolve_limit_rule(rules, status(), date(2021, 1, 1))


def test_symbol_rules_do_not_count_as_board_overlap():
    validate_rule_intervals([
        rule(rule_version="board-rule"),
        rule(
            symbol="000001",
            rule_version="symbol-rule",
            effective_start=date(2020, 6, 1),
        ),
    ])


def test_rule_audit_fields_are_validated():
    with pytest.raises(ValueError, match="six digits"):
        rule(symbol="123")
    with pytest.raises(ValueError, match="SHA-256"):
        rule(source_hash="not-a-hash")
    with pytest.raises(ValueError, match="security_type"):
        rule(security_type="lower-case")
    assert rule(
        symbol="000001",
        security_type="A_SHARE",
        source_hash="a" * 64,
        data_version="v1",
        source_published_at=date(2026, 7, 27),
    ).symbol == "000001"


def test_status_special_treatment_and_audit_fields():
    selected = resolve_security_status(
        [
            status(effective_end=date(2022, 1, 1)),
            status(
                effective_start=date(2022, 1, 2),
                is_st=True,
                special_treatment_type="*ST",
                source_hash="b" * 64,
                data_version="v1",
                status_version="st-v2",
            ),
        ],
        "000001",
        date(2023, 1, 1),
    )
    assert selected.special_treatment_type == "*ST"
    with pytest.raises(ValueError, match="special_treatment_type"):
        status(special_treatment_type="unknown")


def test_status_gap_is_not_implicitly_non_st():
    with pytest.raises(SecurityStatusResolutionError, match="found 0"):
        resolve_security_status(
            [status(effective_end=date(2021, 12, 31))],
            "000001",
            date(2022, 1, 1),
        )


def test_authoritative_config_with_manifest_loads_verified_records(tmp_path):
    payload = {
        "schema_version": "1.0.0",
        "price_adjust_type": "raw",
        "rounding_rules": {"supported": ["half_up", "half_even"]},
        "formal_evidence_status": "verified",
        "formal_quality_status": "pass",
        "unresolved_policy": "block_formal_annual_statistics",
        "rule_records": [
            {
                "exchange": "SZ", "board": "main", "is_st": False,
                "effective_start": "2020-01-01", "effective_end": None,
                "limit_up_ratio": 0.1, "limit_down_ratio": 0.1,
                "no_limit_flag": False, "tick_size": 0.01,
                "price_precision": 2, "rounding_rule": "half_up",
                "rule_version": "fixture-rule", "source_reference": "fixture://rule",
                "source_name": "fixture", "verified_at": "2026-07-27",
                "evidence_status": "verified",
                "record_id": "rule-001", "raw_file": "sources/rule.txt",
                "source_document_id": "DOC-1", "reviewer": "复核人",
                "notes": "", "retrieved_at": "2026-08-01T10:00:00+08:00",
                "review_status": "approved",
                "security_type": "A_SHARE",
                "source_published_at": "2026-07-01",
                "source_hash": "a" * 64,
                "data_version": "v1",
            }
        ],
        "security_status_records": [
            {
                "symbol": "000001", "effective_start": "2020-01-01",
                "effective_end": None, "exchange": "SZ", "board": "main",
                "is_st": False, "listing_status": "listed",
                "listing_date": "1991-01-01", "delisting_date": None,
                "no_limit_reason": None, "source_reference": "fixture://status",
                "status_version": "fixture-status", "evidence_status": "verified",
                "record_id": "status-001", "status_type": "ST",
                "status_value": "NON_ST", "announcement_date": "2026-07-01",
                "raw_file": "sources/status.txt", "source_document_id": "DOC-2",
                "reviewer": "复核人", "notes": "",
                "retrieved_at": "2026-08-01T10:00:00+08:00",
                "review_status": "approved",
                "source_name": "fixture", "source_published_at": "2026-07-01",
                "source_hash": "b" * 64, "data_version": "v1",
            }
        ],
        "source_notes": {
            "limit_pool_usage": "cross_validation_only",
            "gap_proxy_usage": "candidate_feature_only_not_formal_event",
        },
        "dataset_manifest": {
            "dataset_version": "v1",
            "generated_at": "2026-08-05T10:00:00+08:00",
            "as_of_date": "2026-07-27",
            "source_files": ["sources/rule.txt", "sources/status.txt"],
            "source_hashes": {
                "sources/rule.txt": "a" * 64,
                "sources/status.txt": "b" * 64,
            },
            "record_counts": {
                "authoritative_limit_rules": 1,
                "authoritative_security_status_history": 1,
            },
            "date_coverage": {"start": "2025-07-27", "end": "2026-07-27"},
            "review_status": "approved",
            "run_id": "manifest-run",
        },
    }
    path = tmp_path / "stage8.yml"
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    raw, rules, statuses = load_stage8_config(path)
    assert all(item.evidence_status == "verified" for item in rules)
    assert all(item.evidence_status == "verified" for item in statuses)
    assert rules[0].record_id == "rule-001"
    assert statuses[0].status_type == "ST"
    assert raw["dataset_manifest"]["review_status"] == "approved"
    assert all(item.source_hash for item in rules)
    assert all(item.source_hash for item in statuses)


def test_authoritative_rule_gap_and_overlap_validation():
    with pytest.raises(ValueError, match="Overlapping"):
        validate_rule_intervals([
            rule(effective_end=date(2021, 6, 30)),
            rule(
                rule_version="v2",
                effective_start=date(2021, 6, 1),
            ),
        ])
    # A gap between rules means a trading day has no rule; detection must
    # fail closed rather than fall back to a fixed ratio.
    with pytest.raises(RuleResolutionError, match="found 0"):
        resolve_limit_rule(
            [
                rule(effective_end=date(2021, 6, 30)),
                rule(
                    rule_version="v2",
                    effective_start=date(2021, 7, 2),
                ),
            ],
            status(),
            date(2021, 7, 1),
        )


def test_st_and_board_specific_rule_selection():
    rules = [
        rule(rule_version="main-nonst"),
        rule(is_st=True, rule_version="main-st", limit_up_ratio=Decimal("0.05")),
        rule(board="growth", rule_version="growth-nonst", limit_up_ratio=Decimal("0.20")),
    ]
    st_selected = resolve_limit_rule(
        rules,
        status(is_st=True),
        date(2021, 1, 1),
    )
    growth_selected = resolve_limit_rule(
        rules,
        status(board="growth"),
        date(2021, 1, 1),
    )
    assert st_selected.rule_version == "main-st"
    assert growth_selected.rule_version == "growth-nonst"


def test_price_rounding_and_ipo_special_rule(tmp_path):
    ipo_rule = rule(
        symbol="000001",
        effective_start=date(2020, 1, 1),
        effective_end=date(2020, 1, 1),
        limit_up_ratio=Decimal("0.44"),
        limit_down_ratio=Decimal("0.36"),
        rule_version="ipo-first-day",
    )
    _, rounded = calculate_limit_price(
        Decimal("10.00"), Decimal("0.44"), ipo_rule, direction="up"
    )
    assert rounded == Decimal("14.40")
    assert resolve_limit_rule(
        [rule(rule_version="board"), ipo_rule], status(), date(2020, 1, 1)
    ).rule_version == "ipo-first-day"


def _component_config(tmp_path: Path, kind: str) -> Path:
    path = tmp_path / f"{kind}.yml"
    if kind == "rules":
        payload = {
            "rule_records": [
                {
                    "exchange": "SZ", "board": "main", "is_st": False,
                    "effective_start": "2020-01-01", "effective_end": None,
                    "limit_up_ratio": 0.1, "limit_down_ratio": 0.1,
                    "no_limit_flag": False, "tick_size": 0.01,
                    "price_precision": 2, "rounding_rule": "half_up",
                    "rule_version": "fixture-rule",
                    "source_reference": "fixture://rule",
                    "source_name": "fixture", "verified_at": "2026-07-27",
                    "evidence_status": "verified",
                },
                {
                    "exchange": "SZ", "board": "main", "is_st": True,
                    "effective_start": "2020-01-01", "effective_end": None,
                    "limit_up_ratio": 0.05, "limit_down_ratio": 0.05,
                    "no_limit_flag": False, "tick_size": 0.01,
                    "price_precision": 2, "rounding_rule": "half_up",
                    "rule_version": "fixture-rule-st",
                    "source_reference": "fixture://rule-st",
                    "source_name": "fixture", "verified_at": "2026-07-27",
                    "evidence_status": "verified",
                },
            ]
        }
    else:
        payload = {
            "security_status_records": [
                {
                    "symbol": "000001", "effective_start": "2020-01-01",
                    "effective_end": None, "exchange": "SZ", "board": "main",
                    "is_st": False, "listing_status": "listed",
                    "listing_date": "1991-01-01", "delisting_date": None,
                    "no_limit_reason": None,
                    "source_reference": "fixture://status",
                    "status_version": "fixture-status",
                    "evidence_status": "verified",
                },
                {
                    "symbol": "000002", "effective_start": "2020-01-01",
                    "effective_end": None, "exchange": "SZ", "board": "main",
                    "is_st": False, "listing_status": "listed",
                    "listing_date": "1991-01-02", "delisting_date": None,
                    "no_limit_reason": None,
                    "source_reference": "fixture://status",
                    "status_version": "fixture-status",
                    "evidence_status": "verified",
                },
            ]
        }
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_rules_and_status_build_commands_are_offline_and_idempotent(tmp_path):
    rules_path = _component_config(tmp_path, "rules")
    statuses_path = _component_config(tmp_path, "status")
    out = tmp_path / "out"
    config = tmp_path / "stage8_s14_fix.yml"
    first, code = build_rules_manifest(
        rules_path=rules_path,
        output_dir=out,
        as_of_date=date(2026, 7, 27),
        run_id="11111111-1111-4111-8111-111111111111",
        output_config=config,
    )
    assert code == 0
    assert first["verified_rule_count"] == 2
    second, code2 = build_status_manifest(
        statuses_path=statuses_path,
        output_dir=out,
        as_of_date=date(2026, 7, 27),
        run_id="22222222-2222-4222-8222-222222222222",
        output_config=config,
    )
    assert code2 == 0
    assert second["covered_symbol_count"] == 2
    merged = yaml.safe_load(config.read_text(encoding="utf-8"))
    assert len(merged["rule_records"]) == 2
    assert len(merged["security_status_records"]) == 2


def test_rules_and_status_validate_only_do_not_write_outputs(tmp_path):
    rules_path = _component_config(tmp_path, "rules")
    statuses_path = _component_config(tmp_path, "status")
    out = tmp_path / "validate-out"
    report, code = build_rules_manifest(
        rules_path=rules_path,
        output_dir=out,
        as_of_date=date(2026, 7, 27),
        run_id="11111111-1111-4111-8111-111111111111",
        validate_only=True,
    )
    assert code == 0
    assert report["status"] == "READY"
    assert report["outputs_written"] is False
    assert not out.exists()
    report2, code2 = build_status_manifest(
        statuses_path=statuses_path,
        output_dir=out,
        as_of_date=date(2026, 7, 27),
        run_id="22222222-2222-4222-8222-222222222222",
        validate_only=True,
    )
    assert code2 == 0
    assert report2["status"] == "READY"
    assert not out.exists()


def _stage8_database(tmp_path: Path) -> Path:
    """Build a small formal Stage 8 DB with two limit-up events."""
    source = tmp_path / "source.duckdb"
    output = tmp_path / "stage8.duckdb"
    (tmp_path / "sql").mkdir()
    (tmp_path / "config").mkdir()
    import shutil

    shutil.copyfile(ROOT / "sql/stage8_schema.sql", tmp_path / "sql/stage8_schema.sql")
    shutil.copyfile(
        ROOT / "config/metric_definition.yml",
        tmp_path / "config/metric_definition.yml",
    )
    config = {
        "schema_version": "1.0.0",
        "price_adjust_type": "raw",
        "rounding_rules": {"supported": ["half_up", "half_even"]},
        "formal_evidence_status": "verified",
        "formal_quality_status": "pass",
        "unresolved_policy": "block_formal_annual_statistics",
        "rule_records": [
            {
                "exchange": "SZ", "board": "main", "is_st": False,
                "effective_start": "2020-01-01", "effective_end": None,
                "limit_up_ratio": 0.1, "limit_down_ratio": 0.1,
                "no_limit_flag": False, "tick_size": 0.01,
                "price_precision": 2, "rounding_rule": "half_up",
                "rule_version": "fixture-rule", "source_reference": "fixture://rule",
                "source_name": "fixture", "verified_at": "2026-01-01",
                "evidence_status": "verified",
            },
            {
                "exchange": "SH", "board": "main", "is_st": False,
                "effective_start": "2020-01-01", "effective_end": None,
                "limit_up_ratio": 0.1, "limit_down_ratio": 0.1,
                "no_limit_flag": False, "tick_size": 0.01,
                "price_precision": 2, "rounding_rule": "half_up",
                "rule_version": "fixture-rule-sh", "source_reference": "fixture://rule",
                "source_name": "fixture", "verified_at": "2026-01-01",
                "evidence_status": "verified",
            },
        ],
        "security_status_records": [
            {
                "symbol": "002067", "effective_start": "2020-01-01",
                "effective_end": None, "exchange": "SZ", "board": "main",
                "is_st": False, "listing_status": "listed",
                "listing_date": "2006-09-15", "delisting_date": None,
                "no_limit_reason": None, "source_reference": "fixture://status",
                "status_version": "fixture-status", "evidence_status": "verified",
            },
            {
                "symbol": "600763", "effective_start": "2020-01-01",
                "effective_end": None, "exchange": "SH", "board": "main",
                "is_st": False, "listing_status": "listed",
                "listing_date": "1996-10-30", "delisting_date": None,
                "no_limit_reason": None, "source_reference": "fixture://status",
                "status_version": "fixture-status-sh", "evidence_status": "verified",
            },
        ],
    }
    config_path = tmp_path / "stage8.yml"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    with duckdb.connect(str(source)) as connection:
        connection.execute(
            "CREATE TABLE fact_stock_daily("
            "symbol VARCHAR, exchange VARCHAR, trade_date DATE, adjust_type VARCHAR, "
            "open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume_share DOUBLE)"
        )
        connection.executemany(
            "INSERT INTO fact_stock_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("002067", "SZ", "2025-12-31", "raw", 10, 10, 10, 10, 100),
                ("002067", "SZ", "2026-01-02", "raw", 11, 11, 11, 11, 100),
                ("002067", "SZ", "2026-01-05", "raw", 11, 11, 11, 11, 100),
                ("600763", "SH", "2025-12-31", "raw", 20, 20, 20, 20, 100),
                ("600763", "SH", "2026-01-02", "raw", 22, 22, 22, 22, 100),
                ("600763", "SH", "2026-01-05", "raw", 22, 22, 22, 22, 100),
            ],
        )
    from akshare_data_test.stage8_build import analyze_stage8

    report, exit_code = analyze_stage8(
        root=tmp_path,
        config_path=config_path,
        source_database=source,
        output_database=output,
        as_of_date=pd.Timestamp("2026-01-05"),
        start_date=pd.Timestamp("2026-01-01"),
        run_id="s14-events",
        reports_dir=tmp_path / "reports",
    )
    assert exit_code == 0
    assert report["run_status"] == "PASS"
    assert report["formal_event_count"] == 2
    return output


def test_s14_reverify_uses_real_stage8_events(tmp_path):
    stage8 = _stage8_database(tmp_path)
    reports = tmp_path / "stage15"
    reports.mkdir()
    pd.DataFrame(
        [
            {
                "run_id": "stage15-run",
                "symbol": "002067",
                "check_item": "recent_limit_up_day",
                "observed_value": "2026-01-02",
                "source_table": "analysis.fact_limit_event",
                "as_of_date": "2026-01-05",
                "verification_status": "REVIEW",
                "note": "",
            },
            {
                "run_id": "stage15-run",
                "symbol": "002067",
                "check_item": "next_day_open_after_limit_up",
                "observed_value": "11.0",
                "source_table": "analysis.fact_limit_event",
                "as_of_date": "2026-01-05",
                "verification_status": "REVIEW",
                "note": "",
            },
            {
                "run_id": "stage15-run",
                "symbol": "600763",
                "check_item": "recent_limit_up_day",
                "observed_value": "2026-01-02",
                "source_table": "analysis.fact_limit_event",
                "as_of_date": "2026-01-05",
                "verification_status": "REVIEW",
                "note": "",
            },
            {
                "run_id": "stage15-run",
                "symbol": "600763",
                "check_item": "next_day_open_after_limit_up",
                "observed_value": "22.0",
                "source_table": "analysis.fact_limit_event",
                "as_of_date": "2026-01-05",
                "verification_status": "REVIEW",
                "note": "",
            },
        ]
    ).to_csv(reports / "cross_validation.csv", index=False, encoding="utf-8-sig")
    out = tmp_path / "s14"
    report, exit_code = verify_s14(
        stage8_database=stage8,
        stage15_reports_dir=reports,
        output_dir=out,
        as_of_date=date(2026, 1, 5),
        run_id="s14-verify",
    )
    assert exit_code == 0
    assert report["status"] == "PASS"
    assert report["valid_sample_count"] == 2
    assert report["unavailable_count"] == 0
    frame = pd.read_csv(out / "s14_verification.csv", dtype={"symbol": str})
    assert set(frame["symbol"]) == {"002067", "600763"}
    assert (frame["manual_check_result"] == "REVIEW").all()
    assert (frame["previous_close"].astype(float) == [10.0, 20.0]).all()
    assert (frame["rule_version"].isin(["fixture-rule", "fixture-rule-sh"])).all()
    assert (frame["security_status_version"].isin(
        ["fixture-status", "fixture-status-sh"]
    )).all()


def test_s14_reverify_fails_closed_without_two_samples(tmp_path):
    stage8 = _stage8_database(tmp_path)
    reports = tmp_path / "stage15"
    reports.mkdir()
    pd.DataFrame(
        [
            {
                "run_id": "stage15-run",
                "symbol": "002067",
                "check_item": "recent_limit_up_day",
                "observed_value": "unavailable",
                "source_table": "analysis.fact_limit_event",
                "as_of_date": "2026-01-05",
                "verification_status": "UNAVAILABLE",
                "note": "",
            }
        ]
    ).to_csv(reports / "cross_validation.csv", index=False, encoding="utf-8-sig")
    report, exit_code = verify_s14(
        stage8_database=stage8,
        stage15_reports_dir=reports,
        output_dir=tmp_path / "s14-blocked",
        as_of_date=date(2026, 1, 5),
        run_id="s14-blocked",
    )
    assert exit_code == 2
    assert report["status"] == "BLOCKED"


def test_s14_reverify_validate_only_is_ready_without_outputs(tmp_path):
    stage8 = _stage8_database(tmp_path)
    reports = tmp_path / "stage15"
    reports.mkdir()
    (reports / "cross_validation.csv").write_text(
        "run_id,symbol,check_item,observed_value,source_table,"
        "as_of_date,verification_status,note\n",
        encoding="utf-8-sig",
    )
    out = tmp_path / "s14-validate"
    report, exit_code = verify_s14(
        stage8_database=stage8,
        stage15_reports_dir=reports,
        output_dir=out,
        as_of_date=date(2026, 1, 5),
        run_id="s14-validate",
        validate_only=True,
    )
    assert exit_code == 0
    assert report["status"] == "READY"
    assert report["formal_event_count"] == 2
    assert not out.exists()


def test_new_cli_commands_exist_in_help():
    result = subprocess.run(
        [sys.executable, "run_pipeline.py", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    for command in (
        "stage8-source-probe",
        "stage8-rules-build",
        "stage8-status-build",
        "stage8-preflight",
        "stage8-rebuild",
        "stage15-rerun",
        "stage15-s14-reverify",
    ):
        assert command in result.stdout


def test_source_probe_validate_only_prints_plan_without_network():
    result = subprocess.run(
        [
            sys.executable,
            "run_pipeline.py",
            "stage8-source-probe",
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
    assert payload["status"] == "VALIDATE_ONLY"
    names = {item["interface"] for item in payload["plan"]}
    assert "stock_info_sz_change_name_short" in names
    assert "stock_zh_a_st_em" in names


def test_source_probe_feasibility_report_is_deterministic(tmp_path):
    from akshare_data_test.adapters.status_probe import write_feasibility_report

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    manifest = {
        "run_id": "probe-run",
        "as_of_date": "2026-07-27",
        "fetched_at": "2026-08-05T00:00:00+00:00",
        "akshare_version": "1.18.80",
        "probes": [
            {
                "source_name": "深交所简称变更",
                "interface": "stock_info_sz_change_name_short",
                "probe_status": "success",
                "rows": 2,
                "raw_columns": ["变更日期", "证券代码", "证券简称"],
                "normalized_columns": ["change_date", "security_code", "security_short_name"],
                "column_mapping": {
                    "变更日期": "change_date",
                    "证券代码": "security_code",
                    "证券简称": "security_short_name",
                },
                "mapping_status": "MAPPED",
                "mapping_errors": [],
                "snapshot_or_history": "history",
                "date_coverage": {
                    "has_dates": True,
                    "start": "2025-08-01",
                    "end": "2026-07-27",
                },
                "exchange_coverage": "SZSE",
                "sample_coverage": "full_market",
                "source_grade": "B",
                "authoritative": False,
                "can_build_limit_rules": False,
                "can_build_security_status": False,
                "auxiliary_only": True,
                "blocking_reason": "auxiliary_only_not_complete_status_history",
                "raw_file": "stock_info_sz_change_name_short.csv",
                "sha256": "a" * 64,
            },
            {
                "source_name": "东方财富风险警示板",
                "interface": "stock_zh_a_st_em",
                "probe_status": "failed",
                "rows": 0,
                "raw_columns": [],
                "normalized_columns": [],
                "column_mapping": {},
                "mapping_status": "UNMAPPED",
                "mapping_errors": [],
                "snapshot_or_history": "snapshot",
                "date_coverage": {"has_dates": False, "start": "", "end": ""},
                "exchange_coverage": "沪深",
                "sample_coverage": "full_market",
                "source_grade": "C",
                "authoritative": False,
                "can_build_limit_rules": False,
                "can_build_security_status": False,
                "auxiliary_only": True,
                "blocking_reason": "interface_failure:connection_error",
                "raw_file": "",
                "sha256": "",
            },
        ],
    }
    (evidence / "probe_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )
    out = tmp_path / "out"
    summary = write_feasibility_report(
        evidence, out, run_id="probe-run", as_of_date=date(2026, 7, 27)
    )
    assert summary["authoritative_rule_source_ready"] is False
    assert summary["authoritative_status_source_ready"] is False
    assert summary["can_continue_rules_build"] is False
    assert summary["can_continue_status_build"] is False
    assert summary["grade_counts"] == {"A": 0, "B": 1, "C": 1}
    assert "no_authoritative_rule_source" in summary["blocking_reasons"]
    assert "no_authoritative_status_history_source" in summary["blocking_reasons"]
    for name in (
        "source_grade_summary.json",
        "column_mapping.json",
        "source_feasibility.csv",
        "source_feasibility.md",
    ):
        assert (out / name).is_file()
    csv_frame = pd.read_csv(out / "source_feasibility.csv")
    expected_columns = [
        "source_name", "interface", "probe_status", "rows", "raw_columns",
        "normalized_columns", "snapshot_or_history", "date_coverage",
        "exchange_coverage", "sample_coverage", "source_grade",
        "authoritative", "can_build_limit_rules", "can_build_security_status",
        "auxiliary_only", "blocking_reason", "raw_file", "sha256",
    ]
    assert list(csv_frame.columns) == expected_columns
    assert "深交所简称变更" in csv_frame["source_name"].tolist()
    mapping = json.loads(
        (out / "column_mapping.json").read_text(encoding="utf-8-sig")
    )
    assert mapping["interfaces"][0]["column_mapping"]["变更日期"] == "change_date"
    for name in ("source_grade_summary.json", "column_mapping.json"):
        json.loads((out / name).read_text(encoding="utf-8-sig"))


def test_safe_json_write_handles_utf8_columns_and_escapes(tmp_path):
    from akshare_data_test.adapters.status_probe import _safe_json_write

    payload = {
        "中文列名": "证券简称",
        "quote\"col": "value with \"quotes\"",
        "line\nbreak": "first\nsecond",
        "back\\slash": "C:\\路径\\文件",
        "列表": ["中文", "a,b", "x\"y"],
        "空值": None,
        "日期": pd.Timestamp("2026-07-27"),
    }
    path = tmp_path / "中文路径" / "artifact.json"
    reparsed = _safe_json_write(path, payload)
    assert reparsed["中文列名"] == "证券简称"
    assert reparsed["quote\"col"] == 'value with "quotes"'
    assert reparsed["line\nbreak"] == "first\nsecond"
    assert reparsed["back\\slash"] == "C:\\路径\\文件"
    assert reparsed["日期"] == "2026-07-27T00:00:00"
    json.loads(path.read_text(encoding="utf-8-sig"))


def test_empty_dataframe_columns_and_unmapped_columns(tmp_path):
    from akshare_data_test.adapters.status_probe import (
        _build_probe_entry,
        _column_mapping,
    )

    mapping = _column_mapping(
        "stock_info_sz_change_name_short",
        ["变更日期", "证券代码", "未来新增字段"],
    )
    assert mapping["mapping_status"] == "PARTIAL"
    assert mapping["column_mapping"]["变更日期"] == "change_date"
    assert mapping["column_mapping"]["未来新增字段"] == "UNMAPPED"
    assert mapping["mapping_errors"] == ["unmapped_column:未来新增字段"]
    empty_mapping = _column_mapping("cninfo_risk_warning", [])
    assert empty_mapping["mapping_status"] == "UNMAPPED"
    plan = {
        "name": "cninfo_risk_warning",
        "source_name": "巨潮资讯风险警示公告检索",
        "params": {"symbols": [], "keyword": "风险警示"},
        "scope": "per_symbol",
        "category": "announcement_search",
        "note": "",
    }
    entry = _build_probe_entry(
        plan=plan,
        frame=pd.DataFrame(columns=["代码", "简称"]),
        status="empty",
    )
    assert entry["probe_status"] == "empty"
    assert entry["source_grade"] == "C"
    assert entry["blocking_reason"] == "empty_result_cannot_prove_no_data"


def test_probe_grading_is_conservative(tmp_path):
    from akshare_data_test.adapters.status_probe import _build_probe_entry

    plan = {
        "name": "stock_info_sz_change_name_short",
        "source_name": "深交所简称变更",
        "params": {"kind": "简称变更"},
        "scope": "full_market",
        "category": "name_change_history",
        "note": "",
    }
    frame = pd.DataFrame(
        {
            "变更日期": ["2025-08-01"],
            "证券代码": ["002067"],
            "证券简称": ["景兴纸业"],
            "变更前简称": ["景兴纸业"],
            "变更后简称": ["景兴纸业"],
        }
    )
    raw = tmp_path / "raw.csv"
    frame.to_csv(raw, index=False, encoding="utf-8-sig")
    entry = _build_probe_entry(
        plan=plan, frame=frame, status="success", raw_file=raw
    )
    assert entry["source_grade"] == "B"
    assert entry["authoritative"] is False
    assert entry["can_build_security_status"] is False
    assert entry["can_build_limit_rules"] is False
    assert entry["mapping_status"] == "MAPPED"
    failed = _build_probe_entry(
        plan=plan,
        frame=None,
        status="failed",
        error_type="connection_error",
        error_message="RemoteDisconnected",
    )
    assert failed["source_grade"] == "C"
    assert "interface_failure:connection_error" in failed["blocking_reason"]


def test_invalid_probe_manifest_is_not_published(tmp_path):
    from akshare_data_test.adapters.status_probe import write_feasibility_report

    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "probe_manifest.json").write_text(
        '{"broken": "json,', encoding="utf-8"
    )
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="invalid or unreadable"):
        write_feasibility_report(
            evidence, out, run_id="probe-run", as_of_date=date(2026, 7, 27)
        )
    assert not out.exists()


def test_cli_returns_nonzero_on_invalid_manifest(tmp_path, monkeypatch):
    import types

    from akshare_data_test import cli
    from akshare_data_test.adapters import status_probe

    monkeypatch.setattr(cli, "project_root", lambda: tmp_path)

    def fake_suite(output_dir, *, as_of_date, run_id=None):
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "probe_manifest.json").write_text(
            "{broken json,", encoding="utf-8"
        )
        return {"interfaces_probed": []}

    monkeypatch.setattr(status_probe, "probe_source_suite", fake_suite)
    args = types.SimpleNamespace(
        as_of_date="2026-07-27",
        run_id="6b7c8d9e-0f1a-4b2c-9d3e-4f5a6b7c8d9e",
        output_dir="out",
        validate_only=False,
        log_level="INFO",
        debug=False,
    )
    assert cli._cmd_stage8_source_probe(args) == 1
    run_dir = tmp_path / "out" / "6b7c8d9e-0f1a-4b2c-9d3e-4f5a6b7c8d9e"
    assert not (run_dir / "source_grade_summary.json").exists()
    assert not (run_dir / "column_mapping.json").exists()
    assert not (run_dir / "source_feasibility.csv").exists()
