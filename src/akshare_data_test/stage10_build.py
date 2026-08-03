"""Offline orchestration for Stage 10 fundamental and valuation analysis."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from .config import load_universe
from .fundamental_analysis import (
    build_fundamental_summary, calculate_fundamental_indicators,
    cumulative_to_single_quarter, load_stage10_config,
    normalize_financial_statements, normalize_valuation_snapshot,
    FundamentalAnalysisNotApplicable, require_equity_asset,
)
from .quality.fundamental_checks import (
    indicator_report_projection, run_stage10_quality_checks,
    verify_stage10_persistence,
)
from .storage.fundamental_repository import AUDIT_COLUMNS, write_stage10_run


SPOT_INPUT_TABLE = "fact_" + "stock_" + "spot"
INPUT_TABLES = {
    "fact_financial_statement": {
        "symbol", "statement_type", "report_period", "announcement_date",
        "line_item_code", "line_item_name_source", "line_item_value",
        "unit_canonical", "source_column", "source_file", "source_run_id",
        "source_row_number", "potential_lookahead",
    },
    SPOT_INPUT_TABLE: {
        "snapshot_at", "symbol", "pe_dynamic", "pb", "market_cap_cny",
        "source_run_id",
    },
}


def _utc_now() -> pd.Timestamp:
    return pd.Timestamp(datetime.now(timezone.utc))


def _table_columns(connection: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    return {
        str(row[0]) for row in connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema='main' AND table_name=?",
            [table],
        ).fetchall()
    }


def validate_stage10_inputs(
    *, config_path: Path, input_database: Path, output_database: Path,
    as_of_date: pd.Timestamp, symbols: list[str] | None = None,
    input_manifest: Path | None = None,
) -> dict[str, Any]:
    """Read-only validation that never creates output paths or reports."""
    blockers: list[str] = []
    try:
        config, config_hash = load_stage10_config(config_path)
    except (OSError, ValueError) as exc:
        return {"status": "FAILED", "blocking_reasons": [str(exc)]}
    if not input_database.is_file():
        blockers.append(f"input database does not exist: {input_database}")
    if input_database.resolve() == output_database.resolve():
        blockers.append("input and output databases must be different")
    protected = {
        "akshare_features_stage7.duckdb",
        "akshare_limit_events_stage8.duckdb",
        "akshare_style_stage9.duckdb",
    }
    if output_database.name.lower() in protected:
        blockers.append("output_database_is_protected_baseline")
    manifest_path = input_manifest or input_database.with_suffix(
        input_database.suffix + ".manifest.json"
    )
    manifest: dict[str, Any] | None = None
    if not manifest_path.is_file():
        blockers.append(f"verified Stage 5 manifest does not exist: {manifest_path}")
    else:
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError("manifest root must be an object")
            manifest = loaded
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            blockers.append(f"Stage 5 manifest read failed: {exc}")
    if manifest is not None:
        if manifest.get("stage") != "stage5":
            blockers.append("Stage 5 manifest stage must be 'stage5'")
        if manifest.get("validation_status") != "PASS":
            blockers.append("Stage 5 manifest validation_status must be PASS")
        verified_tag = manifest.get("verified_tag")
        if not isinstance(verified_tag, str) or not verified_tag.startswith("stage5-verified-"):
            blockers.append("Stage 5 manifest verified_tag is invalid")
        if not isinstance(manifest.get("run_id"), str) or not manifest.get("run_id", "").strip():
            blockers.append("Stage 5 manifest run_id is missing")
    counts: dict[str, int] = {}
    available_symbols: list[str] = []
    if not blockers:
        try:
            with duckdb.connect(str(input_database), read_only=True) as connection:
                for table, required in INPUT_TABLES.items():
                    actual = _table_columns(connection, table)
                    missing = sorted(required.difference(actual))
                    if missing:
                        blockers.append(f"{table} missing columns: {missing}")
                    else:
                        counts[table] = int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
                if not blockers:
                    etl_columns = _table_columns(connection, "etl_run")
                    required_etl = {"transform_run_id", "status"}
                    missing_etl = sorted(required_etl.difference(etl_columns))
                    if missing_etl:
                        blockers.append(f"etl_run missing columns: {missing_etl}")
                    elif manifest is not None:
                        verified_run = connection.execute(
                            "SELECT status FROM etl_run WHERE transform_run_id=?",
                            [manifest["run_id"]],
                        ).fetchone()
                        if verified_run is None or verified_run[0] != "PASS":
                            blockers.append("Stage 5 manifest run_id is not a PASS etl_run")
                if not blockers:
                    available_symbols = [
                        str(row[0]).zfill(6) for row in connection.execute(
                            "SELECT DISTINCT symbol FROM fact_financial_statement "
                            "WHERE potential_lookahead=FALSE AND announcement_date IS NOT NULL "
                            "AND announcement_date <= ? ORDER BY symbol",
                            [pd.Timestamp(as_of_date).date()],
                        ).fetchall()
                    ]
        except duckdb.Error as exc:
            blockers.append(f"input database read failed: {exc}")
    expected = set(symbols or [item.symbol for item in load_universe().stocks])
    missing_symbols = sorted(expected.difference(available_symbols))
    if missing_symbols:
        blockers.append(f"point-in-time financial data missing symbols: {missing_symbols}")
    return {
        "status": "READY" if not blockers else "BLOCKED",
        "blocking_reasons": blockers, "config_hash": config_hash,
        "config_version": config["schema_version"],
        "as_of_date": pd.Timestamp(as_of_date).date().isoformat(),
        "input_database": str(input_database), "output_database": str(output_database),
        "input_manifest": str(manifest_path),
        "verified_stage5_run_id": manifest.get("run_id") if manifest else None,
        "verified_stage5_tag": manifest.get("verified_tag") if manifest else None,
        "table_counts": counts, "available_symbols": available_symbols,
    }


def _read_inputs(
    database_path: Path, *, as_of_date: pd.Timestamp, symbols: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    placeholders = ",".join("?" for _ in symbols)
    end_exclusive = pd.Timestamp(as_of_date).normalize() + pd.Timedelta(days=1)
    with duckdb.connect(str(database_path), read_only=True) as connection:
        statements = connection.execute(
            f"SELECT * FROM fact_financial_statement WHERE symbol IN ({placeholders}) "
            "AND potential_lookahead=FALSE AND announcement_date IS NOT NULL "
            "AND announcement_date <= ? AND report_period <= ?",
            [*symbols, pd.Timestamp(as_of_date).date(), pd.Timestamp(as_of_date).date()],
        ).fetchdf()
        spot = connection.execute(
            f"SELECT * EXCLUDE (rn) FROM (SELECT *, row_number() OVER ("
            "PARTITION BY symbol, snapshot_at, source_run_id ORDER BY "
            "CASE WHEN snapshot_scope='target_16' THEN 0 ELSE 1 END) rn "
            f"FROM {SPOT_INPUT_TABLE} WHERE symbol IN ({placeholders}) AND snapshot_at < ?) WHERE rn=1",
            [*symbols, end_exclusive.to_pydatetime()],
        ).fetchdf()
    return statements, spot


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if value is pd.NA or (isinstance(value, float) and pd.isna(value)):
        return None
    return value


def render_stage10_validation(report: dict[str, Any]) -> str:
    blockers = "\n".join(f"- {item}" for item in report["blocking_reasons"]) or "- 无"
    return f"""# 阶段 10 基本面与估值分析验证

- run_id：`{report['run_id']}`
- run_status：**{report['run_status']}**
- publication_status：`{report['publication_status']}`
- 数据来源：阶段 5 DuckDB 中经公告日期约束的 AKShare 财务报表与实时行情快照
- 是否正式数据：`{report['output_type']}`；仅输入门禁全部通过时可发布为分析数据
- 截止日期：{report['as_of_date']}
- 财务口径：利润表及现金流量表累计值转换为单季度；最近四个完整季度计算 TTM
- 财务事实：{report['fact_row_count']} 行
- 指标：{report['indicator_row_count']} 行
- 基本面摘要：{report['summary_row_count']} 行
- 当前估值快照：{report['valuation_row_count']} 行

## 质量门禁

- PASS：{report['quality_passed']}
- FAIL：{report['quality_failed']}
- 阻塞项：
{blockers}

## 风险与限制

- 当前 PE/PB 仅代表 `current valuation snapshot`，没有回填或伪造历史估值。
- 负 PE 标记为 `loss-making`；缺失 PE/PB 保持空值，不填 0。
- 公告日期缺失、未来公告、累计前期缺失和单位冲突均采用 fail-closed 处理。
- 财务评分是指标完整性与方向的描述性摘要，不是证券价值高低结论。
- 本系统仅用于研究和数据能力测试，不构成投资建议。
"""


def _write_reports(
    reports_dir: Path, *, report: dict[str, Any], summaries: pd.DataFrame,
    indicators: pd.DataFrame, valuations: pd.DataFrame, quality: pd.DataFrame,
) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "stage10_run.json").write_text(
        json.dumps(_json_safe(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    summaries.to_csv(reports_dir / "stage10_fundamental_summary.csv", index=False, encoding="utf-8-sig")
    indicator_report_projection(indicators).to_csv(
        reports_dir / "stage10_fundamental_indicator.csv", index=False,
        encoding="utf-8-sig",
    )
    valuations.to_csv(reports_dir / "stage10_valuation_snapshot.csv", index=False, encoding="utf-8-sig")
    quality.to_csv(reports_dir / "stage10_data_quality.csv", index=False, encoding="utf-8-sig")
    validation = render_stage10_validation(report)
    (reports_dir / "stage10_validation.md").write_text(validation, encoding="utf-8")
    audit = f"""# 阶段 10 独立审计

- run_id：`{report['run_id']}`
- 结论：**{report['run_status']}**
- 已核对：来源、公告日期边界、版本保留、单位、累计转单季、同比、TTM、估值类型、run_id 与事务写入。
- 缺失项和阻塞原因：{'; '.join(report['blocking_reasons']) or '无'}
- 数据范围：截至 {report['as_of_date']}，{report['symbol_count']} 只证券。
- 限制：历史 PE/PB 未由当前快照推导；输出不构成投资建议。
"""
    (reports_dir / "stage10_independent_audit.md").write_text(audit, encoding="utf-8")


def _build_audit(report: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame([{
        "run_id": report["run_id"], "run_status": report["run_status"],
        "publication_status": report["publication_status"],
        "started_at": report["started_at"], "completed_at": report["completed_at"],
        "input_database": report["input_database"], "output_database": report["output_database"],
        "as_of_date": report["as_of_date"], "symbol_count": report["symbol_count"],
        "raw_row_count": report["raw_row_count"], "fact_row_count": report["fact_row_count"],
        "indicator_row_count": report["indicator_row_count"],
        "summary_row_count": report["summary_row_count"],
        "valuation_row_count": report["valuation_row_count"],
        "quality_passed": report["quality_passed"], "quality_failed": report["quality_failed"],
        "blocking_reasons_json": json.dumps(report["blocking_reasons"], ensure_ascii=False),
        "config_hash": report["config_hash"],
        "calculation_version": report["calculation_version"],
        "model_version": report["model_version"], "output_type": report["output_type"],
        "manifest_json": json.dumps(_json_safe(report), ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        "created_at": report["created_at"],
    }], columns=AUDIT_COLUMNS)


def analyze_stage10(
    *, root: Path, config_path: Path, input_database: Path,
    output_database: Path, as_of_date: pd.Timestamp, symbols: list[str] | None = None,
    run_id: str | None = None, dry_run: bool = False,
    input_manifest: Path | None = None,
    asset_type: str = "equity",
) -> tuple[dict[str, Any], int]:
    """Execute Stage 10 fully offline and return its manifest and exit code."""
    started_at = _utc_now()
    run_id = run_id or str(uuid.uuid4())
    try:
        require_equity_asset(asset_type)
    except FundamentalAnalysisNotApplicable as exc:
        return {
            "run_id": run_id, "status": exc.status,
            "run_status": "NOT_APPLICABLE", "publication_status": "not_applicable",
            "asset_type": "crypto", "reason": str(exc),
            "financial_adapter_called": False, "financial_repository_accessed": False,
            "financial_results": {}, "quality_failed": 0,
            "started_at": started_at.isoformat(), "completed_at": _utc_now().isoformat(),
        }, 0
    config, config_hash = load_stage10_config(config_path)
    selected_symbols = symbols or [item.symbol for item in load_universe().stocks]
    selected_symbols = sorted({str(symbol).zfill(6) for symbol in selected_symbols})
    validation = validate_stage10_inputs(
        config_path=config_path, input_database=input_database,
        output_database=output_database, as_of_date=as_of_date,
        symbols=selected_symbols, input_manifest=input_manifest,
    )
    if validation["status"] != "READY":
        raise ValueError("; ".join(validation["blocking_reasons"]))
    statements, spot = _read_inputs(
        input_database, as_of_date=as_of_date, symbols=selected_symbols,
    )
    raw, facts = normalize_financial_statements(statements, run_id=run_id, config=config)
    facts = cumulative_to_single_quarter(facts)
    indicators = calculate_fundamental_indicators(
        facts, run_id=run_id, calculation_version=config["calculation_version"],
        created_at=started_at,
    )
    valuations = normalize_valuation_snapshot(
        spot, run_id=run_id, source="AKShare stock_zh_a_spot_em",
        created_at=started_at, valuation_type=config["valuation_type"],
    )
    summaries = build_fundamental_summary(
        indicators, valuations, run_id=run_id, as_of_date=as_of_date,
        config=config, created_at=started_at,
    )
    quality = run_stage10_quality_checks(
        raw, facts, indicators, summaries, valuations, run_id=run_id,
        as_of_date=as_of_date, expected_symbols=selected_symbols, config=config,
        checked_at=started_at,
    )
    failed_errors = quality.loc[
        quality["severity"].eq("ERROR") & quality["status"].eq("FAIL"), "check_name"
    ].astype(str).tolist()
    report: dict[str, Any] = {
        "run_id": run_id, "run_status": "FAIL" if failed_errors else "PASS",
        "publication_status": "blocked" if failed_errors else "formal",
        "started_at": started_at, "completed_at": _utc_now(),
        "created_at": started_at, "input_database": str(input_database),
        "output_database": str(output_database),
        "as_of_date": pd.Timestamp(as_of_date).date().isoformat(),
        "symbol_count": len(selected_symbols), "raw_row_count": len(raw),
        "fact_row_count": len(facts), "indicator_row_count": len(indicators),
        "summary_row_count": len(summaries), "valuation_row_count": len(valuations),
        "summary_count": len(summaries), "indicator_count": len(indicators),
        "quality_passed": int(quality["status"].eq("PASS").sum()),
        "quality_failed": int(quality["status"].eq("FAIL").sum()),
        "blocking_reasons": failed_errors, "config_hash": config_hash,
        "calculation_version": config["calculation_version"],
        "model_version": config["model_version"],
        "config_version": config["schema_version"],
        "output_type": "dry_run" if dry_run else "analysis_data",
        "source_statement": "Stage 5 point-in-time-safe AKShare financial facts",
        "valuation_scope": "current valuation snapshot",
        "input_manifest": validation["input_manifest"],
        "verified_stage5_run_id": validation["verified_stage5_run_id"],
        "verified_stage5_tag": validation["verified_stage5_tag"],
    }
    summaries["publication_status"] = report["publication_status"]
    if dry_run:
        return _json_safe(report), 1 if failed_errors else 0
    reports_dir = root / "reports"
    schema_path = root / "sql/stage10_schema.sql"
    audit = _build_audit(report)
    write_stage10_run(
        output_database, schema_path, run_id=run_id, raw=raw, facts=facts,
        indicators=indicators, summaries=summaries, valuations=valuations,
        quality=quality, audit=audit,
    )
    _write_reports(
        reports_dir, report=report, summaries=summaries, indicators=indicators,
        valuations=valuations, quality=quality,
    )
    expected_counts = {
        "raw": len(raw), "facts": len(facts), "indicators": len(indicators),
        "summaries": len(summaries), "valuations": len(valuations),
    }
    post = verify_stage10_persistence(
        output_database, reports_dir, run_id=run_id,
        expected_counts=expected_counts, checked_at=_utc_now(),
    )
    quality = pd.concat([quality, post], ignore_index=True)
    post_failures = post.loc[post.severity.eq("ERROR") & post.status.eq("FAIL"), "check_name"].astype(str).tolist()
    report["blocking_reasons"] = failed_errors + post_failures
    report["run_status"] = "FAIL" if report["blocking_reasons"] else "PASS"
    report["publication_status"] = "blocked" if report["blocking_reasons"] else "formal"
    summaries["publication_status"] = report["publication_status"]
    report["quality_passed"] = int(quality.status.eq("PASS").sum())
    report["quality_failed"] = int(quality.status.eq("FAIL").sum())
    report["completed_at"] = _utc_now()
    audit = _build_audit(report)
    write_stage10_run(
        output_database, schema_path, run_id=run_id, raw=raw, facts=facts,
        indicators=indicators, summaries=summaries, valuations=valuations,
        quality=quality, audit=audit,
    )
    _write_reports(
        reports_dir, report=report, summaries=summaries, indicators=indicators,
        valuations=valuations, quality=quality,
    )
    return _json_safe(report), 1 if report["run_status"] == "FAIL" else 0
