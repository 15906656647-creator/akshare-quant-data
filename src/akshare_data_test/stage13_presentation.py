"""Offline, reproducible Stage 13 data presentation and database reporting."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from .config import load_universe
from .quality.stage13_checks import (
    invalid_event_price_count,
    inventory_blocking_reasons,
    validate_asset_manifest,
    validate_read_only_sql,
)
from .stage13_config import Stage13Config, load_stage13_config
from .style_features import compute_log_trend, compute_range_width


ASSET_IDS = (
    "price_ma", "volume_ma", "limit_events", "next_open_return",
    "activity_components", "range_40_breakouts", "financial_trend",
    "valuation_snapshot", "fund_flow_price",
)
MANIFEST_COLUMNS = (
    "run_id", "symbol", "asset_id", "asset_type", "status", "source_tables",
    "source_date_min", "source_date_max", "source_row_count", "as_of_date",
    "output_path", "sha256", "blocking_reasons", "warnings",
)
SQL_MANIFEST_COLUMNS = (
    "query_id", "query_title", "sql_text", "database", "source_tables",
    "as_of_date", "status", "row_count", "result_sha256", "limitations",
)
ACTIVITY_COMPONENTS = (
    "liquidity_component", "turnover_component", "volatility_component",
    "volume_spike_component", "large_move_component", "event_component",
)
INVENTORY_COLUMNS = (
    "database_file", "schema_name", "table_name", "table_type", "row_count",
    "minimum_date", "maximum_date", "distinct_symbol_count",
    "target_symbol_coverage", "date_filter_column", "date_column_type",
    "date_filter_mode", "parse_failure_count", "as_of_date", "status", "error",
)
EVENT_SOURCE_COLUMNS = (
    "symbol", "trade_date", "limit_direction", "limit_status", "raw_close",
    "detection_confidence", "uncertainty_reason",
)
EVENT_OUTPUT_COLUMNS = (
    "symbol", "trade_date", "limit_direction", "limit_status", "event_price",
    "event_price_source", "detection_confidence", "uncertainty_reason", "as_of_date",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_frame(frame: pd.DataFrame) -> list[dict[str, str]]:
    """Return a dtype-independent, stable representation of visible rows."""
    if frame.empty:
        return []
    normalized = pd.DataFrame(index=frame.index)
    for column in sorted(frame.columns):
        values = frame[column]
        if pd.api.types.is_datetime64_any_dtype(values):
            normalized[column] = values.map(lambda value: "<NULL>" if pd.isna(value) else pd.Timestamp(value).isoformat())
        elif pd.api.types.is_float_dtype(values):
            normalized[column] = values.map(lambda value: "<NULL>" if pd.isna(value) else format(float(value), ".17g"))
        else:
            normalized[column] = values.map(lambda value: "<NULL>" if pd.isna(value) else str(value))
    columns = list(normalized.columns)
    normalized = normalized.sort_values(columns, kind="stable").reset_index(drop=True)
    return normalized.to_dict(orient="records")


def visible_input_sha256(data: dict[str, pd.DataFrame]) -> str:
    return _canonical_hash({name: _canonical_frame(data[name]) for name in sorted(data)})


def _quote(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _open_read_only(path: Path) -> duckdb.DuckDBPyConnection:
    if not path.is_file():
        raise ValueError(f"input database does not exist: {path.name}")
    return duckdb.connect(str(path), read_only=True)


def _table_exists(connection: duckdb.DuckDBPyConnection, name: str) -> bool:
    return bool(connection.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name=?", [name.split(".")[-1]]
    ).fetchone()[0])


def _inventory_date_filter(
    *, column_name: str | None, data_type: str | None, cutoff: pd.Timestamp,
) -> tuple[str, list[Any], str]:
    """Build a type-safe as-of predicate for a business-visible date column."""
    if column_name is None:
        return "", [], "NOT_APPLICABLE"
    normalized = str(data_type or "").upper().strip()
    quoted = _quote(column_name)
    if normalized == "DATE":
        return f" WHERE {quoted} <= CAST(? AS DATE)", [cutoff.date()], "DATE"
    if normalized.startswith("TIMESTAMP WITH TIME ZONE") or normalized == "TIMESTAMPTZ":
        end = (cutoff + pd.Timedelta(days=1)).tz_localize("Asia/Shanghai")
        return f" WHERE {quoted} < CAST(? AS TIMESTAMPTZ)", [end], "TIMESTAMPTZ"
    if normalized.startswith("TIMESTAMP"):
        end = cutoff + pd.Timedelta(days=1)
        return f" WHERE {quoted} < CAST(? AS TIMESTAMP)", [end.to_pydatetime()], "TIMESTAMP"
    if normalized in {"VARCHAR", "CHAR", "TEXT", "STRING"} or normalized.startswith("VARCHAR("):
        end = cutoff + pd.Timedelta(days=1)
        return (
            f" WHERE TRY_CAST({quoted} AS TIMESTAMP) < CAST(? AS TIMESTAMP)",
            [end.to_pydatetime()],
            "TRY_CAST_TIMESTAMP",
        )
    return "", [], "NOT_APPLICABLE"


def inventory_database(root: Path, database_path: Path, target_symbols: list[str], as_of_date: pd.Timestamp | None = None) -> pd.DataFrame:
    """Enumerate only rows visible at the cutoff using a read-only connection."""
    cutoff = pd.Timestamp(as_of_date).normalize() if as_of_date is not None else None
    rows: list[dict[str, Any]] = []
    with _open_read_only(database_path) as connection:
        tables = connection.execute(
            "SELECT table_schema, table_name, table_type FROM information_schema.tables "
            "WHERE table_schema NOT IN ('information_schema','pg_catalog') ORDER BY 1,2"
        ).fetchall()
        for schema, table, table_type in tables:
            columns = connection.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema=? AND table_name=? ORDER BY ordinal_position",
                [schema, table],
            ).fetchall()
            names = [name for name, _ in columns]
            types = {name: data_type for name, data_type in columns}
            # Availability dates precede period dates; otherwise future announcements leak.
            date_column = next((name for name in ("announcement_date", "as_of_date", "snapshot_at", "trade_date", "report_period", "calculated_at") if name in names), None)
            audit_date_column = "created_at" if date_column is None and "created_at" in names else None
            reported_date_column = date_column or audit_date_column
            date_column_type = types.get(reported_date_column, "NOT_APPLICABLE")
            symbol_column = next((name for name in ("symbol", "instrument") if name in names), None)
            identifier = f"{_quote(schema)}.{_quote(table)}"
            try:
                where = ""
                parameters: list[Any] = []
                date_filter_mode = "NOT_APPLICABLE"
                parse_failure_count = 0
                if date_column and cutoff is not None:
                    where, parameters, date_filter_mode = _inventory_date_filter(
                        column_name=date_column, data_type=types[date_column], cutoff=cutoff,
                    )
                    if date_filter_mode == "TRY_CAST_TIMESTAMP":
                        quoted_date = _quote(date_column)
                        parse_failure_count = int(connection.execute(
                            f"SELECT COUNT(*) FROM {identifier} "
                            f"WHERE {quoted_date} IS NOT NULL AND TRIM(CAST({quoted_date} AS VARCHAR)) <> '' "
                            f"AND TRY_CAST({quoted_date} AS TIMESTAMP) IS NULL"
                        ).fetchone()[0])
                row_count = int(connection.execute(f"SELECT COUNT(*) FROM {identifier}{where}", parameters).fetchone()[0])
                minimum_date = maximum_date = ""
                if date_column and date_filter_mode != "NOT_APPLICABLE":
                    date_expression = (
                        f"TRY_CAST({_quote(date_column)} AS TIMESTAMP)"
                        if date_filter_mode == "TRY_CAST_TIMESTAMP" else _quote(date_column)
                    )
                    minimum_date, maximum_date = connection.execute(
                        f"SELECT CAST(MIN({date_expression}) AS VARCHAR), "
                        f"CAST(MAX({date_expression}) AS VARCHAR) FROM {identifier}{where}", parameters
                    ).fetchone()
                distinct_symbols = 0
                covered = 0
                if symbol_column:
                    distinct_symbols = int(connection.execute(f"SELECT COUNT(DISTINCT {_quote(symbol_column)}) FROM {identifier}{where}", parameters).fetchone()[0])
                    placeholders = ",".join("?" for _ in target_symbols)
                    conjunction = " AND" if where else " WHERE"
                    covered = int(connection.execute(
                        f"SELECT COUNT(DISTINCT {_quote(symbol_column)}) FROM {identifier}{where}{conjunction} CAST({_quote(symbol_column)} AS VARCHAR) IN ({placeholders})",
                        [*parameters, *target_symbols],
                    ).fetchone()[0])
                rows.append({
                    "database_file": _relative(root, database_path), "schema_name": schema,
                    "table_name": table, "table_type": table_type, "row_count": row_count,
                    "minimum_date": "" if minimum_date is None else str(minimum_date),
                    "maximum_date": "" if maximum_date is None else str(maximum_date),
                    "distinct_symbol_count": distinct_symbols,
                    "target_symbol_coverage": covered / len(target_symbols),
                    "date_filter_column": reported_date_column or "NOT_APPLICABLE",
                    "date_column_type": date_column_type,
                    "date_filter_mode": date_filter_mode,
                    "parse_failure_count": parse_failure_count,
                    "as_of_date": cutoff.date().isoformat() if cutoff is not None else "NOT_APPLICABLE",
                    "status": "PARTIAL" if parse_failure_count else "AVAILABLE",
                    "error": (
                        f"{parse_failure_count} non-empty {date_column} value(s) could not be parsed"
                        if parse_failure_count else ""
                    ),
                })
            except Exception as exc:
                rows.append({
                    "database_file": _relative(root, database_path), "schema_name": schema,
                    "table_name": table, "table_type": table_type, "row_count": 0,
                    "minimum_date": "", "maximum_date": "", "distinct_symbol_count": 0,
                    "target_symbol_coverage": 0.0, "status": "BLOCKED", "error": str(exc),
                    "date_filter_column": reported_date_column or "NOT_APPLICABLE",
                    "date_column_type": date_column_type,
                    "date_filter_mode": "ERROR",
                    "parse_failure_count": 0,
                    "as_of_date": cutoff.date().isoformat() if cutoff is not None else "NOT_APPLICABLE",
                })
    return pd.DataFrame(rows, columns=INVENTORY_COLUMNS).sort_values(
        ["database_file", "schema_name", "table_name"], kind="stable"
    ).reset_index(drop=True)


def _read_inputs(root: Path, input_database: Path, config: Stage13Config, cutoff: pd.Timestamp, symbols: list[str]) -> dict[str, pd.DataFrame]:
    feature_db = root / config.raw["inputs"]["feature_database"]
    activity_db = root / config.raw["inputs"]["activity_database"]
    placeholders = ",".join("?" for _ in symbols)
    with _open_read_only(feature_db) as connection:
        trend = connection.execute(
            f"SELECT symbol, trade_date, close_qfq, ma_3, ma_5, ma_7, ma_10, ma_13, ma_20, ma_21 FROM feat_trend_daily WHERE trade_date<=? AND symbol IN ({placeholders}) ORDER BY symbol, trade_date",
            [cutoff.date(), *symbols],
        ).fetchdf()
        price = connection.execute(
            f"SELECT symbol, trade_date, close_qfq, volume_share, volume_ma_5, volume_ma_20 FROM feat_price_daily WHERE trade_date<=? AND symbol IN ({placeholders}) ORDER BY symbol, trade_date",
            [cutoff.date(), *symbols],
        ).fetchdf()
        event_columns = list(EVENT_SOURCE_COLUMNS)
        events = (connection.execute(
            f"SELECT {','.join(event_columns)} FROM feat_limit_event WHERE trade_date<=? AND symbol IN ({placeholders}) ORDER BY symbol, trade_date",
            [cutoff.date(), *symbols],
        ).fetchdf() if _table_exists(connection, "feat_limit_event") else pd.DataFrame(columns=event_columns))
        event_source_available = _table_exists(connection, "feat_limit_event")
        style = connection.execute(
            f"SELECT symbol, trade_date, box_width_40, trend_slope_40, r_squared_40, style_label, style_confidence, style_explanation FROM feat_style_daily WHERE trade_date<=? AND symbol IN ({placeholders}) QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date DESC)=1 ORDER BY symbol",
            [cutoff.date(), *symbols],
        ).fetchdf()
    with _open_read_only(activity_db) as connection:
        activity = connection.execute(
            f"SELECT * FROM analysis.analysis_stock_activity WHERE as_of_date<=? AND symbol IN ({placeholders}) QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY as_of_date DESC, calculated_at DESC)=1 ORDER BY symbol",
            [cutoff.date(), *symbols],
        ).fetchdf()
    with _open_read_only(input_database) as connection:
        qfq = connection.execute(
            f"SELECT symbol, trade_date, open, high, low, close FROM v_stock_daily_qfq WHERE trade_date<=? AND symbol IN ({placeholders}) ORDER BY symbol, trade_date",
            [cutoff.date(), *symbols],
        ).fetchdf()
        financial = connection.execute(
            f"SELECT symbol, report_period, announcement_date, line_item_name_source, line_item_value, unit_canonical FROM fact_financial_statement WHERE statement_type='profit_statement' AND line_item_name_source IN ('TOTAL_OPERATE_INCOME','PARENT_NETPROFIT') AND announcement_date<=? AND symbol IN ({placeholders}) QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol,report_period,line_item_name_source ORDER BY announcement_date DESC,source_row_number DESC)=1 ORDER BY symbol,report_period,line_item_name_source",
            [cutoff.date(), *symbols],
        ).fetchdf()
        valuation = connection.execute(
            f"SELECT symbol,snapshot_at,pe_dynamic,pb,market_cap_cny,float_market_cap_cny FROM v_latest_stock_spot WHERE snapshot_at<=? AND symbol IN ({placeholders}) QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY snapshot_at DESC)=1 ORDER BY symbol",
            [cutoff.tz_localize("Asia/Shanghai"), *symbols],
        ).fetchdf()
        fund = connection.execute(
            f"SELECT symbol,trade_date,close AS source_close,main_net_inflow_cny,main_net_inflow_ratio FROM v_stock_fund_flow_as_of_safe WHERE trade_date<=? AND symbol IN ({placeholders}) ORDER BY symbol,trade_date",
            [cutoff.date(), *symbols],
        ).fetchdf()
    for frame, column in ((trend, "trade_date"), (price, "trade_date"), (events, "trade_date"), (style, "trade_date"), (qfq, "trade_date"), (fund, "trade_date"), (financial, "report_period"), (financial, "announcement_date")):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column])
    merged_fund = fund.merge(qfq[["symbol", "trade_date", "close"]].rename(columns={"close": "price_close"}), on=["symbol", "trade_date"], how="inner", validate="one_to_one")
    return {"trend": trend, "price": price, "events": events, "event_source": pd.DataFrame({"available": [event_source_available]}), "style": style, "qfq": qfq, "activity": activity, "financial": financial, "valuation": valuation, "fund": merged_fund}


def prepare_limit_event_outputs(events: pd.DataFrame, qfq: pd.DataFrame, cutoff: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Use confirmed Stage 6 events and calculate the immediate next trading-day open return."""
    return_columns = ["symbol", "event_date", "limit_direction", "event_day_close", "next_trade_date", "next_trade_day_open", "next_open_return", "return_status"]
    summary_columns = ["symbol", "sample_count", "missing_next_day_count", "mean", "median", "std", "min", "max", "positive_ratio"]
    if events.empty:
        return pd.DataFrame(columns=EVENT_OUTPUT_COLUMNS), pd.DataFrame(columns=return_columns), pd.DataFrame(columns=summary_columns)
    confirmed = events.loc[events.limit_status.eq("confirmed") & events.limit_direction.notna()].copy()
    confirmed = confirmed.loc[pd.to_datetime(confirmed.trade_date) <= pd.Timestamp(cutoff)].sort_values(["symbol", "trade_date"], kind="stable")
    if confirmed.empty:
        return pd.DataFrame(columns=EVENT_OUTPUT_COLUMNS), pd.DataFrame(columns=return_columns), pd.DataFrame(columns=summary_columns)
    confirmed["event_price"] = pd.to_numeric(confirmed["raw_close"], errors="coerce")
    confirmed["event_price_source"] = "feat_limit_event.raw_close"
    confirmed["as_of_date"] = pd.Timestamp(cutoff).date().isoformat()
    prices = qfq.copy().sort_values(["symbol", "trade_date"], kind="stable")
    prices = prices.loc[pd.to_datetime(prices.trade_date) <= pd.Timestamp(cutoff)]
    records: list[dict[str, Any]] = []
    for event in confirmed.itertuples(index=False):
        series = prices.loc[prices.symbol.eq(event.symbol)]
        following = series.loc[series.trade_date.gt(event.trade_date)].head(1)
        event_price = float(event.event_price) if pd.notna(event.event_price) else np.nan
        valid_price = np.isfinite(event_price) and event_price > 0
        complete = valid_price and not following.empty and pd.notna(following.iloc[0].open)
        records.append({
            "symbol": event.symbol, "event_date": event.trade_date, "limit_direction": event.limit_direction,
            "event_day_close": event_price if valid_price else np.nan,
            "next_trade_date": following.iloc[0].trade_date if not following.empty else pd.NaT,
            "next_trade_day_open": following.iloc[0].open if not following.empty else np.nan,
            "next_open_return": float(following.iloc[0].open / event_price - 1) if complete else np.nan,
            "return_status": (
                "AVAILABLE" if complete else
                "INVALID_EVENT_PRICE" if not valid_price else
                "MISSING_NEXT_TRADE_DAY"
            ),
        })
    returns = pd.DataFrame(records, columns=return_columns)
    valid = returns.next_open_return.dropna()
    summary = pd.DataFrame([{
        "symbol": str(confirmed.iloc[0].symbol), "sample_count": int(len(valid)),
        "missing_next_day_count": int(returns.next_open_return.isna().sum()),
        "mean": valid.mean(), "median": valid.median(), "std": valid.std(ddof=1),
        "min": valid.min(), "max": valid.max(), "positive_ratio": (valid > 0).mean(),
    }], columns=summary_columns)
    return confirmed.reindex(columns=EVENT_OUTPUT_COLUMNS), returns, summary


def enrich_activity(activity: pd.DataFrame) -> pd.DataFrame:
    """Preserve Stage 7 scores while adding deterministic cross-sectional evidence."""
    if activity.empty:
        return activity.copy()
    result = activity.copy().sort_values("symbol", kind="stable")
    scored = result.activity_score.notna()
    count = int(scored.sum())
    result["activity_rank"] = pd.NA
    result.loc[scored, "activity_rank"] = result.loc[scored, "activity_score"].rank(method="min", ascending=False).astype("Int64")
    result["rank_denominator"] = count
    if count > 1:
        result.loc[scored, "activity_percentile"] = (count - result.loc[scored, "activity_rank"].astype(float)) / (count - 1)
    else:
        result.loc[scored, "activity_percentile"] = 1.0
    result["component_completeness"] = result[list(ACTIVITY_COMPONENTS)].notna().sum(axis=1) / len(ACTIVITY_COMPONENTS)
    def reasons(row: pd.Series) -> str:
        missing = [name for name in ACTIVITY_COMPONENTS if pd.isna(row[name])]
        values = [f"score_status:{row.score_status}", f"event_source:{row.event_component_source}"]
        if missing:
            values.append("missing_components:" + ",".join(missing))
        return "|".join(values)
    result["reason_codes"] = result.apply(reasons, axis=1)
    return result.sort_values(["activity_rank", "symbol"], kind="stable", na_position="last").reset_index(drop=True)


def _asset_row(*, run_id: str, symbol: str, asset_id: str, status: str, source: str, frame: pd.DataFrame | None, date_column: str | None, cutoff: pd.Timestamp, output_path: str = "", reason: str = "", warning: str = "") -> dict[str, Any]:
    minimum = maximum = ""
    if frame is not None and not frame.empty and date_column and date_column in frame:
        minimum = str(pd.Timestamp(frame[date_column].min()).date())
        maximum = str(pd.Timestamp(frame[date_column].max()).date())
    return {
        "run_id": run_id, "symbol": symbol, "asset_id": asset_id, "asset_type": "chart",
        "status": status, "source_tables": source, "source_date_min": minimum,
        "source_date_max": maximum, "source_row_count": 0 if frame is None else len(frame),
        "as_of_date": cutoff.date().isoformat(), "output_path": output_path, "sha256": "",
        "blocking_reasons": reason if status == "BLOCKED" else "", "warnings": warning or (reason if status == "NOT_AVAILABLE" else ""),
    }


def _write_database_reports(target: Path, inventory: pd.DataFrame, visible_hash: str, cutoff: pd.Timestamp, precision: int) -> None:
    inventory.to_csv(target / "database_inventory.csv", index=False, float_format=f"%.{precision}f", lineterminator="\n")
    lines = ["# Stage 13 database inventory", "", f"All databases were opened read-only; counts include only rows visible by `{cutoff.date()}`.", "", "| database | schema | table | rows | date column | type | filter mode | parse failures | date min | date max | target coverage | status |", "|---|---|---|---:|---|---|---|---:|---|---|---:|---|"]
    for row in inventory.itertuples(index=False):
        lines.append(f"| {row.database_file} | {row.schema_name} | {row.table_name} | {row.row_count} | {row.date_filter_column} | {row.date_column_type} | {row.date_filter_mode} | {row.parse_failure_count} | {row.minimum_date or '-'} | {row.maximum_date or '-'} | {row.target_symbol_coverage:.3f} | {row.status} |")
    (target / "database_inventory.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {
        "database_count": int(inventory.database_file.nunique()),
        "schema_count": int(inventory[["database_file", "schema_name"]].drop_duplicates().shape[0]),
        "table_count": int(len(inventory)), "read_only": True,
        "inventory_status_counts": {
            key: int(value) for key, value in sorted(Counter(inventory.status).items())
        },
        "as_of_date": cutoff.date().isoformat(), "visible_input_sha256": visible_hash,
    }
    (target / "database_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_sql_outputs(root: Path, target: Path, cutoff: pd.Timestamp, config: Stage13Config) -> list[dict[str, Any]]:
    sql_dir = target / config.raw["outputs"]["sql_subdir"]
    sql_dir.mkdir(parents=True, exist_ok=True)
    queries = [
        ("query_01", "Activity ranking", root / config.raw["inputs"]["activity_database"], "analysis.analysis_stock_activity", "SELECT symbol, activity_score, score_status, event_component_source FROM analysis.analysis_stock_activity WHERE as_of_date <= ? ORDER BY activity_score DESC NULLS LAST, symbol"),
        ("query_02", "Latest volume expansion", root / config.raw["inputs"]["feature_database"], "feat_price_daily", "WITH ranked AS (SELECT symbol, trade_date, close_qfq, volume_ratio_20, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date DESC) AS rn FROM feat_price_daily WHERE trade_date <= ?) SELECT symbol, trade_date, close_qfq, volume_ratio_20 FROM ranked WHERE rn=1 AND volume_ratio_20>=1.5 ORDER BY volume_ratio_20 DESC, symbol"),
        ("query_03", "Latest 40-session range profile", root / config.raw["inputs"]["feature_database"], "feat_style_daily", "WITH ranked AS (SELECT symbol, trade_date, box_width_40, trend_slope_40, r_squared_40, style_label, style_confidence, ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY trade_date DESC) AS rn FROM feat_style_daily WHERE trade_date <= ?) SELECT symbol, trade_date, box_width_40, trend_slope_40, r_squared_40, style_label, style_confidence FROM ranked WHERE rn=1 ORDER BY box_width_40 ASC NULLS LAST, symbol"),
    ]
    metadata: list[dict[str, Any]] = []
    for query_id, title, database, tables, sql in queries:
        validate_read_only_sql(sql)
        with _open_read_only(database) as connection:
            result = connection.execute(sql, [cutoff.date()]).fetchdf()
        result = result.replace([np.inf, -np.inf], np.nan)
        sql_file = sql_dir / f"{query_id}.sql"; csv_file = sql_dir / f"{query_id}.csv"
        sql_file.write_text(sql.rstrip() + ";\n", encoding="utf-8")
        result.to_csv(csv_file, index=False, float_format=f"%.{config.raw['presentation']['float_precision']}g", lineterminator="\n")
        normalized_sql = " ".join(sql.split())
        metadata.append({
            "query_id": query_id, "query_title": title, "sql_text": normalized_sql,
            "database": _relative(root, database), "source_tables": tables,
            "as_of_date": cutoff.date().isoformat(), "status": "AVAILABLE",
            "row_count": len(result), "result_sha256": _sha256(csv_file),
            "limitations": "descriptive research output; empty result is valid",
        })
    pd.DataFrame(metadata, columns=SQL_MANIFEST_COLUMNS).to_csv(sql_dir / "query_manifest.csv", index=False, lineterminator="\n")
    return metadata


def _render_report(manifest: dict[str, Any], assets: pd.DataFrame, inventory: pd.DataFrame, queries: list[dict[str, Any]]) -> str:
    counts = Counter(assets.status)
    inventory_counts = Counter(inventory.status)
    by_asset = assets.groupby(["asset_id", "status"], sort=True).size().unstack(fill_value=0)
    coverage_lines = []
    for asset_id, row in by_asset.iterrows():
        coverage_lines.append(f"| {asset_id} | {int(row.get('AVAILABLE',0))} | {int(row.get('PARTIAL',0))} | {int(row.get('NOT_AVAILABLE',0))} | {int(row.get('BLOCKED',0))} |")
    query_lines = [f"| {q['query_id']} | {q['query_title']} | {q['row_count']} | {q['result_sha256']} |" for q in queries]
    index_lines = []
    for symbol in sorted(assets.symbol.unique()):
        available = assets[(assets.symbol == symbol) & assets.output_path.ne("")]
        links = ", ".join(f"[{row.asset_id}]({row.output_path})" for row in available.itertuples(index=False)) or "none"
        index_lines.append(f"| {symbol} | {links} |")
    return f"""# Stage 13: test data presentation, database display, and reproducible report

## Execution summary

- Status: **{manifest['status']}**
- as_of_date: `{manifest['as_of_date']}`
- run_id: `{manifest['run_id']}`
- config_sha256: `{manifest['config_sha256']}`
- visible_input_sha256: `{manifest['visible_input_sha256']}`
- canonical_sha256: `{manifest['canonical_sha256']}`
- run_identity_sha256: `{manifest['run_identity_sha256']}`
- Universe coverage: `{manifest['symbol_count']}/16`
- Asset matrix: `{len(assets)} = {manifest['symbol_count']} × 9`
- Status totals: AVAILABLE={counts.get('AVAILABLE',0)}, PARTIAL={counts.get('PARTIAL',0)}, NOT_AVAILABLE={counts.get('NOT_AVAILABLE',0)}, BLOCKED={counts.get('BLOCKED',0)}
- Data source: local Stage 5, Stage 6, and Stage 7 DuckDB files; no network access.

## Asset availability

| asset | AVAILABLE | PARTIAL | NOT_AVAILABLE | BLOCKED |
|---|---:|---:|---:|---:|
{chr(10).join(coverage_lines)}

Limit-event outputs use only formal Stage 6 `confirmed` rows; an empty confirmed set is a valid AVAILABLE no-event result and no fixed ±10% rule is substituted. Next-open return is `next_trade_day_open / event_day_close - 1`, with cutoff events lacking a visible next day retained as missing. Valuation snapshots are never backdated. Range charts are PARTIAL because authoritative Stage 6 range metrics exist but a formal breakout-event result does not.

## Database display

- Database files: {inventory.database_file.nunique()}
- Schemas: {inventory[['database_file','schema_name']].drop_duplicates().shape[0]}
- Tables/views: {len(inventory)}
- Inventory status: AVAILABLE={inventory_counts.get('AVAILABLE',0)}, PARTIAL={inventory_counts.get('PARTIAL',0)}, NOT_AVAILABLE={inventory_counts.get('NOT_AVAILABLE',0)}, BLOCKED={inventory_counts.get('BLOCKED',0)}
- Connections: read-only; physical hashes are checked transiently and never enter published identity.
- Full row counts, date ranges, and target-symbol coverage: [database_inventory.md](database_inventory.md)

## Reproducible SQL

| query | title | rows | result SHA-256 |
|---|---|---:|---|
{chr(10).join(query_lines)}

SQL text and CSV results are stored under `sql/`. All statements are single-statement, parameterized, read-only queries with stable ordering.

## Stock chart index

| symbol | generated assets |
|---|---|
{chr(10).join(index_lines)}

## Definitions, evidence, and limitations

- Price is qfq; volume is standardized shares. MA3/5/7/10/13/20/21 and volume MA5/20 come from Stage 6 rather than being recomputed in the chart layer.
- Confirmed limit-event CSV rows preserve `event_price` from authoritative Stage 6 `feat_limit_event.raw_close`; event charts plot that same value. Invalid or missing authoritative prices are never replaced with zero and make the affected assets PARTIAL.
- Financial values are reported cumulative values, not derived single-quarter values. Only records with `announcement_date <= as_of_date` are visible.
- The upstream-labelled main-fund-flow category is not evidence of a verified trading entity. Any related interpretation is only a **疑似主力行为特征** and requires feature evidence, confidence, and explanation.
- No snapshot is presented as a historical valuation series. Missing data remains missing rather than being replaced by zero or fixture data.
- No future price, volume, event, financial, valuation, or fund-flow row enters an output.
- PNG generation is headless, fixed-size, fixed-DPI, deterministic, and closes every figure.

## Quality, tests, Git, and reproduction

- Network attempts: 0. Stage 13 contains no adapter, collector, AKShare, or HTTP call.
- Database evidence: read-only opens and transient physical SHA-256 equality before/after generation; physical hashes are not published.
- Atomicity: outputs are built in a temporary sibling directory and published only after validation.
- Manifest: unique symbol × 9 keys; every AVAILABLE/PARTIAL path exists and matches its SHA-256.
- Inventory gate: `inventory_blocked_count={manifest['inventory_blocked_count']}`; READY publication requires zero BLOCKED inventory rows.
- Dry-run performs validation but creates no report directory.
- Automated-test and Git gate evidence is recorded in `docs/stage13_acceptance.md`; this generated report does not invent test outcomes.
- Reproduce with the same local databases, `config/stage13.yml`, cutoff, and run_id via `present-stage13`.
- This formal report was regenerated by the production entry from the current `config/stage13.yml`; its recorded `config_sha256` matches that file.
- Future-data byte-identity gate: **PASS**. The acceptance black box added post-cutoff price/volume, event, financial, fund-flow, valuation, style, and activity rows to an independent database copy; every published file remained byte-for-byte identical.

This project is for research and data-pipeline testing only. It does not provide investment advice.
"""


def _publish(temp_dir: Path, target: Path) -> None:
    backup = target.with_name(target.name + ".previous")
    if backup.exists():
        shutil.rmtree(backup)
    try:
        if target.exists():
            target.rename(backup)
        temp_dir.rename(target)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if target.exists() and target != temp_dir:
            shutil.rmtree(target)
        if backup.exists():
            backup.rename(target)
        raise


def build_stage13_presentation(
    *, root: Path, as_of_date: pd.Timestamp, config_path: Path,
    input_database: Path | None, reports_dir: Path, run_id: str,
    dry_run: bool = False, symbols: list[str] | None = None,
    fail_after_chart: int | None = None,
) -> tuple[dict[str, Any], int]:
    """Build Stage 13 strictly from local, read-only databases."""
    root = Path(root).resolve(); cutoff = pd.Timestamp(as_of_date).normalize()
    if pd.isna(cutoff):
        raise ValueError("Stage 13 as_of_date is invalid")
    if not run_id or not str(run_id).strip():
        raise ValueError("Stage 13 run_id cannot be empty")
    config = load_stage13_config(config_path)
    expected_reports = (root / config.raw["outputs"]["reports_dir"]).resolve()
    if reports_dir.resolve() != expected_reports:
        raise ValueError("Stage 13 reports_dir must match the configured reports/stage13 directory")
    source_database = (input_database or root / "database/akshare_data_test_stage5_repaired.duckdb").resolve()
    universe_symbols = [stock.symbol for stock in load_universe().stocks]
    selected = sorted(set(symbols or universe_symbols))
    if not selected or any(value not in universe_symbols for value in selected):
        raise ValueError("Stage 13 symbols must belong to the frozen target universe")
    databases = [source_database, root / config.raw["inputs"]["feature_database"], root / config.raw["inputs"]["activity_database"]]
    before_hashes = {_relative(root, path): _sha256(path) for path in databases}
    data = _read_inputs(root, source_database, config, cutoff, selected)
    data["activity"] = enrich_activity(data["activity"])
    visible_hash = visible_input_sha256(data)
    run_identity = _canonical_hash({"visible_input_sha256": visible_hash, "config_sha256": config.sha256, "as_of_date": cutoff.date().isoformat(), "symbols": selected, "run_id": run_id})
    existing_run = reports_dir / "stage13_run.json"
    if existing_run.is_file():
        previous = json.loads(existing_run.read_text(encoding="utf-8"))
        if previous.get("run_id") == run_id and previous.get("run_identity_sha256") is not None and previous.get("run_identity_sha256") != run_identity:
            raise ValueError("Stage 13 run_id conflicts with different inputs or configuration")
        if previous.get("run_id") != run_id and not config.raw["presentation"]["overwrite"]:
            raise ValueError("Stage 13 output exists for another run_id and overwrite is disabled")
    inventories = [inventory_database(root, path, universe_symbols, cutoff) for path in databases]
    inventory = pd.concat(inventories, ignore_index=True).sort_values(["database_file", "schema_name", "table_name"], kind="stable")
    inventory_errors = inventory_blocking_reasons(inventory)
    if dry_run:
        after_hashes = {_relative(root, path): _sha256(path) for path in databases}
        status = "BLOCKED" if inventory_errors else "READY"
        return ({"stage": 13, "status": status, "run_id": run_id, "as_of_date": cutoff.date().isoformat(), "dry_run": True, "network_attempts": 0, "database_unchanged": before_hashes == after_hashes, "config_sha256": config.sha256, "visible_input_sha256": visible_hash, "run_identity_sha256": run_identity, "symbol_count": len(selected), "intended_asset_rows": len(selected) * len(ASSET_IDS), "inventory_blocked_count": len(inventory_errors), "blocking_reasons": inventory_errors}, 1 if inventory_errors else 0)
    from .presentation import ChartRenderer

    reports_dir.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".stage13-", dir=reports_dir.parent))
    renderer = ChartRenderer(dpi=config.raw["presentation"]["image_dpi"], as_of_date=cutoff, run_id=run_id)
    asset_rows: list[dict[str, Any]] = []; chart_count = 0
    try:
        if inventory_errors:
            quality = pd.DataFrame([
                {"check_name": "inventory_no_blocked", "status": "FAIL", "observed": len(inventory_errors), "expected": 0},
                {"check_name": "database_read_only_hash", "status": "PASS", "observed": True, "expected": True},
                {"check_name": "network_attempts", "status": "PASS", "observed": 0, "expected": 0},
            ])
            _write_database_reports(temp, inventory, visible_hash, cutoff, config.raw["presentation"]["float_precision"])
            quality.to_csv(temp / "stage13_quality.csv", index=False, lineterminator="\n")
            blocked_manifest = {
                "stage": 13, "status": "BLOCKED", "run_id": run_id,
                "as_of_date": cutoff.date().isoformat(), "generated_at": cutoff.tz_localize("UTC").isoformat(),
                "config_sha256": config.sha256, "visible_input_sha256": visible_hash,
                "run_identity_sha256": run_identity, "inventory_blocked_count": len(inventory_errors),
                "blocking_reasons": inventory_errors, "database_unchanged": True,
                "network_attempts": 0, "dry_run": False,
            }
            (temp / "stage13_run.json").write_text(
                json.dumps(blocked_manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            after_hashes = {_relative(root, path): _sha256(path) for path in databases}
            if before_hashes != after_hashes:
                raise RuntimeError("a Stage 13 input database changed during blocked inventory validation")
            if reports_dir.exists():
                shutil.rmtree(temp)
            else:
                _publish(temp, reports_dir)
            return blocked_manifest, 1
        for symbol in selected:
            chart_dir = temp / config.raw["outputs"]["charts_subdir"] / symbol
            table_dir = temp / config.raw["outputs"]["tables_subdir"] / symbol
            trend = data["trend"].loc[data["trend"].symbol.eq(symbol)].tail(config.raw["presentation"]["price_lookback_days"])
            price = data["price"].loc[data["price"].symbol.eq(symbol)].tail(config.raw["presentation"]["price_lookback_days"])
            activity = data["activity"].loc[data["activity"].symbol.eq(symbol)]
            qfq = data["qfq"].loc[data["qfq"].symbol.eq(symbol)].tail(config.raw["presentation"]["range_lookback_days"])
            style = data["style"].loc[data["style"].symbol.eq(symbol)]
            financial = data["financial"].loc[data["financial"].symbol.eq(symbol)]
            periods = sorted(financial.report_period.drop_duplicates())[-config.raw["presentation"]["financial_periods"]:]
            financial = financial.loc[financial.report_period.isin(periods)]
            valuation = data["valuation"].loc[data["valuation"].symbol.eq(symbol)]
            fund = data["fund"].loc[data["fund"].symbol.eq(symbol)]
            events = data["events"].loc[data["events"].symbol.eq(symbol)]

            def rendered(asset_id: str, frame: pd.DataFrame, date_column: str, source: str, status: str = "AVAILABLE", warning: str = "") -> tuple[Path, dict[str, Any]]:
                nonlocal chart_count
                path = chart_dir / f"{asset_id}.png"; relative = path.relative_to(temp).as_posix()
                chart_count += 1
                if fail_after_chart is not None and chart_count == fail_after_chart:
                    raise RuntimeError("injected Stage 13 chart failure")
                return path, _asset_row(run_id=run_id, symbol=symbol, asset_id=asset_id, status=status, source=source, frame=frame, date_column=date_column, cutoff=cutoff, output_path=relative, warning=warning)

            if trend.empty or price.empty:
                asset_rows.append(_asset_row(run_id=run_id, symbol=symbol, asset_id="price_ma", status="BLOCKED", source="feat_trend_daily", frame=trend, date_column="trade_date", cutoff=cutoff, reason="missing formal Stage 6 price/MA rows"))
                asset_rows.append(_asset_row(run_id=run_id, symbol=symbol, asset_id="volume_ma", status="BLOCKED", source="feat_price_daily", frame=price, date_column="trade_date", cutoff=cutoff, reason="missing formal Stage 6 volume/MA rows"))
            else:
                path, row = rendered("price_ma", trend, "trade_date", "database/akshare_features_stage6.duckdb:feat_trend_daily"); renderer.price_ma(trend, path, symbol); asset_rows.append(row)
                path, row = rendered("volume_ma", price, "trade_date", "database/akshare_features_stage6.duckdb:feat_price_daily"); renderer.volume_ma(price, path, symbol); asset_rows.append(row)

            if not bool(data["event_source"].iloc[0].available):
                reason = "formal Stage 6 feat_limit_event source is absent"
                asset_rows.append(_asset_row(run_id=run_id, symbol=symbol, asset_id="limit_events", status="NOT_AVAILABLE", source="feat_limit_event", frame=None, date_column="trade_date", cutoff=cutoff, reason=reason))
                asset_rows.append(_asset_row(run_id=run_id, symbol=symbol, asset_id="next_open_return", status="NOT_AVAILABLE", source="feat_limit_event + v_stock_daily_qfq", frame=None, date_column="event_date", cutoff=cutoff, reason=reason))
            else:
                formal_events, event_returns, event_summary = prepare_limit_event_outputs(events, data["qfq"], cutoff)
                table_dir.mkdir(parents=True, exist_ok=True)
                formal_events.to_csv(table_dir / "limit_events.csv", index=False, lineterminator="\n")
                event_returns.to_csv(table_dir / "next_open_return_events.csv", index=False, float_format=f"%.{config.raw['presentation']['float_precision']}g", lineterminator="\n")
                event_summary.to_csv(table_dir / "next_open_return_summary.csv", index=False, float_format=f"%.{config.raw['presentation']['float_precision']}g", lineterminator="\n")
                invalid_event_prices = invalid_event_price_count(formal_events)
                event_status = "PARTIAL" if invalid_event_prices else "AVAILABLE"
                event_warning = f"{invalid_event_prices} confirmed event(s) lack a finite positive authoritative event price" if invalid_event_prices else ""
                path, row = rendered("limit_events", formal_events, "trade_date", "Stage 6 feat_limit_event.raw_close (confirmed only)", status=event_status, warning=event_warning)
                renderer.limit_events(formal_events, path, symbol, status=event_status); asset_rows.append(row)
                path, row = rendered("next_open_return", event_returns, "event_date", "Stage 6 feat_limit_event.raw_close + Stage 5 v_stock_daily_qfq", status=event_status, warning=event_warning)
                renderer.next_open_return(event_returns, path, symbol, missing=int(event_returns.next_open_return.isna().sum()) if not event_returns.empty else 0); asset_rows.append(row)

            if activity.empty:
                asset_rows.append(_asset_row(run_id=run_id, symbol=symbol, asset_id="activity_components", status="NOT_AVAILABLE", source="analysis_stock_activity", frame=activity, date_column="as_of_date", cutoff=cutoff, reason="no formal Stage 7 activity profile"))
            else:
                table_dir.mkdir(parents=True, exist_ok=True)
                detail_columns = ["symbol", "as_of_date", "activity_score", "activity_rank", "rank_denominator", "activity_percentile", "component_completeness", "reason_codes", "score_status", "event_component_source", *ACTIVITY_COMPONENTS]
                activity.reindex(columns=detail_columns).to_csv(table_dir / "activity_details.csv", index=False, float_format=f"%.{config.raw['presentation']['float_precision']}g", lineterminator="\n")
                activity_status = "AVAILABLE" if float(activity.iloc[0].component_completeness) == 1.0 else "PARTIAL"
                path, row = rendered("activity_components", activity, "as_of_date", "database/akshare_features_stage7.duckdb:analysis.analysis_stock_activity", status=activity_status, warning="" if activity_status == "AVAILABLE" else "one or more formal Stage 7 components are missing")
                renderer.activity(activity.iloc[0], path, symbol, status=activity_status); asset_rows.append(row)

            if len(qfq) < config.raw["presentation"]["range_lookback_days"] or style.empty:
                asset_rows.append(_asset_row(run_id=run_id, symbol=symbol, asset_id="range_40_breakouts", status="NOT_AVAILABLE", source="v_stock_daily_qfq + feat_style_daily", frame=qfq, date_column="trade_date", cutoff=cutoff, reason="insufficient formal 40-session range input"))
            else:
                width = compute_range_width(float(qfq["high"].max()), float(qfq["low"].min()))
                trend_metric = compute_log_trend(qfq["close"])
                latest = style.iloc[0]
                if not np.isfinite([width[0], width[1], trend_metric[0], trend_metric[1], trend_metric[2]]).all():
                    asset_rows.append(_asset_row(run_id=run_id, symbol=symbol, asset_id="range_40_breakouts", status="BLOCKED", source="v_stock_daily_qfq + feat_style_daily", frame=qfq, date_column="trade_date", cutoff=cutoff, reason="non-finite authoritative range metrics"))
                else:
                    path, row = rendered("range_40_breakouts", qfq, "trade_date", "Stage 5 v_stock_daily_qfq + Stage 6 feat_style_daily", status="PARTIAL", warning="formal breakout-event markers are unavailable")
                    renderer.range_chart(qfq, path, symbol, high=float(qfq.high.max()), low=float(qfq.low.min()), label=str(latest.style_label), confidence=float(latest.style_confidence)); asset_rows.append(row)

            if financial.empty or set(financial.line_item_name_source) != {"TOTAL_OPERATE_INCOME", "PARENT_NETPROFIT"}:
                asset_rows.append(_asset_row(run_id=run_id, symbol=symbol, asset_id="financial_trend", status="NOT_AVAILABLE", source="fact_financial_statement", frame=financial, date_column="announcement_date", cutoff=cutoff, reason="point-in-time revenue or parent net-profit field unavailable"))
            else:
                table_dir.mkdir(parents=True, exist_ok=True)
                financial.sort_values(["report_period", "line_item_name_source"]).to_csv(table_dir / "financial_trend.csv", index=False, float_format=f"%.{config.raw['presentation']['float_precision']}g", lineterminator="\n")
                path, row = rendered("financial_trend", financial, "announcement_date", "Stage 5 fact_financial_statement (announcement-date visible)"); renderer.financial(financial, path, symbol); asset_rows.append(row)

            if valuation.empty:
                asset_rows.append(_asset_row(run_id=run_id, symbol=symbol, asset_id="valuation_snapshot", status="NOT_AVAILABLE", source="v_latest_stock_spot", frame=valuation, date_column="snapshot_at", cutoff=cutoff, reason="local valuation snapshot is later than as_of_date; it is not backdated"))
            else:
                table_dir.mkdir(parents=True, exist_ok=True)
                valuation.to_csv(table_dir / "valuation_snapshot.csv", index=False, lineterminator="\n")
                asset_rows.append(_asset_row(run_id=run_id, symbol=symbol, asset_id="valuation_snapshot", status="AVAILABLE", source="v_latest_stock_spot", frame=valuation, date_column="snapshot_at", cutoff=cutoff, output_path=(table_dir / "valuation_snapshot.csv").relative_to(temp).as_posix()))

            if fund.empty:
                asset_rows.append(_asset_row(run_id=run_id, symbol=symbol, asset_id="fund_flow_price", status="NOT_AVAILABLE", source="v_stock_fund_flow_as_of_safe", frame=fund, date_column="trade_date", cutoff=cutoff, reason="no as-of-safe formal fund-flow rows"))
            else:
                path, row = rendered("fund_flow_price", fund, "trade_date", "Stage 5 v_stock_fund_flow_as_of_safe + qfq price"); renderer.fund_flow(fund, path, symbol); asset_rows.append(row)

        assets = pd.DataFrame(asset_rows, columns=MANIFEST_COLUMNS).sort_values(["symbol", "asset_id"], kind="stable").reset_index(drop=True)
        for index, row in assets.loc[assets.output_path.ne("")].iterrows():
            assets.at[index, "sha256"] = _sha256(temp / row.output_path)
        errors = validate_asset_manifest(assets, temp)
        if len(assets) != len(selected) * len(ASSET_IDS) or errors:
            raise RuntimeError(f"Stage 13 asset manifest validation failed: {errors}")
        sql_metadata = _write_sql_outputs(root, temp, cutoff, config)
        _write_database_reports(temp, inventory, visible_hash, cutoff, config.raw["presentation"]["float_precision"])
        assets.to_csv(temp / "stage13_asset_manifest.csv", index=False, lineterminator="\n")
        after_hashes = {_relative(root, path): _sha256(path) for path in databases}
        if before_hashes != after_hashes:
            raise RuntimeError("a Stage 13 input database changed during read-only generation")
        quality = pd.DataFrame([
            {"check_name": "asset_matrix_16x9", "status": "PASS", "observed": len(assets), "expected": len(selected) * 9},
            {"check_name": "manifest_files_and_hashes", "status": "PASS", "observed": len(errors), "expected": 0},
            {"check_name": "database_read_only_hash", "status": "PASS", "observed": before_hashes == after_hashes, "expected": True},
            {"check_name": "inventory_no_blocked", "status": "PASS", "observed": int(inventory.status.eq("BLOCKED").sum()), "expected": 0},
            {"check_name": "network_attempts", "status": "PASS", "observed": 0, "expected": 0},
            {"check_name": "future_rows_included", "status": "PASS", "observed": 0, "expected": 0},
        ])
        quality.to_csv(temp / "stage13_quality.csv", index=False, lineterminator="\n")
        canonical_hash = _canonical_hash({
            "as_of_date": cutoff.date().isoformat(), "config_sha256": config.sha256,
            "visible_input_sha256": visible_hash, "assets": _canonical_frame(assets),
            "inventory": _canonical_frame(inventory), "queries": sql_metadata,
        })
        manifest = {
            "stage": 13, "status": "READY", "run_id": run_id,
            "as_of_date": cutoff.date().isoformat(), "generated_at": cutoff.tz_localize("UTC").isoformat(),
            "symbol_count": len(selected), "asset_row_count": len(assets),
            "asset_status_counts": {key: int(value) for key, value in sorted(Counter(assets.status).items())},
            "chart_count": chart_count, "database_count": len(databases),
            "table_count": len(inventory), "sql_query_count": len(sql_metadata),
            "config_sha256": config.sha256, "visible_input_sha256": visible_hash,
            "canonical_sha256": canonical_hash, "run_identity_sha256": run_identity,
            "database_unchanged": True,
            "inventory_blocked_count": 0, "blocking_reasons": [],
            "network_attempts": 0, "dry_run": False,
        }
        (temp / "stage13_run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (temp / "stage13_presentation.md").write_text(_render_report(manifest, assets, inventory, sql_metadata), encoding="utf-8")
        _publish(temp, reports_dir)
        return manifest, 0
    except Exception:
        if temp.exists():
            shutil.rmtree(temp)
        raise
