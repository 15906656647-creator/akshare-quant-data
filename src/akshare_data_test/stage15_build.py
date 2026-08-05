"""Stage 15 quality-control and risk-validation orchestration."""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .config import load_universe
from .fundamental_analysis import load_stage10_config
from .paths import project_root
from .quality.stage15_checks import (
    CHECK_COLUMNS,
    CROSS_VALIDATION_COLUMNS,
    RISK_LOG_COLUMNS,
    build_cross_validation,
    build_risk_log,
    run_daily_quality_checks,
)
from .stage15_config import load_stage15_config


TABLE_DAILY = "fact_" + "stock_" + "daily"
TABLE_SPOT = "fact_" + "stock_" + "spot"
INPUT_TABLES = (
    TABLE_DAILY,
    TABLE_SPOT,
    "fact_" + "financial_" + "abstract",
    "fact_" + "financial_" + "indicator",
    "fact_" + "financial_" + "statement",
    "fact_" + "stock_" + "fund_" + "flow",
)
PROTECTED_OUTPUT_NAMES = {
    "akshare_data_test_stage5_repaired.duckdb",
    "akshare_features_stage7.duckdb",
    "akshare_limit_events_stage8.duckdb",
    "akshare_style_stage9.duckdb",
}


def _git_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            check=False,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else "unavailable"
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return "unavailable"


def _table_columns(connection: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='main' AND table_name=?",
            [table],
        ).fetchall()
    }


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def _load_baseline(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"baseline must be a JSON object: {path}")
    return payload


def _load_elapsed_records(root: Path, config: dict[str, Any]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for key in ("interface_smoke_csv", "stage4_financial_coverage"):
        path = root / config["inputs"][key]
        if not path.is_file():
            continue
        frame = pd.read_csv(path, encoding="utf-8-sig")
        if {"interface_name", "elapsed_seconds"}.issubset(frame.columns):
            frames.append(frame[["interface_name", "elapsed_seconds"]].copy())
    if not frames:
        return pd.DataFrame(columns=["interface_name", "elapsed_seconds"])
    return pd.concat(frames, ignore_index=True)


def _cross_validation_markdown(
    cross: pd.DataFrame, as_of_date: date, run_id: str
) -> str:
    lines = [
        "# Stage 15 Cross-Validation Checklist",
        "",
        f"- Run ID: `{run_id}`",
        f"- Business date: {as_of_date.isoformat()}",
        "- Verification status: `REVIEW` means evidence is generated for manual",
        "  cross-check against an external source; `UNAVAILABLE` means the item",
        "  cannot be verified because its upstream input is not available.",
        "",
        "| symbol | check_item | observed_value | source | status | note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in cross.itertuples(index=False):
        observed = str(row.observed_value).replace("|", "\\|")
        note = str(row.note).replace("|", "\\|")
        lines.append(
            f"| {row.symbol} | {row.check_item} | {observed} | "
            f"{row.source_table} | {row.verification_status} | {note} |"
        )
    lines.extend(
        [
            "",
            "Manual reviewers should confirm the order of magnitude and field",
            "interpretation of the `REVIEW` rows against a public quote page. No",
            "investment advice is produced by this checklist.",
        ]
    )
    return "\n".join(lines) + "\n"


def validate_stage15_inputs(
    *,
    root: Path,
    config_path: Path,
    input_database: Path,
    output_database: Path,
    as_of_date: date,
    stage8_database: Path | None = None,
    baseline: Path | None = None,
    cross_validation_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Read-only preflight; never creates output paths or report files."""
    errors: list[str] = []
    blockers: list[str] = []
    config: dict[str, Any] | None = None
    config_hash = ""
    try:
        config, config_hash = load_stage15_config(config_path)
    except (OSError, ValueError) as exc:
        errors.append(f"stage15_config_invalid:{exc}")
    universe = load_universe()
    expected_symbols = [item.symbol for item in universe.stocks]
    if cross_validation_symbols is not None:
        unknown = sorted(
            set(cross_validation_symbols).difference(expected_symbols)
        )
        if unknown:
            blockers.append(
                f"cross-validation symbols outside universe: {unknown}"
            )
    if not input_database.is_file():
        blockers.append(f"input database does not exist: {input_database}")
    if output_database.resolve() == input_database.resolve():
        blockers.append("input and output databases must be different")
    if output_database.name.lower() in PROTECTED_OUTPUT_NAMES:
        blockers.append(f"output database is protected: {output_database.name}")
    if Path(output_database).stem.lower() == "quality":
        blockers.append(
            "output database stem must not equal the DuckDB schema name 'quality'"
        )
    if baseline is not None and not baseline.is_file():
        blockers.append(f"baseline file does not exist: {baseline}")
    elif baseline is not None:
        try:
            payload = json.loads(baseline.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("baseline root must be an object")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            blockers.append(f"baseline read failed: {exc}")
    if stage8_database is not None and not stage8_database.is_file():
        blockers.append(f"stage8 database does not exist: {stage8_database}")
    counts: dict[str, int] = {}
    available_symbols: list[str] = []
    if config is not None and input_database.is_file():
        try:
            with duckdb.connect(str(input_database), read_only=True) as connection:
                for table in INPUT_TABLES:
                    actual = _table_columns(connection, table)
                    expected = set(config["daily_checks"]["expected_columns"][table])
                    missing = sorted(expected.difference(actual))
                    if missing:
                        blockers.append(f"{table} missing columns: {missing}")
                    else:
                        counts[table] = int(
                            connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                        )
                if not blockers:
                    etl_columns = _table_columns(connection, "etl_run")
                    required_etl = {"transform_run_id", "status", "as_of_date"}
                    missing_etl = sorted(required_etl.difference(etl_columns))
                    if missing_etl:
                        blockers.append(f"etl_run missing columns: {missing_etl}")
                    else:
                        passed = connection.execute(
                            "SELECT count(*) FROM etl_run WHERE status='PASS'"
                        ).fetchone()[0]
                        if passed <= 0:
                            blockers.append("no PASS etl_run record in input database")
                    dim_columns = _table_columns(connection, "dim_security")
                    if "symbol" not in dim_columns:
                        blockers.append("dim_security missing symbol column")
                    else:
                        dim_count = int(
                            connection.execute("SELECT count(*) FROM dim_security").fetchone()[0]
                        )
                        if dim_count != len(expected_symbols):
                            blockers.append(
                                f"dim_security count {dim_count} != {len(expected_symbols)}"
                            )
                if not blockers:
                    available_symbols = [
                        str(row[0]).zfill(6)
                        for row in connection.execute(
                            "SELECT DISTINCT symbol FROM fact_financial_statement "
                            "WHERE potential_lookahead=FALSE AND announcement_date IS NOT NULL "
                            "AND announcement_date <= ? ORDER BY symbol",
                            [as_of_date],
                        ).fetchall()
                    ]
        except duckdb.Error as exc:
            blockers.append(f"input database read failed: {exc}")
    missing_symbols = sorted(
        set(expected_symbols).difference(available_symbols)
    )
    if available_symbols and missing_symbols:
        blockers.append(
            f"point-in-time financial data missing symbols: {missing_symbols}"
        )
    stage8_notes: list[str] = []
    if stage8_database is not None and stage8_database.is_file():
        try:
            with duckdb.connect(str(stage8_database), read_only=True) as connection:
                names = {
                    f"{str(row[0])}.{str(row[1])}"
                    for row in connection.execute(
                        "SELECT table_schema, table_name FROM information_schema.tables"
                    ).fetchall()
                }
                if "analysis.v_latest_formal_limit_event" in names:
                    stage8_notes.append("formal limit-event view available")
                else:
                    blockers.append(
                        "stage8 database is missing analysis.v_latest_formal_limit_event"
                    )
        except duckdb.Error as exc:
            blockers.append(f"stage8 database read failed: {exc}")
    elif stage8_database is None:
        stage8_notes.append(
            "stage8 database not provided; limit-up cross-validation stays UNAVAILABLE"
        )
    status = "FAILED" if errors else ("BLOCKED" if blockers else "READY")
    return {
        "status": status,
        "blocking_reasons": sorted(set(blockers)),
        "errors": sorted(set(errors)),
        "stage8_notes": stage8_notes,
        "config_hash": config_hash,
        "config_version": config.get("schema_version") if config else None,
        "as_of_date": as_of_date.isoformat(),
        "input_database": str(input_database),
        "output_database": str(output_database),
        "stage8_database": str(stage8_database) if stage8_database else None,
        "table_counts": counts,
        "available_symbols": available_symbols,
    }


def _read_inputs(connection: duckdb.DuckDBPyConnection) -> dict[str, pd.DataFrame]:
    return {
        table: connection.execute(f"SELECT * FROM {table}").fetchdf()
        for table in INPUT_TABLES
    }


def _read_limit_events(stage8_database: Path | None) -> pd.DataFrame | None:
    if stage8_database is None or not stage8_database.is_file():
        return None
    with duckdb.connect(str(stage8_database), read_only=True) as connection:
        names = {
            f"{str(row[0])}.{str(row[1])}"
            for row in connection.execute(
                "SELECT table_schema, table_name FROM information_schema.tables"
            ).fetchall()
        }
        if "analysis.v_latest_formal_limit_event" not in names:
            return None
        return connection.execute(
            "SELECT * FROM analysis.v_latest_formal_limit_event"
        ).fetchdf()


def _stage8_blocker_codes(
    config: dict[str, Any], limit_events: pd.DataFrame | None
) -> list[str]:
    if limit_events is not None and not limit_events.empty:
        return []
    return list(config["stage8"]["blocker_codes"])


def decide_stage15_status(
    *, checks: pd.DataFrame, cross: pd.DataFrame, risks: pd.DataFrame
) -> str:
    """Return the run status without hiding blocked or unavailable items.

    ``PASS_WITH_UNAVAILABLE_ITEMS`` is used whenever Stage 15 output still
    contains unavailable cross-validation items or blocked risk entries, so
    an overall ``PASS`` can never disguise an incomplete cross-validation.
    """
    error_failures = checks.loc[
        checks["severity"].astype(str).eq("error")
        & checks["status"].astype(str).eq("FAIL")
    ]
    warning_failures = checks.loc[
        ~checks["severity"].astype(str).eq("error")
        & checks["status"].astype(str).eq("FAIL")
    ]
    warns = checks.loc[checks["status"].astype(str).eq("WARN")]
    unavailable_count = (
        int(cross["verification_status"].astype(str).eq("UNAVAILABLE").sum())
        if not cross.empty
        else 0
    )
    blocked_count = (
        int(risks["status"].astype(str).eq("blocked").sum())
        if not risks.empty
        else 0
    )
    if not error_failures.empty:
        return "FAIL"
    if unavailable_count > 0 or blocked_count > 0:
        return "PASS_WITH_UNAVAILABLE_ITEMS"
    if not warning_failures.empty or not warns.empty:
        return "WARN"
    return "PASS"


def _write_output_database(
    output_database: Path,
    *,
    run_id: str,
    checks: pd.DataFrame,
    cross: pd.DataFrame,
    risks: pd.DataFrame,
    run_summary: dict[str, Any],
) -> None:
    output_database.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(str(output_database))
    try:
        connection.execute(
            (project_root() / "sql/stage15_schema.sql").read_text(encoding="utf-8")
        )
        connection.register("checks", checks)
        connection.execute(
            "INSERT OR REPLACE INTO quality.check_result "
            f"({', '.join(CHECK_COLUMNS)}) "
            f"SELECT {', '.join(CHECK_COLUMNS)} FROM checks"
        )
        connection.unregister("checks")
        connection.register("cross_rows", cross)
        connection.execute(
            "INSERT OR REPLACE INTO quality.cross_validation "
            f"({', '.join(CROSS_VALIDATION_COLUMNS)}) "
            f"SELECT {', '.join(CROSS_VALIDATION_COLUMNS)} FROM cross_rows"
        )
        connection.unregister("cross_rows")
        connection.register("risks", risks)
        connection.execute(
            "INSERT OR REPLACE INTO quality.risk_log "
            "(risk_id, run_id, detected_at, category, interface_name, symbol, "
            "severity, description, impact, mitigation, status) "
            "SELECT risk_id, ? AS run_id, detected_at, category, interface_name, "
            "symbol, severity, description, impact, mitigation, status FROM risks",
            [run_id],
        )
        connection.unregister("risks")
        connection.execute(
            "INSERT OR REPLACE INTO audit.stage15_run "
            "(run_id, as_of_date, status, config_hash, quality_passed, "
            "quality_failed, quality_warned, risk_row_count, "
            "cross_validation_row_count, stage8_blocker_codes, created_at, "
            "input_database, output_database) "
            "SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?",
            [
                run_summary["run_id"],
                run_summary["as_of_date"],
                run_summary["status"],
                run_summary["config_hash"],
                run_summary["quality_passed"],
                run_summary["quality_failed"],
                run_summary["quality_warned"],
                run_summary["risk_row_count"],
                run_summary["cross_validation_row_count"],
                run_summary["stage8_blocker_codes"],
                run_summary["created_at"],
                run_summary["input_database"],
                run_summary["output_database"],
            ],
        )
    finally:
        connection.close()


def run_stage15_quality_control(
    *,
    root: Path,
    as_of_date: date,
    config_path: Path,
    input_database: Path,
    output_database: Path,
    reports_dir: Path,
    run_id: str | None = None,
    stage8_database: Path | None = None,
    baseline_path: Path | None = None,
    cross_validation_symbols: list[str] | None = None,
    dry_run: bool = False,
    checked_at: pd.Timestamp | None = None,
) -> tuple[dict[str, Any], int]:
    """Run Stage 15 quality control fully offline and publish run-scoped outputs."""
    config, config_hash = load_stage15_config(config_path)
    actual_run_id = run_id or str(uuid.uuid4())
    uuid.UUID(actual_run_id)
    if dry_run:
        print(
            "Stage 15 dry-run: run_id="
            + actual_run_id
            + " as_of_date="
            + as_of_date.isoformat()
        )
        print("  input: " + str(input_database))
        print("  outputs: " + str(output_database))
        print("  reports: " + str(reports_dir / actual_run_id))
        return {
            "stage": 15,
            "status": "DRY_RUN",
            "run_id": actual_run_id,
            "as_of_date": as_of_date.isoformat(),
        }, 0
    universe = load_universe()
    expected_symbols = [item.symbol for item in universe.stocks]
    selected_symbols = cross_validation_symbols or list(
        config["cross_validation"]["symbols"]
    )
    selected_symbols = [str(item).zfill(6) for item in selected_symbols]
    preflight = validate_stage15_inputs(
        root=root,
        config_path=config_path,
        input_database=input_database,
        output_database=output_database,
        as_of_date=as_of_date,
        stage8_database=stage8_database,
        baseline=baseline_path,
        cross_validation_symbols=selected_symbols,
    )
    if preflight["status"] != "READY":
        report = {
            "stage": 15,
            "status": preflight["status"],
            "run_id": actual_run_id,
            "as_of_date": as_of_date.isoformat(),
            "blocking_reasons": preflight["blocking_reasons"],
            "errors": preflight["errors"],
            "outputs_written": False,
        }
        return report, {"FAILED": 1, "BLOCKED": 2}[preflight["status"]]
    timestamp = checked_at or pd.Timestamp(datetime.now(timezone.utc))
    baseline = _load_baseline(baseline_path)
    stage10_config = load_stage10_config(root / "config/stage10.yml")[0]
    with duckdb.connect(str(input_database), read_only=True) as connection:
        tables = _read_inputs(connection)
    elapsed = _load_elapsed_records(root, config)
    checks = run_daily_quality_checks(
        run_id=actual_run_id,
        checked_at=timestamp,
        tables=tables,
        expected_symbols=expected_symbols,
        config=config,
        stage10_config=stage10_config,
        as_of_date=pd.Timestamp(as_of_date).normalize(),
        baseline=baseline,
        elapsed=elapsed,
    )
    limit_events = _read_limit_events(stage8_database)
    blockers = _stage8_blocker_codes(config, limit_events)
    cross = build_cross_validation(
        run_id=actual_run_id,
        as_of_date=pd.Timestamp(as_of_date).normalize(),
        daily=tables[TABLE_DAILY],
        spot=tables[TABLE_SPOT],
        statements=tables["fact_financial_statement"],
        limit_events=limit_events,
        symbols=selected_symbols,
        config=config,
        stage10_config=stage10_config,
    )
    risks = build_risk_log(
        run_id=actual_run_id,
        checked_at=timestamp,
        checks=checks,
        cross_validation=cross,
        stage8_blocker_codes=blockers,
        config=config,
    )
    status = decide_stage15_status(
        checks=checks, cross=cross, risks=risks
    )
    unavailable_count = (
        int(cross["verification_status"].astype(str).eq("UNAVAILABLE").sum())
        if not cross.empty
        else 0
    )
    blocked_count = (
        int(risks["status"].astype(str).eq("blocked").sum())
        if not risks.empty
        else 0
    )
    status_counts = (
        checks["status"].value_counts().to_dict()
        if not checks.empty
        else {}
    )
    report_dir = reports_dir / actual_run_id
    summary_path = report_dir / "quality_summary.json"
    if summary_path.is_file():
        existing = json.loads(summary_path.read_text(encoding="utf-8"))
        if existing.get("run_id") != actual_run_id:
            raise ValueError(
                f"reports directory is owned by another run: {report_dir}"
            )
    run_summary = {
        "run_id": actual_run_id,
        "as_of_date": as_of_date,
        "status": status,
        "config_hash": config_hash,
        "quality_passed": int(status_counts.get("PASS", 0)),
        "quality_failed": int(status_counts.get("FAIL", 0)),
        "quality_warned": int(status_counts.get("WARN", 0)),
        "risk_row_count": int(len(risks)),
        "cross_validation_row_count": int(len(cross)),
        "stage8_blocker_codes": json.dumps(blockers, ensure_ascii=False),
        "created_at": timestamp,
        "input_database": str(input_database),
        "output_database": str(output_database),
    }
    _write_output_database(
        output_database,
        run_id=actual_run_id,
        checks=checks,
        cross=cross,
        risks=risks,
        run_summary=run_summary,
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    checks.to_csv(
        report_dir / "quality_check_results.csv",
        index=False,
        encoding="utf-8-sig",
    )
    cross.to_csv(
        report_dir / "cross_validation.csv",
        index=False,
        encoding="utf-8-sig",
    )
    risks.to_csv(
        report_dir / "risk_log.csv",
        index=False,
        encoding="utf-8-sig",
    )
    _atomic_write_text(
        report_dir / "cross_validation.md",
        _cross_validation_markdown(cross, as_of_date, actual_run_id),
    )
    summary = {
        "stage": 15,
        "run_id": actual_run_id,
        "as_of_date": as_of_date.isoformat(),
        "status": status,
        "exit_code": 1 if status == "FAIL" else 0,
        "quality_status_counts": {
            key: int(status_counts.get(key, 0))
            for key in ("PASS", "WARN", "FAIL", "UNAVAILABLE")
        },
        "quality_checks": checks.to_dict("records"),
        "cross_validation": cross.to_dict("records"),
        "risk_log": risks.to_dict("records"),
        "stage8_blocker_codes": blockers,
        "unavailable_count": unavailable_count,
        "blocked_risk_count": blocked_count,
        "input_database": str(input_database),
        "stage8_database": str(stage8_database) if stage8_database else None,
        "baseline": str(baseline_path) if baseline_path else None,
        "outputs": {
            "database": str(output_database),
            "reports_dir": str(report_dir),
            "quality_check_results": str(report_dir / "quality_check_results.csv"),
            "cross_validation": str(report_dir / "cross_validation.csv"),
            "cross_validation_markdown": str(report_dir / "cross_validation.md"),
            "risk_log": str(report_dir / "risk_log.csv"),
            "risk_log_json": str(report_dir / "risk_log.json"),
        },
        "config_hash": config_hash,
        "config_version": config["schema_version"],
        "python_version": platform.python_version(),
        "git_commit": _git_commit(root),
        "created_at": timestamp.isoformat(),
    }
    _atomic_write_text(
        report_dir / "risk_log.json",
        json.dumps(risks.to_dict("records"), ensure_ascii=False, indent=2, default=str),
    )
    _atomic_write_text(
        summary_path,
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
    )
    return summary, 1 if status == "FAIL" else 0
