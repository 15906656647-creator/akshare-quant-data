"""Offline Stage 8 orchestration with fail-closed publication status."""
from __future__ import annotations

import json
import hashlib
import subprocess
import uuid
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .limit_event_detection import detect_limit_events, formal_events
from .limit_rules import (
    LimitRule,
    SecurityStatus,
    validate_rule_intervals,
    validate_status_intervals,
)
from .quality.limit_event_checks import (
    run_stage8_post_write_checks,
    run_stage8_quality_checks,
)
from .stage8_analysis import (
    FORMAL_SUMMARY_COLUMNS,
    apply_publication_status,
    decide_publication,
    summarize_annual_events,
)
from .storage.limit_event_repository import (
    EVENT_COLUMNS,
    finalize_stage8_results,
    read_raw_daily,
    upsert_stage8_results,
    validate_output_target,
    validate_raw_daily_source,
)


def _parse_date(value: object, *, required: bool = False) -> date | None:
    if value in (None, ""):
        if required:
            raise ValueError("Required effective date is missing")
        return None
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _strict_bool(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} must be a YAML boolean")
    return value


def _required_text(value: object, field: str) -> str:
    """Validate text before conversion so YAML null never becomes ``"None"``."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _strict_int(value: object, field: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{field} must be a YAML integer")
    return value


def _reject_unknown_fields(
    item: dict[str, Any], allowed: set[str], record_type: str
) -> None:
    unknown = sorted(set(item).difference(allowed))
    if unknown:
        raise ValueError(f"Unknown {record_type} fields: {unknown}")


def load_stage8_config(path: Path) -> tuple[dict[str, Any], list[LimitRule], list[SecurityStatus]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("price_adjust_type") != "raw":
        raise ValueError("Stage 8 config must explicitly require raw prices")
    _reject_unknown_fields(
        raw,
        {
            "schema_version", "price_adjust_type", "rounding_rules",
            "formal_evidence_status", "formal_quality_status",
            "unresolved_policy", "rule_records", "security_status_records",
            "source_notes",
        },
        "stage8 config",
    )
    rounding = raw.get("rounding_rules")
    if not isinstance(rounding, dict) or set(rounding) != {"supported"}:
        raise ValueError("rounding_rules must contain only a supported list")
    supported_rounding = rounding["supported"]
    if (
        not isinstance(supported_rounding, list)
        or not supported_rounding
        or any(not isinstance(item, str) or not item for item in supported_rounding)
    ):
        raise ValueError("rounding_rules.supported must be a non-empty string list")
    if raw.get("formal_evidence_status") != "verified":
        raise ValueError("formal_evidence_status must be verified")
    if raw.get("formal_quality_status") != "pass":
        raise ValueError("formal_quality_status must be pass")
    if raw.get("unresolved_policy") != "block_formal_annual_statistics":
        raise ValueError("unresolved_policy must be block_formal_annual_statistics")
    if not isinstance(raw.get("rule_records"), list):
        raise ValueError("rule_records must be a list")
    if not isinstance(raw.get("security_status_records"), list):
        raise ValueError("security_status_records must be a list")
    rule_allowed = {
        "exchange", "board", "is_st", "effective_start", "effective_end",
        "limit_up_ratio", "limit_down_ratio", "no_limit_flag", "tick_size",
        "price_precision", "rounding_rule", "rule_version",
        "source_reference", "source_name", "verified_at", "evidence_status",
    }
    status_allowed = {
        "symbol", "effective_start", "effective_end", "exchange", "board",
        "is_st", "listing_status", "listing_date", "delisting_date",
        "no_limit_reason", "source_reference", "status_version",
        "evidence_status",
    }
    rules = []
    for item in raw.get("rule_records", []):
        if not isinstance(item, dict):
            raise ValueError("Each rule record must be a mapping")
        _reject_unknown_fields(item, rule_allowed, "rule")
        parsed_rule = LimitRule(
            exchange=_required_text(item.get("exchange"), "exchange"),
            board=_required_text(item.get("board"), "board"),
            is_st=_strict_bool(item["is_st"], "is_st"),
            effective_start=_parse_date(item["effective_start"], required=True),
            effective_end=_parse_date(item.get("effective_end")),
            limit_up_ratio=Decimal(str(item["limit_up_ratio"])) if item.get("limit_up_ratio") is not None else None,
            limit_down_ratio=Decimal(str(item["limit_down_ratio"])) if item.get("limit_down_ratio") is not None else None,
            no_limit_flag=_strict_bool(item["no_limit_flag"], "no_limit_flag"),
            tick_size=Decimal(str(item["tick_size"])),
            price_precision=_strict_int(item.get("price_precision"), "price_precision"),
            rounding_rule=_required_text(item.get("rounding_rule"), "rounding_rule"),
            rule_version=_required_text(item.get("rule_version"), "rule_version"),
            source_reference=_required_text(
                item.get("source_reference"), "source_reference"
            ),
            source_name=_required_text(item.get("source_name"), "source_name"),
            verified_at=_parse_date(item.get("verified_at")),
            evidence_status=_required_text(
                item.get("evidence_status", "unverified"), "evidence_status"
            ),
        )
        if parsed_rule.rounding_rule not in supported_rounding:
            raise ValueError(
                f"rounding_rule {parsed_rule.rounding_rule!r} is not enabled "
                "by rounding_rules.supported"
            )
        rules.append(parsed_rule)
    statuses = []
    for item in raw.get("security_status_records", []):
        if not isinstance(item, dict):
            raise ValueError("Each security status record must be a mapping")
        _reject_unknown_fields(item, status_allowed, "security status")
        is_st = item.get("is_st")
        if is_st is not None:
            is_st = _strict_bool(is_st, "is_st")
        statuses.append(SecurityStatus(
            symbol=_required_text(item.get("symbol"), "symbol").zfill(6),
            effective_start=_parse_date(item["effective_start"], required=True),
            effective_end=_parse_date(item.get("effective_end")),
            exchange=_required_text(item.get("exchange"), "exchange"),
            board=_required_text(item.get("board"), "board"),
            is_st=is_st,
            listing_status=_required_text(
                item.get("listing_status"), "listing_status"
            ),
            listing_date=_parse_date(item.get("listing_date")),
            delisting_date=_parse_date(item.get("delisting_date")),
            no_limit_reason=item.get("no_limit_reason"),
            source_reference=_required_text(
                item.get("source_reference"), "source_reference"
            ),
            status_version=_required_text(
                item.get("status_version"), "status_version"
            ),
            evidence_status=_required_text(
                item.get("evidence_status", "unverified"), "evidence_status"
            ),
        ))
    validate_rule_intervals(rules)
    validate_status_intervals(statuses)
    return raw, rules, statuses


def validate_stage8_inputs(
    *,
    config_path: Path,
    source_database: Path,
    output_database: Path,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> dict[str, Any]:
    """Perform a read-only preflight; never create an output or source file."""
    errors: list[str] = []
    blockers: list[str] = []
    try:
        _, rules, statuses = load_stage8_config(config_path)
    except Exception as exc:
        rules, statuses = [], []
        errors.append(f"stage8_config_invalid:{exc}")
    source = validate_raw_daily_source(
        source_database, start_date=start_date, end_date=end_date
    )
    errors.extend(source.get("errors", []))
    blockers.extend(source.get("blockers", []))
    errors.extend(validate_output_target(source_database, output_database))
    verified_rules = [item for item in rules if item.evidence_status == "verified"]
    verified_statuses = [
        item for item in statuses if item.evidence_status == "verified"
    ]
    if not verified_rules:
        blockers.append("no_authoritative_limit_rules")
    if not verified_statuses:
        blockers.append("no_authoritative_security_status_history")
    status = "FAILED" if errors else ("BLOCKED" if blockers else "READY")
    return {
        "status": status,
        "rule_count": len(rules),
        "verified_rule_count": len(verified_rules),
        "security_status_count": len(statuses),
        "verified_security_status_count": len(verified_statuses),
        "input_database": str(source_database),
        "input_table": source.get("input_table"),
        "input_price_routes": source.get("input_price_routes", []),
        "window_start": start_date.date(),
        "window_end": end_date.date(),
        "range_row_count": source.get("range_row_count"),
        "raw_row_count": source.get("raw_row_count"),
        "errors": sorted(set(errors)),
        "blockers": sorted(set(blockers)),
    }


def _lookback_days(root: Path) -> int:
    path = root / "config" / "metric_definition.yml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    value = raw["data_ranges"]["limit_event"]["lookback_natural_days"]
    if type(value) is not int or value <= 0:
        raise ValueError("limit_event.lookback_natural_days must be a positive integer")
    return value


def _config_hash(root: Path, config_path: Path) -> str:
    digest = hashlib.sha256()
    for path in (root / "config" / "metric_definition.yml", config_path):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _code_version(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _write_reports(
    root: Path,
    observations: pd.DataFrame,
    summary: pd.DataFrame,
    quality: pd.DataFrame,
    report: dict[str, Any],
) -> None:
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    observations.reindex(columns=EVENT_COLUMNS).head(100).to_csv(
        reports / "stage8_event_sample.csv", index=False, encoding="utf-8-sig"
    )
    summary.to_csv(
        reports / "stage8_annual_event_summary.csv", index=False, encoding="utf-8-sig"
    )
    quality.to_csv(
        reports / "stage8_data_quality.csv", index=False, encoding="utf-8-sig"
    )
    pd.DataFrame([{
        "run_id": report["run_id"],
        "rule_count": report["rule_count"],
        "verified_rule_count": report["verified_rule_count"],
        "numerator": report["rule_coverage_numerator"],
        "denominator": report["rule_coverage_denominator"],
        "ratio": report["rule_coverage_ratio"],
        "coverage_status": report["publication_status"],
    }]).to_csv(reports / "stage8_rule_coverage.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame([{
        "run_id": report["run_id"],
        "security_status_count": report["security_status_count"],
        "numerator": report["status_coverage_numerator"],
        "denominator": report["status_coverage_denominator"],
        "ratio": report["status_coverage_ratio"],
        "coverage_status": report["publication_status"],
    }]).to_csv(reports / "stage8_security_status_coverage.csv", index=False, encoding="utf-8-sig")
    (reports / "stage8_run.json").write_text(
        json.dumps(
            report, ensure_ascii=False, indent=2, default=str, allow_nan=False
        ) + "\n",
        encoding="utf-8",
    )
    formal_event_label = (
        "not_calculated"
        if report["formal_event_count"] is None
        else str(report["formal_event_count"])
    )
    annual_summary_lines = []
    for row in report["annual_summary"]:
        symbol = row.get("symbol", "unknown")
        for field in FORMAL_SUMMARY_COLUMNS:
            value = row.get(field)
            annual_summary_lines.append(
                f"- {symbol}.{field}: "
                + ("not_calculated" if value is None else str(value))
            )
    annual_summary_text = "\n".join(annual_summary_lines) or "- not_available"
    document = f"""# 阶段 8 涨跌停统计与事件研究验证

- 状态：**{report["run_status"]}**
- run_id：`{report["run_id"]}`
- 输出类型：`{report["output_type"]}`（fixture 绝非正式结果）
- 价格口径：`{report["input_price_route"]}`（不复权真实交易价格）
- 时间范围：{report["window_start"]} 至 {report["window_end"]}
- 正式事件：{formal_event_label}
- candidate：{report["candidate_count"]}
- unresolved：{report["unresolved_count"]}
- 规则版本数：{report["rule_count"]}
- 规则来源：{", ".join(report["rule_sources"]) or "缺失"}
- 证券状态来源：{", ".join(report["security_status_sources"]) or "缺失"}
- 全年统计发布状态：`{report["publication_status"]}`

## 阻塞项

{chr(10).join("- " + item for item in report["blockers"]) or "- 无"}

## 未决原因计数

{chr(10).join("- " + name + ": " + str(value) for name, value in report["unresolved_reason_counts"].items()) or "- 无"}

## Formal annual summary

{annual_summary_text}

## 质量检查

- 通过：{report["quality_passed"]}
- 失败：{report["quality_failed"]}
- ERROR 失败：{", ".join(report["failed_quality_checks"]) or "无"}

## 口径声明

`gap_proxy` 不是正式涨停或跌停事件；近期涨跌停池只能用于交叉校验。
只有规则、证券状态证据均已验证且质量检查通过的事件才进入正式统计。
无数据或未解决状态不会解释为 0 次涨停/跌停。本项目仅用于研究测试，
不构成投资建议。
"""
    (reports / "stage8_validation.md").write_text(document, encoding="utf-8")


def _quality_row(quality: pd.DataFrame, name: str) -> pd.Series | None:
    rows = quality.loc[quality["check_name"].eq(name)]
    return None if rows.empty else rows.iloc[-1]


def _report_summary_records(summary: pd.DataFrame) -> list[dict[str, Any]]:
    """Create strict JSON records; pandas missing values become JSON null."""
    return json.loads(summary.to_json(orient="records", date_format="iso"))


def _update_quality_manifest(
    report: dict[str, Any], quality: pd.DataFrame
) -> None:
    report["quality_passed"] = int(quality["status"].eq("PASS").sum())
    report["quality_failed"] = int(quality["status"].eq("FAIL").sum())
    report["quality_checks_passed"] = report["quality_passed"]
    report["quality_checks_total"] = len(quality)
    report["quality_results"] = json.loads(
        quality.to_json(orient="records", date_format="iso")
    )
    for check_name, prefix in (
        ("rule_coverage", "rule_coverage"),
        ("security_status_coverage", "status_coverage"),
    ):
        row = _quality_row(quality, check_name)
        numerator = None if row is None or pd.isna(row["numerator"]) else int(row["numerator"])
        denominator = None if row is None or pd.isna(row["denominator"]) else int(row["denominator"])
        report[prefix + "_numerator"] = numerator
        report[prefix + "_denominator"] = denominator
        report[prefix + "_ratio"] = (
            numerator / denominator if denominator else None
        )


def _audit_run(report: dict[str, Any]) -> dict[str, object]:
    """Map the shared manifest to the audit table contract."""
    return {
        "run_id": report["run_id"],
        "as_of_date": report["as_of_date"],
        "period_start": report["window_start"],
        "price_adjust_type": report["input_price_route"],
        "source_database": report["input_database"],
        "output_database": report["output_database"],
        "status": report["run_status"],
        "formal_event_count": report["formal_event_count"],
        "provisional_count": report["candidate_count"],
        "unresolved_count": report["unresolved_count"],
        "blockers": report["blocking_reasons"],
        "created_at": report["created_at"],
        "started_at": report["started_at"],
        "completed_at": report["completed_at"],
        "input_database": report["input_database"],
        "input_table": report["input_table"],
        "input_price_route": report["input_price_route"],
        "window_start": report["window_start"],
        "window_end": report["window_end"],
        "publication_status": report["publication_status"],
        "output_type": report["output_type"],
        "candidate_count": report["candidate_count"],
        "quality_passed": report["quality_passed"],
        "quality_failed": report["quality_failed"],
        "code_version": report["code_version"],
        "config_hash": report["config_hash"],
        "manifest_json": json.dumps(
            report, ensure_ascii=False, default=str, allow_nan=False
        ),
    }


def analyze_stage8(
    *,
    root: Path,
    config_path: Path,
    source_database: Path,
    output_database: Path,
    as_of_date: pd.Timestamp,
    start_date: pd.Timestamp | None = None,
    run_id: str | None = None,
    dry_run: bool = False,
) -> tuple[dict[str, Any], int]:
    started_at = pd.Timestamp.now(tz="UTC")
    end = pd.Timestamp(as_of_date).normalize()
    start = (
        pd.Timestamp(start_date).normalize()
        if start_date is not None
        else end - pd.Timedelta(days=_lookback_days(root))
    )
    validation = validate_stage8_inputs(
        config_path=config_path,
        source_database=source_database,
        output_database=output_database,
        start_date=start,
        end_date=end,
    )
    if validation["status"] == "FAILED":
        raise ValueError("; ".join(validation["errors"]))
    raw_config, rules, statuses = load_stage8_config(config_path)
    effective_run_id = run_id or str(uuid.uuid4())
    created_at = started_at
    # Read a bounded pre-period warm-up so the first in-period trading row can
    # use its actual previous trading close. Warm-up rows never enter outputs.
    daily, source_table = read_raw_daily(
        source_database, start_date=start - pd.Timedelta(days=31), end_date=end
    )
    detected = detect_limit_events(
        daily, rules, statuses, run_id=effective_run_id, created_at=created_at
    )
    observations = detected.loc[
        pd.to_datetime(detected["trade_date"]).between(start, end)
    ].reset_index(drop=True)
    summary, _, summary_blockers = summarize_annual_events(
        observations, start_date=start, end_date=end
    )
    summary["run_id"] = effective_run_id
    summary["created_at"] = created_at
    quality = run_stage8_quality_checks(
        observations,
        summary,
        run_id=effective_run_id,
        created_at=created_at,
        input_price_routes=set(daily["adjust_type"].dropna().astype(str).str.lower()),
    )
    decision = decide_publication(
        observations,
        quality,
        base_blockers=validation["blockers"] + summary_blockers,
    )
    blockers = list(decision.blocking_reasons)
    summary = apply_publication_status(summary, decision.publication_status)
    detected_formal_count = len(formal_events(observations))
    reason_counts = {
        str(name): int(value)
        for name, value in observations["resolution_reason"]
        .dropna()
        .value_counts()
        .sort_index()
        .items()
    }
    candidate_count = int(
        observations["event_type"].isin(["candidate", "proxy", "gap_proxy"]).sum()
    )
    unresolved_count = int(
        (
            observations["event_type"].eq("unresolved")
            | observations["evidence_status"].eq("unresolved")
        ).sum()
    )
    source_references = [
        *[rule.source_reference for rule in rules],
        *[status.source_reference for status in statuses],
    ]
    output_type = (
        "fixture"
        if source_references
        and all(str(item).startswith("fixture://") for item in source_references)
        else ("formal" if decision.publication_status == "formal" else "validation")
    )
    report = {
        "status": decision.run_status,
        "run_status": decision.run_status,
        "run_id": effective_run_id,
        "created_at": created_at,
        "started_at": started_at,
        "completed_at": pd.Timestamp.now(tz="UTC"),
        "as_of_date": end.date(),
        "period_start": start.date(),
        "window_start": start.date(),
        "window_end": end.date(),
        "price_adjust_type": "raw",
        "input_price_route": "raw",
        "source_database": str(source_database),
        "source_table": source_table,
        "input_database": str(source_database),
        "input_table": source_table,
        "output_database": str(output_database),
        "output_type": output_type,
        "rule_count": len(rules),
        "verified_rule_count": sum(rule.evidence_status == "verified" for rule in rules),
        "security_status_count": len(statuses),
        "rule_sources": sorted({rule.source_reference for rule in rules}),
        "security_status_sources": sorted({status.source_reference for status in statuses}),
        "rule_versions": sorted({rule.rule_version for rule in rules}),
        "rule_source_summary": sorted({rule.source_reference for rule in rules}),
        "security_status_versions": sorted(
            {status.status_version for status in statuses}
        ),
        "security_status_source_summary": sorted(
            {status.source_reference for status in statuses}
        ),
        "observation_count": len(observations),
        "formal_event_count": (
            detected_formal_count
            if decision.publication_status == "formal"
            else None
        ),
        "detected_formal_event_count": (
            detected_formal_count
            if decision.publication_status == "formal"
            else None
        ),
        "annual_summary": _report_summary_records(summary),
        "candidate_count": candidate_count,
        "provisional_count": candidate_count,
        "unresolved_count": unresolved_count,
        "unresolved_reason_counts": reason_counts,
        "missing_rule_count": reason_counts.get("missing_rule", 0),
        "missing_status_count": reason_counts.get("missing_security_status", 0),
        "missing_previous_close_count": reason_counts.get("missing_previous_close", 0),
        "no_limit_count": reason_counts.get("no_limit_period", 0),
        "invalid_trade_row_count": reason_counts.get("invalid_trade_row", 0),
        "insufficient_forward_sample_count": int(
            observations["forward_sample_status"].ne("complete").sum()
        ),
        "publication_status": decision.publication_status,
        "failed_quality_checks": list(decision.failed_quality_checks),
        "blocking_reasons": blockers,
        "blockers": blockers,
        "code_version": _code_version(root),
        "config_hash": _config_hash(root, config_path),
        "formal_evidence_status": raw_config["formal_evidence_status"],
        "formal_quality_status": raw_config["formal_quality_status"],
        "unresolved_policy": raw_config["unresolved_policy"],
        "rounding_rules_supported": raw_config["rounding_rules"]["supported"],
        "dry_run": dry_run,
    }
    _update_quality_manifest(report, quality)
    if not dry_run:
        upsert_stage8_results(
            database_path=output_database,
            schema_sql_path=root / "sql" / "stage8_schema.sql",
            rules=rules,
            statuses=statuses,
            observations=observations,
            summary=summary,
            quality=quality,
            run=_audit_run(report),
        )
        # Persist the first complete artifact set before validating it.  The
        # post-write check reads these files; it must not merely trust the
        # in-memory frames that produced them.
        _write_reports(root, observations, summary, quality, report)
        post_write_quality = run_stage8_post_write_checks(
            output_database,
            run_id=effective_run_id,
            expected_event_rows=len(observations),
            expected_summary_rows=len(summary),
            expected_formal_events=detected_formal_count,
            expected_publication_status=decision.publication_status,
            expected_report_formal_event_count=report["formal_event_count"],
            checked_at=created_at,
            reports_dir=root / "reports",
        )
        quality = pd.concat(
            [quality, post_write_quality], ignore_index=True
        )
        decision = decide_publication(
            observations,
            quality,
            base_blockers=validation["blockers"] + summary_blockers,
        )
        blockers = list(decision.blocking_reasons)
        summary = apply_publication_status(summary, decision.publication_status)
        report.update(
            status=decision.run_status,
            run_status=decision.run_status,
            publication_status=decision.publication_status,
            formal_event_count=(
                detected_formal_count
                if decision.publication_status == "formal"
                else None
            ),
            detected_formal_event_count=(
                detected_formal_count
                if decision.publication_status == "formal"
                else None
            ),
            annual_summary=_report_summary_records(summary),
            failed_quality_checks=list(decision.failed_quality_checks),
            blocking_reasons=blockers,
            blockers=blockers,
            completed_at=pd.Timestamp.now(tz="UTC"),
        )
        _update_quality_manifest(report, quality)
        finalize_stage8_results(
            database_path=output_database,
            summary=summary,
            quality=quality,
            run=_audit_run(report),
        )
        _write_reports(root, observations, summary, quality, report)
    return report, decision.exit_code
