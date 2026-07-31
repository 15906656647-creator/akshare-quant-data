"""Measured Stage 8 quality checks and post-write verification."""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path

import duckdb
import pandas as pd


QUALITY_COLUMNS = [
    "run_id", "check_name", "severity", "status", "observed_value",
    "expected_value", "numerator", "denominator", "message", "checked_at",
]
EVENT_TABLE = "fact_limit_" + "event"
FORMAL_SUMMARY_FIELDS = [
    "limit_up_count", "limit_down_count",
    "avg_next_open_return_after_limit_up",
    "avg_next_close_return_after_limit_up",
    "avg_forward_3d_return_after_limit_up",
    "avg_forward_5d_return_after_limit_up",
    "avg_forward_10d_return_after_limit_up",
    "next_day_gap_up_ratio", "continued_limit_ratio", "formal_event_count",
]


def _normalized(value: object) -> object:
    """Normalize cross-format scalar values without treating numeric zero as null."""
    if value is None:
        return None
    if isinstance(value, str) and value == "":
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (pd.Timestamp, datetime, date)):
        if isinstance(value, date) and not isinstance(value, (pd.Timestamp, datetime)):
            return value.isoformat()
        return value.date().isoformat()
    return value


def _summary_projection(records: list[dict[str, object]]) -> list[dict[str, object]]:
    fields = [
        "symbol", "period_start", "period_end", *FORMAL_SUMMARY_FIELDS,
        "publication_status", "run_id",
    ]
    projected = [
        {
            field: (
                pd.Timestamp(record.get(field)).date().isoformat()
                if field in {"period_start", "period_end"}
                and _normalized(record.get(field)) is not None
                else _normalized(record.get(field))
            )
            for field in fields
        }
        for record in records
    ]
    return sorted(projected, key=lambda row: (str(row["symbol"]), str(row["period_start"])))


def _record_projection(
    records: list[dict[str, object]], fields: list[str], sort_fields: list[str]
) -> list[dict[str, object]]:
    projected = [
        {field: _normalized(record.get(field)) for field in fields}
        for record in records
    ]
    return sorted(
        projected, key=lambda row: tuple(str(row[field]) for field in sort_fields)
    )


def _check(
    *,
    run_id: str,
    name: str,
    passed: bool,
    severity: str,
    observed: object,
    expected: object,
    numerator: int | None,
    denominator: int | None,
    message: str,
    checked_at: pd.Timestamp,
) -> dict[str, object]:
    return {
        "run_id": run_id,
        "check_name": name,
        "severity": severity,
        "status": "PASS" if passed else "FAIL",
        "observed_value": str(observed),
        "expected_value": str(expected),
        "numerator": numerator,
        "denominator": denominator,
        "message": message,
        "checked_at": checked_at,
    }


def run_stage8_quality_checks(
    observations: pd.DataFrame,
    summary: pd.DataFrame,
    *,
    run_id: str,
    created_at: pd.Timestamp,
    input_price_routes: set[str] | None = None,
) -> pd.DataFrame:
    """Calculate pre-write quality results from actual Stage 8 frames."""
    routes = {str(item).lower() for item in (input_price_routes or set())}
    rows: list[dict[str, object]] = []

    def add(
        name: str,
        passed: bool,
        observed: object,
        expected: object,
        *,
        severity: str = "ERROR",
        numerator: int | None = None,
        denominator: int | None = None,
        message: str = "",
    ) -> None:
        rows.append(_check(
            run_id=run_id, name=name, passed=passed, severity=severity,
            observed=observed, expected=expected, numerator=numerator,
            denominator=denominator, message=message, checked_at=created_at,
        ))

    add(
        "input_price_route_raw",
        routes == {"raw"},
        ",".join(sorted(routes)) or "missing",
        "raw",
        message="actual adjust_type values",
    )
    event_duplicates = int(
        observations.duplicated(["run_id", "symbol", "trade_date"], keep=False).sum()
    )
    add("event_primary_key_unique", event_duplicates == 0, event_duplicates, 0)
    summary_duplicates = int(
        summary.duplicated(
            ["run_id", "symbol", "period_start", "period_end"], keep=False
        ).sum()
    ) if not summary.empty else 0
    add("summary_primary_key_unique", summary_duplicates == 0, summary_duplicates, 0)

    formal = observations.loc[
        observations["event_type"].isin(["limit_up", "limit_down"])
        & observations["evidence_status"].eq("verified")
        & observations["quality_status"].eq("pass")
    ]
    formal_types = (
        formal.groupby(["symbol", "trade_date"])["event_type"].nunique()
        if not formal.empty else pd.Series(dtype="int64")
    )
    conflicts = int(formal_types.gt(1).sum())
    conflicts += int(
        observations["resolution_reason"].eq("mutual_exclusion_conflict").sum()
    )
    add("formal_event_mutual_exclusion", conflicts == 0, conflicts, 0)

    unresolved_mask = (
        observations["event_type"].isin(
            ["unresolved", "candidate", "proxy", "gap_proxy"]
        )
        | observations["evidence_status"].isin(
            ["unresolved", "provisional", "unverified"]
        )
    )
    unresolved_count = int(unresolved_mask.sum())
    add(
        "unresolved_count",
        unresolved_count == 0,
        unresolved_count,
        0,
        numerator=unresolved_count,
        denominator=len(observations),
        message="fail-closed threshold for formal publication",
    )

    valid = observations["is_valid_trade_row"].fillna(False).astype(bool)
    valid_count = int(valid.sum())
    rule_covered = int((valid & observations["rule_version"].notna()).sum())
    status_covered = int(
        (valid & observations["security_status_version"].notna()).sum()
    )
    add(
        "rule_coverage",
        rule_covered == valid_count and valid_count > 0,
        rule_covered / valid_count if valid_count else 0,
        1,
        numerator=rule_covered,
        denominator=valid_count,
    )
    add(
        "security_status_coverage",
        status_covered == valid_count and valid_count > 0,
        status_covered / valid_count if valid_count else 0,
        1,
        numerator=status_covered,
        denominator=valid_count,
    )

    evidence_fields = [
        "previous_close", "matched_limit_price", "tick_size", "rule_version",
        "security_status_version", "detection_method",
    ]
    incomplete = int(formal[evidence_fields].isna().any(axis=1).sum())
    add(
        "official_or_theoretical_evidence_complete",
        incomplete == 0,
        incomplete,
        0,
        numerator=len(formal) - incomplete,
        denominator=len(formal),
    )
    theoretical = formal["detection_method"].eq("theoretical_decimal")
    theoretical_incomplete = int(
        formal.loc[
            theoretical,
            [
                "unrounded_limit_up_price", "unrounded_limit_down_price",
                "theoretical_limit_up_price", "theoretical_limit_down_price",
            ],
        ].isna().any(axis=1).sum()
    )
    add(
        "theoretical_limit_fields_complete",
        theoretical_incomplete == 0,
        theoretical_incomplete,
        0,
    )

    bad_next = int(
        (
            observations["next_trade_date"].notna()
            & (
                pd.to_datetime(observations["next_trade_date"])
                <= pd.to_datetime(observations["trade_date"])
            )
        ).sum()
    )
    add("event_date_order_valid", bad_next == 0, bad_next, 0)

    publication_eligible = observations.loc[
        observations["evidence_status"].eq("verified")
        & observations["quality_status"].eq("pass")
    ]
    forbidden_formal = int(
        publication_eligible["event_type"].isin(
            ["unresolved", "candidate", "proxy", "gap_proxy"]
        ).sum()
    )
    add("forbidden_formal_event_type", forbidden_formal == 0, forbidden_formal, 0)

    complete_forward = int(
        observations["forward_sample_status"].eq("complete").sum()
    )
    add(
        "forward_return_completeness",
        complete_forward == len(observations) and len(observations) > 0,
        complete_forward / len(observations) if len(observations) else 0,
        1,
        severity="WARNING",
        numerator=complete_forward,
        denominator=len(observations),
        message="tail incompleteness is reported, not imputed as zero",
    )

    return_columns = [
        "next_open_return", "next_close_return", "forward_3d_return",
        "forward_5d_return", "forward_10d_return",
    ]
    abnormal = 0
    for column in return_columns:
        values = pd.to_numeric(observations[column], errors="coerce").dropna()
        abnormal += int((~values.map(math.isfinite) | values.abs().gt(10)).sum())
    add("return_range_valid", abnormal == 0, abnormal, 0)

    run_ids = set(observations["run_id"].dropna().astype(str))
    if not summary.empty:
        run_ids.update(summary["run_id"].dropna().astype(str))
    add("run_id_consistent", run_ids == {run_id}, sorted(run_ids), [run_id])
    return pd.DataFrame(rows, columns=QUALITY_COLUMNS)


def run_stage8_post_write_checks(
    database_path: Path,
    *,
    run_id: str,
    expected_event_rows: int,
    expected_summary_rows: int,
    expected_formal_events: int,
    checked_at: pd.Timestamp,
    expected_publication_status: str | None = None,
    expected_report_formal_event_count: int | None = None,
    reports_dir: Path | None = None,
) -> pd.DataFrame:
    """Cross-check DuckDB and all persisted Stage 8 report artifacts."""
    with duckdb.connect(str(database_path), read_only=True) as connection:
        event_rows = connection.execute(
            f"SELECT count(*) FROM analysis.{EVENT_TABLE} WHERE run_id = ?",
            [run_id],
        ).fetchone()[0]
        summary_rows = connection.execute(
            "SELECT count(*) FROM analysis.limit_event_annual_summary "
            "WHERE run_id = ?",
            [run_id],
        ).fetchone()[0]
        formal_rows = connection.execute(
            "SELECT count(*) FROM analysis.v_formal_limit_event WHERE run_id = ?",
            [run_id],
        ).fetchone()[0]
        event_run_ids = {
            row[0] for row in connection.execute(
                f"SELECT DISTINCT run_id FROM analysis.{EVENT_TABLE} "
                "WHERE run_id = ?",
                [run_id],
            ).fetchall()
        }
        summary_run_ids = {
            row[0] for row in connection.execute(
                "SELECT DISTINCT run_id "
                "FROM analysis.limit_event_annual_summary WHERE run_id = ?",
                [run_id],
            ).fetchall()
        }
        quality_run_ids = {
            row[0] for row in connection.execute(
                "SELECT DISTINCT run_id "
                "FROM quality.stage8_quality_result WHERE run_id = ?",
                [run_id],
            ).fetchall()
        }
        audit_rows = connection.execute(
            "SELECT count(*) FROM audit.stage8_run WHERE run_id = ?", [run_id]
        ).fetchone()[0]
        summary_records = connection.execute(
            "SELECT symbol, period_start, period_end, limit_up_count, "
            "limit_down_count, avg_next_open_return_after_limit_up, "
            "avg_next_close_return_after_limit_up, "
            "avg_forward_3d_return_after_limit_up, "
            "avg_forward_5d_return_after_limit_up, "
            "avg_forward_10d_return_after_limit_up, next_day_gap_up_ratio, "
            "continued_limit_ratio, formal_event_count, publication_status, run_id "
            "FROM analysis.limit_event_annual_summary WHERE run_id = ? "
            "ORDER BY symbol, period_start",
            [run_id],
        ).fetchdf().to_dict(orient="records")
        audit_row = connection.execute(
            "SELECT status, publication_status, formal_event_count, unresolved_count, "
            "candidate_count, blockers_json, run_id, window_start, window_end, "
            "quality_passed, quality_failed "
            "FROM audit.stage8_run WHERE run_id = ?",
            [run_id],
        ).fetchone()
        quality_counts = connection.execute(
            "SELECT count_if(status = 'PASS'), count_if(status = 'FAIL') "
            "FROM quality.stage8_quality_result WHERE run_id = ?",
            [run_id],
        ).fetchone()
        candidate_rows = connection.execute(
            f"SELECT count(*) FROM analysis.{EVENT_TABLE} WHERE run_id = ? "
            "AND event_type IN ('candidate', 'proxy', 'gap_proxy')",
            [run_id],
        ).fetchone()[0]
        unresolved_rows = connection.execute(
            f"SELECT count(*) FROM analysis.{EVENT_TABLE} WHERE run_id = ? "
            "AND (event_type = 'unresolved' OR evidence_status = 'unresolved')",
            [run_id],
        ).fetchone()[0]
        event_sample_records = connection.execute(
            f"SELECT symbol, trade_date, event_type, evidence_status, "
            f"quality_status, resolution_reason, detection_method, run_id "
            f"FROM analysis.{EVENT_TABLE} WHERE run_id = ? "
            "ORDER BY symbol, trade_date LIMIT 100",
            [run_id],
        ).fetchdf().to_dict(orient="records")
        quality_records = connection.execute(
            "SELECT run_id, check_name, severity, status, observed_value, "
            "expected_value, numerator, denominator, message "
            "FROM quality.stage8_quality_result WHERE run_id = ? "
            "ORDER BY check_name",
            [run_id],
        ).fetchdf().to_dict(orient="records")
    count_match = (
        event_rows == expected_event_rows
        and summary_rows == expected_summary_rows
        and formal_rows == expected_formal_events
    )
    semantic_match = True
    if expected_publication_status is not None:
        semantic_match = (
            all(
                row["publication_status"] == expected_publication_status
                for row in summary_records
            )
            and audit_row is not None
            and audit_row[1] == expected_publication_status
        )
        if expected_publication_status == "formal":
            persisted_formal_count = sum(
                row["formal_event_count"]
                for row in summary_records
                if row["formal_event_count"] is not None
            )
            semantic_match = semantic_match and (
                audit_row[2] == expected_report_formal_event_count
                and persisted_formal_count == expected_report_formal_event_count
            )
        else:
            semantic_match = semantic_match and (
                expected_report_formal_event_count is None
                and audit_row[2] is None
                and all(
                    all(_normalized(row[field]) is None for field in FORMAL_SUMMARY_FIELDS)
                    for row in summary_records
                )
            )

    artifact_match = True
    artifact_observed = "not_requested"
    if reports_dir is not None:
        try:
            json_path = reports_dir / "stage8_run.json"
            annual_path = reports_dir / "stage8_annual_event_summary.csv"
            quality_path = reports_dir / "stage8_data_quality.csv"
            event_path = reports_dir / "stage8_event_sample.csv"
            markdown_path = reports_dir / "stage8_validation.md"
            manifest = json.loads(json_path.read_text(encoding="utf-8"))
            annual = pd.read_csv(
                annual_path, dtype={"symbol": str, "run_id": str}
            ).to_dict(orient="records")
            quality_report = pd.read_csv(
                quality_path,
                dtype={
                    "run_id": str,
                    "check_name": str,
                    "severity": str,
                    "status": str,
                    "observed_value": str,
                    "expected_value": str,
                    "message": str,
                },
            )
            event_report = pd.read_csv(
                event_path, dtype={"symbol": str, "run_id": str}
            )
            markdown = markdown_path.read_text(encoding="utf-8")
            db_projection = _summary_projection(summary_records)
            json_projection = _summary_projection(manifest.get("annual_summary", []))
            csv_projection = _summary_projection(annual)
            blockers = json.loads(audit_row[5]) if audit_row is not None else None
            expected_formal_label = (
                "not_calculated"
                if manifest.get("formal_event_count") is None
                else str(manifest.get("formal_event_count"))
            )
            event_fields = [
                "symbol", "trade_date", "event_type", "evidence_status",
                "quality_status", "resolution_reason", "detection_method", "run_id",
            ]
            quality_fields = [
                "run_id", "check_name", "severity", "status", "observed_value",
                "expected_value", "numerator", "denominator", "message",
            ]
            event_match = _record_projection(
                event_sample_records, event_fields, ["symbol", "trade_date"]
            ) == _record_projection(
                event_report.to_dict(orient="records"),
                event_fields,
                ["symbol", "trade_date"],
            )
            quality_match = _record_projection(
                quality_records, quality_fields, ["run_id", "check_name"]
            ) == _record_projection(
                quality_report.to_dict(orient="records"),
                quality_fields,
                ["run_id", "check_name"],
            )
            markdown_tokens = [
                f"`{run_id}`",
                f'**{manifest.get("run_status")}**',
                f'`{manifest.get("publication_status")}`',
                str(manifest.get("window_start")),
                str(manifest.get("window_end")),
                expected_formal_label,
                f'- candidate：{manifest.get("candidate_count")}',
                f'- unresolved：{manifest.get("unresolved_count")}',
                *[f"- {item}" for item in manifest.get("blocking_reasons", [])],
            ]
            for row in manifest.get("annual_summary", []):
                for field in FORMAL_SUMMARY_FIELDS:
                    value = row.get(field)
                    rendered = "not_calculated" if value is None else str(value)
                    markdown_tokens.append(
                        f'- {row.get("symbol", "unknown")}.{field}: {rendered}'
                    )
            markdown_match = all(
                token in markdown
                for token in markdown_tokens
            )
            artifact_match = (
                audit_row is not None
                and manifest.get("run_id") == audit_row[6] == run_id
                and manifest.get("run_status") == audit_row[0]
                and manifest.get("publication_status") == audit_row[1]
                and _normalized(manifest.get("formal_event_count"))
                == _normalized(audit_row[2])
                and manifest.get("unresolved_count") == audit_row[3]
                and manifest.get("candidate_count") == audit_row[4]
                and manifest.get("provisional_count") == candidate_rows
                and manifest.get("candidate_count") == candidate_rows
                and manifest.get("unresolved_count") == unresolved_rows
                and manifest.get("blocking_reasons") == blockers
                and str(manifest.get("window_start")) == str(audit_row[7])
                and str(manifest.get("window_end")) == str(audit_row[8])
                and manifest.get("quality_passed") == quality_counts[0]
                and manifest.get("quality_failed") == quality_counts[1]
                and len(quality_report) == sum(quality_counts)
                and int(quality_report["status"].eq("PASS").sum()) == quality_counts[0]
                and int(quality_report["status"].eq("FAIL").sum()) == quality_counts[1]
                and set(quality_report["run_id"].astype(str)) == {run_id}
                and event_match
                and quality_match
                and db_projection == json_projection == csv_projection
                and markdown_match
            )
            artifact_observed = (
                f"json_run={manifest.get('run_id')};summary_rows="
                f"{len(json_projection)}/{len(csv_projection)};quality_rows="
                f"{len(quality_report)};event={event_match};quality={quality_match};"
                f"markdown={markdown_match}"
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            artifact_match = False
            artifact_observed = f"artifact_error:{type(exc).__name__}:{exc}"
    lineage_match = (
        event_run_ids == ({run_id} if expected_event_rows else set())
        and summary_run_ids == ({run_id} if expected_summary_rows else set())
        and quality_run_ids == {run_id}
        and audit_rows == 1
    )
    rows = [
        _check(
            run_id=run_id, name="database_report_consistent",
            passed=count_match and semantic_match and artifact_match,
            severity="ERROR",
            observed=(
                f"counts={event_rows}/{summary_rows}/{formal_rows};"
                f"publication={audit_row};summary={summary_records};"
                f"artifacts={artifact_observed}"
            ),
            expected=(
                f"counts={expected_event_rows}/{expected_summary_rows}/"
                f"{expected_formal_events};publication="
                f"{expected_publication_status};report_formal_count="
                f"{expected_report_formal_event_count}"
            ),
            numerator=int(count_match and semantic_match and artifact_match), denominator=1,
            message=(
                "post-write database counts and publication semantics "
                "vs report frames"
            ),
            checked_at=checked_at,
        ),
        _check(
            run_id=run_id, name="run_id_consistent_post_write",
            passed=lineage_match,
            severity="ERROR",
            observed=(
                f"event={sorted(event_run_ids)},summary={sorted(summary_run_ids)},"
                f"quality={sorted(quality_run_ids)},audit_rows={audit_rows}"
            ),
            expected=f"all populated relations use run_id={run_id},audit_rows=1",
            numerator=int(lineage_match),
            denominator=1,
            message="database event/summary/quality/audit run lineage",
            checked_at=checked_at,
        ),
    ]
    return pd.DataFrame(rows, columns=QUALITY_COLUMNS)
