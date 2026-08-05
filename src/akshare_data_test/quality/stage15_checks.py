"""Stage 15 daily quality checks, cross-validation snapshot, and risk log."""
from __future__ import annotations

import json
import uuid
from typing import Any

import numpy as np
import pandas as pd


CHECK_COLUMNS = [
    "run_id",
    "check_name",
    "category",
    "severity",
    "status",
    "observed_value",
    "expected_value",
    "interface_name",
    "message",
    "checked_at",
]
CROSS_VALIDATION_COLUMNS = [
    "run_id",
    "symbol",
    "check_item",
    "observed_value",
    "source_table",
    "as_of_date",
    "verification_status",
    "note",
]
RISK_LOG_COLUMNS = [
    "risk_id",
    "detected_at",
    "category",
    "interface_name",
    "symbol",
    "severity",
    "description",
    "impact",
    "mitigation",
    "status",
]

TABLE_DAILY = "fact_" + "stock_" + "daily"
TABLE_SPOT = "fact_" + "stock_" + "spot"
TABLE_LIMIT_EVENT = "fact_" + "limit_" + "event"
TABLE_LIMIT_SOURCE = "analysis." + TABLE_LIMIT_EVENT

_DAILY_KEY = ["symbol", "trade_date", "adjust_type", "source_run_id"]
_SPOT_KEY = ["symbol", "snapshot_at", "snapshot_scope", "source_run_id"]
_ABSTRACT_KEY = ["symbol", "report_period", "metric_code", "source_run_id"]
_INDICATOR_KEY = ["symbol", "report_period", "metric_code", "source_run_id"]
_STATEMENT_KEY = [
    "symbol",
    "statement_type",
    "report_period",
    "line_item_code",
    "source_run_id",
]
_FUND_FLOW_KEY = ["symbol", "trade_date", "source_run_id"]


def _row(
    run_id: str,
    name: str,
    category: str,
    severity: str,
    status: str,
    observed: Any,
    expected: Any,
    checked_at: pd.Timestamp,
    *,
    interface_name: str = "",
    message: str = "",
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "check_name": name,
        "category": category,
        "severity": severity,
        "status": status,
        "observed_value": str(observed),
        "expected_value": str(expected),
        "interface_name": interface_name,
        "message": message,
        "checked_at": checked_at,
    }


def _symbols(frame: pd.DataFrame, *, scope: str | None = None) -> set[str]:
    if scope is None:
        return set(frame["symbol"].astype("string").str.zfill(6))
    return set(
        frame.loc[frame["snapshot_scope"].astype(str).eq(scope), "symbol"]
        .astype("string")
        .str.zfill(6)
    )


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    return pd.to_numeric(frame[column], errors="coerce")


def _table_primary_keys(table: str) -> list[str]:
    mapping = {
        TABLE_DAILY: _DAILY_KEY,
        TABLE_SPOT: _SPOT_KEY,
        "fact_" + "financial_" + "abstract": _ABSTRACT_KEY,
        "fact_" + "financial_" + "indicator": _INDICATOR_KEY,
        "fact_" + "financial_" + "statement": _STATEMENT_KEY,
        "fact_" + "stock_" + "fund_" + "flow": _FUND_FLOW_KEY,
    }
    return mapping[table]


def _coverage_rows(
    run_id: str,
    checked_at: pd.Timestamp,
    expected_symbols: list[str],
    tables: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    expected = set(expected_symbols)
    scopes = {
        f"sample_stocks_present:{TABLE_DAILY}:qfq": (
            TABLE_DAILY,
            _symbols(tables[TABLE_DAILY].loc[
                tables[TABLE_DAILY]["adjust_type"].astype(str).eq("qfq")
            ]),
        ),
        f"sample_stocks_present:{TABLE_DAILY}:raw": (
            TABLE_DAILY,
            _symbols(tables[TABLE_DAILY].loc[
                tables[TABLE_DAILY]["adjust_type"].astype(str).eq("raw")
            ]),
        ),
        f"sample_stocks_present:{TABLE_SPOT}:target_16": (
            TABLE_SPOT,
            _symbols(tables[TABLE_SPOT], scope="target_16"),
        ),
        "sample_stocks_present:fact_" + "financial_" + "abstract": (
            "fact_" + "financial_" + "abstract",
            _symbols(tables["fact_" + "financial_" + "abstract"]),
        ),
        "sample_stocks_present:fact_" + "financial_" + "indicator": (
            "fact_" + "financial_" + "indicator",
            _symbols(tables["fact_" + "financial_" + "indicator"]),
        ),
        "sample_stocks_present:fact_" + "financial_" + "statement": (
            "fact_" + "financial_" + "statement",
            _symbols(tables["fact_" + "financial_" + "statement"]),
        ),
        "sample_stocks_present:fact_" + "stock_" + "fund_" + "flow": (
            "fact_" + "stock_" + "fund_" + "flow",
            _symbols(tables["fact_" + "stock_" + "fund_" + "flow"]),
        ),
    }
    rows: list[dict[str, Any]] = []
    for name, (table, actual) in scopes.items():
        missing = sorted(expected.difference(actual))
        rows.append(
            _row(
                run_id,
                name,
                "data_completeness",
                "error",
                "PASS" if not missing else "FAIL",
                missing,
                sorted(expected),
                checked_at,
                interface_name="",
                message=f"{table} missing configured sample symbols",
            )
        )
    return rows


def _row_count_rows(
    run_id: str,
    checked_at: pd.Timestamp,
    tables: dict[str, pd.DataFrame],
    config: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    minimums = config["daily_checks"]["row_count_expected_minimum"]
    decline_ratio = float(config["daily_checks"]["row_count_decline_ratio"])
    baseline_counts = (baseline or {}).get("table_row_counts", {})
    rows: list[dict[str, Any]] = []
    for table, frame in tables.items():
        observed = len(frame)
        previous = baseline_counts.get(table)
        expected = previous if previous is not None else minimums[table]
        abnormal_decline = (
            previous is not None
            and observed < previous * (1.0 - decline_ratio)
        )
        below_minimum = observed < minimums[table]
        failed = abnormal_decline or below_minimum
        message = "row count abnormal decline vs baseline" if abnormal_decline else (
            "row count below expected minimum" if below_minimum else ""
        )
        rows.append(
            _row(
                run_id,
                f"row_count:{table}",
                "data_completeness",
                "error",
                "FAIL" if failed else "PASS",
                observed,
                expected,
                checked_at,
                message=message,
            )
        )
    return rows


def _latest_trade_date_rows(
    run_id: str,
    checked_at: pd.Timestamp,
    daily: pd.DataFrame,
    as_of_date: pd.Timestamp,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    tolerance = int(config["daily_checks"]["latest_trade_date_tolerance_days"])
    lower = as_of_date.normalize() - pd.Timedelta(days=tolerance)
    rows: list[dict[str, Any]] = []
    for adjust in ("qfq", "raw"):
        subset = daily.loc[daily["adjust_type"].astype(str).eq(adjust)]
        observed = (
            pd.to_datetime(subset["trade_date"], errors="coerce").max()
            if not subset.empty
            else pd.NaT
        )
        passed = (
            pd.notna(observed)
            and observed.normalize() <= as_of_date.normalize()
            and observed.normalize() >= lower
        )
        rows.append(
            _row(
                run_id,
                f"latest_trade_date_updated:{adjust}",
                "data_completeness",
                "error",
                "PASS" if passed else "FAIL",
                observed.date().isoformat() if pd.notna(observed) else "empty",
                f"{lower.date().isoformat()}..{as_of_date.date().isoformat()}",
                checked_at,
                message="latest trade date must fall within the configured tolerance",
            )
        )
    return rows


def _schema_rows(
    run_id: str,
    checked_at: pd.Timestamp,
    tables: dict[str, pd.DataFrame],
    config: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    expected_columns = config["daily_checks"]["expected_columns"]
    baseline_schemas = (baseline or {}).get("table_schemas", {})
    rows: list[dict[str, Any]] = []
    for table, frame in tables.items():
        observed = sorted(str(column) for column in frame.columns)
        expected = sorted(baseline_schemas.get(table, expected_columns[table]))
        rows.append(
            _row(
                run_id,
                f"schema_field_set:{table}",
                "schema_change",
                "error",
                "PASS" if observed == expected else "FAIL",
                observed,
                expected,
                checked_at,
                message="field set must not change without a documented schema migration",
            )
        )
    return rows


def _duplicate_rows(
    run_id: str,
    checked_at: pd.Timestamp,
    tables: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table, frame in tables.items():
        keys = _table_primary_keys(table)
        duplicated = int(frame.duplicated(keys).sum())
        null_keys = int(frame[keys].isna().any(axis=1).sum())
        failed = duplicated > 0 or null_keys > 0
        rows.append(
            _row(
                run_id,
                f"primary_key_duplicates:{table}",
                "logic_error",
                "error",
                "FAIL" if failed else "PASS",
                {"duplicate_rows": duplicated, "null_key_rows": null_keys},
                {"duplicate_rows": 0, "null_key_rows": 0},
                checked_at,
                message="primary key duplicates or null keys are not allowed",
            )
        )
    return rows


def _ohlc_rows(
    run_id: str,
    checked_at: pd.Timestamp,
    daily: pd.DataFrame,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for adjust in ("qfq", "raw"):
        subset = daily.loc[daily["adjust_type"].astype(str).eq(adjust)].copy()
        if subset.empty:
            rows.append(
                _row(
                    run_id,
                    f"ohlc_logic:{adjust}",
                    "logic_error",
                    "error",
                    "FAIL",
                    0,
                    0,
                    checked_at,
                    message="daily rows are empty for this adjust type",
                )
            )
            continue
        for column in ("open", "high", "low", "close"):
            subset[column] = _numeric_series(subset, column)
        invalid = int(
            (
                subset["high"].lt(subset["low"])
                | subset["high"].lt(subset["open"])
                | subset["high"].lt(subset["close"])
                | subset["low"].gt(subset["open"])
                | subset["low"].gt(subset["close"])
            )
            .fillna(False)
            .sum()
        )
        non_positive = int(
            (
                subset[["open", "high", "low", "close"]]
                .le(0)
                .any(axis=1)
            )
            .fillna(False)
            .sum()
        )
        failed = invalid > 0 or non_positive > 0
        rows.append(
            _row(
                run_id,
                f"ohlc_logic:{adjust}",
                "logic_error",
                "error",
                "FAIL" if failed else "PASS",
                {"invalid_relationship_rows": invalid, "non_positive_price_rows": non_positive},
                {"invalid_relationship_rows": 0, "non_positive_price_rows": 0},
                checked_at,
                message="OHLC relationships and positive prices must hold",
            )
        )
    return rows


def _negative_volume_rows(
    run_id: str,
    checked_at: pd.Timestamp,
    tables: dict[str, pd.DataFrame],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for adjust in ("qfq", "raw"):
        subset = tables[TABLE_DAILY].loc[
            tables[TABLE_DAILY]["adjust_type"].astype(str).eq(adjust)
        ]
        volume = _numeric_series(subset, "volume_lot")
        amount = _numeric_series(subset, "amount_cny")
        count = int((volume.lt(0) | amount.lt(0)).fillna(False).sum())
        rows.append(
            _row(
                run_id,
                f"negative_volume_amount:{TABLE_DAILY}:{adjust}",
                "logic_error",
                "error",
                "PASS" if count == 0 else "FAIL",
                count,
                0,
                checked_at,
                message="volume and amount must not be negative",
            )
        )
    spot = tables[TABLE_SPOT].loc[
        tables[TABLE_SPOT]["snapshot_scope"].astype(str).eq("target_16")
    ]
    volume = _numeric_series(spot, "volume_lot")
    amount = _numeric_series(spot, "amount_cny")
    count = int((volume.lt(0) | amount.lt(0)).fillna(False).sum())
    rows.append(
        _row(
            run_id,
            f"negative_volume_amount:{TABLE_SPOT}:target_16",
            "logic_error",
            "error",
            "PASS" if count == 0 else "FAIL",
            count,
            0,
            checked_at,
            message="spot volume and amount must not be negative",
        )
    )
    return rows


def _pe_pb_missing_rows(
    run_id: str,
    checked_at: pd.Timestamp,
    spot: pd.DataFrame,
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    subset = spot.loc[spot["snapshot_scope"].astype(str).eq("target_16")]
    threshold = float(config["daily_checks"]["pe_pb_missing_rate_threshold"])
    rows: list[dict[str, Any]] = []
    for field in ("pe_dynamic", "pb"):
        observed = float(subset[field].isna().mean()) if not subset.empty else 1.0
        rows.append(
            _row(
                run_id,
                f"pe_pb_missing_rate:{field}",
                "valuation_quality",
                "warning",
                "PASS" if observed <= threshold else "FAIL",
                round(observed, 6),
                threshold,
                checked_at,
                message="PE/PB missing rate above configured threshold",
            )
        )
    return rows


def _financial_mapping_lookup(stage10_config: dict[str, Any]) -> dict[tuple[str, str], str]:
    result: dict[tuple[str, str], str] = {}
    for statement_type, mapping in stage10_config["statement_mappings"].items():
        for canonical, specification in mapping.items():
            aliases = (
                specification.get("priority")
                if isinstance(specification, dict)
                else specification
            )
            for alias in aliases:
                key = (str(statement_type), str(alias))
                if key in result:
                    raise ValueError(f"Duplicate financial source alias: {key}")
                result[key] = str(canonical)
    return result


def _financial_coverage(
    statements: pd.DataFrame,
    stage10_config: dict[str, Any],
    expected_symbols: list[str],
) -> dict[str, list[str]]:
    lookup = _financial_mapping_lookup(stage10_config)
    required = stage10_config["required_items"]
    safe = statements.loc[
        statements["announcement_date"].notna()
        & statements["potential_lookahead"].astype("boolean").fillna(False).eq(False)
        & pd.to_numeric(statements["line_item_value"], errors="coerce").notna()
    ].copy()
    safe["_canonical"] = [
        lookup.get((str(kind), str(column)))
        for kind, column in zip(safe["statement_type"], safe["source_column"])
    ]
    safe = safe.loc[safe["_canonical"].notna()]
    covered: dict[str, set[str]] = {item: set() for item in required}
    for canonical, group in safe.groupby("_canonical", dropna=False):
        if canonical in covered:
            covered[canonical].update(
                group["symbol"].astype("string").str.zfill(6)
            )
    expected = set(expected_symbols)
    return {
        item: sorted(expected.difference(covered[item]))
        for item in required
    }


def _financial_key_field_rows(
    run_id: str,
    checked_at: pd.Timestamp,
    statements: pd.DataFrame,
    stage10_config: dict[str, Any],
    expected_symbols: list[str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    coverage = _financial_coverage(statements, stage10_config, expected_symbols)
    threshold = float(config["daily_checks"]["financial_key_fields_coverage_threshold"])
    rows: list[dict[str, Any]] = []
    total_slots = len(expected_symbols) * len(stage10_config["required_items"])
    covered_slots = total_slots - sum(len(missing) for missing in coverage.values())
    observed_rate = covered_slots / total_slots if total_slots else 1.0
    rows.append(
        _row(
            run_id,
            "financial_key_fields_coverage",
            "financial_quality",
            "error",
            "PASS" if observed_rate >= threshold else "FAIL",
            round(observed_rate, 6),
            threshold,
            checked_at,
            message="point-in-time-safe financial key fields coverage below threshold",
        )
    )
    for item in stage10_config["required_items"]:
        missing = coverage[item]
        rows.append(
            _row(
                run_id,
                f"financial_key_field_missing:{item}",
                "financial_quality",
                "warning",
                "PASS" if not missing else "FAIL",
                missing,
                [],
                checked_at,
                message="symbols missing a point-in-time-safe value for this key field",
            )
        )
    return rows


def _elapsed_rows(
    run_id: str,
    checked_at: pd.Timestamp,
    elapsed: pd.DataFrame,
    config: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    thresholds = config["performance"]["max_elapsed_seconds"]
    multiplier = float(config["performance"]["elapsed_spike_multiplier"])
    baseline_elapsed = (baseline or {}).get("interface_elapsed_seconds", {})
    rows: list[dict[str, Any]] = []
    observed: dict[str, float] = {}
    if not elapsed.empty:
        frame = elapsed.copy()
        frame["elapsed_seconds"] = pd.to_numeric(
            frame["elapsed_seconds"], errors="coerce"
        )
        frame = frame.loc[frame["elapsed_seconds"].notna()]
        observed = {
            str(interface): float(values.max())
            for interface, values in frame.groupby("interface_name")["elapsed_seconds"]
        }
    interfaces = sorted(set(thresholds).union(observed))
    for interface in interfaces:
        if interface not in observed:
            rows.append(
                _row(
                    run_id,
                    f"interface_elapsed_time_spike:{interface}",
                    "performance",
                    "warning",
                    "WARN",
                    "missing",
                    thresholds.get(interface, "no-threshold"),
                    checked_at,
                    interface_name=interface,
                    message="no elapsed-time evidence for this interface in current reports",
                )
            )
            continue
        previous = baseline_elapsed.get(interface)
        expected = (
            previous * multiplier
            if previous is not None
            else thresholds.get(interface, float("inf"))
        )
        failed = observed[interface] > expected
        rows.append(
            _row(
                run_id,
                f"interface_elapsed_time_spike:{interface}",
                "performance",
                "warning",
                "FAIL" if failed else "PASS",
                round(observed[interface], 6),
                round(expected, 6) if previous is not None else thresholds.get(interface, "no-threshold"),
                checked_at,
                interface_name=interface,
                message="interface execution time above baseline spike or configured maximum",
            )
        )
    return rows


def run_daily_quality_checks(
    *,
    run_id: str,
    checked_at: pd.Timestamp,
    tables: dict[str, pd.DataFrame],
    expected_symbols: list[str],
    config: dict[str, Any],
    stage10_config: dict[str, Any],
    as_of_date: pd.Timestamp,
    baseline: dict[str, Any] | None = None,
    elapsed: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Run every Stage 15.1 daily quality check over local Stage 5 facts."""
    rows: list[dict[str, Any]] = []
    rows.extend(_row_count_rows(run_id, checked_at, tables, config, baseline))
    rows.extend(
        _latest_trade_date_rows(
            run_id, checked_at, tables[TABLE_DAILY], as_of_date, config
        )
    )
    rows.extend(_schema_rows(run_id, checked_at, tables, config, baseline))
    rows.extend(_coverage_rows(run_id, checked_at, expected_symbols, tables))
    rows.extend(_ohlc_rows(run_id, checked_at, tables[TABLE_DAILY]))
    rows.extend(_duplicate_rows(run_id, checked_at, tables))
    rows.extend(_negative_volume_rows(run_id, checked_at, tables))
    rows.extend(
        _pe_pb_missing_rows(
            run_id, checked_at, tables[TABLE_SPOT], config
        )
    )
    rows.extend(
        _financial_key_field_rows(
            run_id,
            checked_at,
            tables["fact_" + "financial_" + "statement"],
            stage10_config,
            expected_symbols,
            config,
        )
    )
    rows.extend(
        _elapsed_rows(
            run_id,
            checked_at,
            elapsed if elapsed is not None else pd.DataFrame(),
            config,
            baseline,
        )
    )
    return pd.DataFrame(rows, columns=CHECK_COLUMNS)


def _latest_financial_value(
    statements: pd.DataFrame,
    stage10_config: dict[str, Any],
    symbol: str,
    item: str,
) -> tuple[str, str, str] | None:
    lookup = _financial_mapping_lookup(stage10_config)
    aliases = set()
    for statement_type, mapping in stage10_config["statement_mappings"].items():
        for canonical, specification in mapping.items():
            if canonical != item:
                continue
            values = (
                specification.get("priority")
                if isinstance(specification, dict)
                else specification
            )
            aliases.update(
                (str(statement_type), str(alias)) for alias in values
            )
    candidates = statements.loc[
        statements["symbol"].astype("string").str.zfill(6).eq(symbol)
        & statements["announcement_date"].notna()
        & statements["potential_lookahead"].astype("boolean").fillna(False).eq(False)
    ].copy()
    if candidates.empty:
        return None
    candidates["_canonical"] = [
        lookup.get((str(kind), str(column)))
        for kind, column in zip(candidates["statement_type"], candidates["source_column"])
    ]
    candidates = candidates.loc[candidates["_canonical"].eq(item)]
    candidates["_value"] = pd.to_numeric(
        candidates["line_item_value"], errors="coerce"
    )
    candidates = candidates.loc[candidates["_value"].notna()]
    if candidates.empty:
        return None
    latest_period = candidates["report_period"].max()
    best = candidates.loc[candidates["report_period"].eq(latest_period)].iloc[0]
    return (
        str(best["_value"]),
        str(pd.Timestamp(latest_period).date()),
        str(best["source_column"]),
    )


def build_cross_validation(
    *,
    run_id: str,
    as_of_date: pd.Timestamp,
    daily: pd.DataFrame,
    spot: pd.DataFrame,
    statements: pd.DataFrame,
    limit_events: pd.DataFrame | None,
    symbols: list[str],
    config: dict[str, Any],
    stage10_config: dict[str, Any],
) -> pd.DataFrame:
    """Build the Stage 15.2 cross-validation evidence snapshot."""
    rows: list[dict[str, Any]] = []
    adjust = config["cross_validation"]["price_adjust_type"]
    last_days = int(config["cross_validation"]["last_trade_days"])
    formal = limit_events
    if formal is not None and not formal.empty:
        formal = formal.loc[formal["event_type"].astype(str).eq("limit_up")].copy()
        formal = formal.sort_values("trade_date", kind="mergesort")
    for symbol in symbols:
        recent = daily.loc[
            daily["symbol"].astype("string").str.zfill(6).eq(symbol)
            & daily["adjust_type"].astype(str).eq(adjust)
        ].copy()
        recent = recent.sort_values("trade_date", kind="mergesort")
        recent = recent.tail(last_days)
        if recent.empty:
            rows.append(
                {
                    "run_id": run_id,
                    "symbol": symbol,
                    "check_item": "last_5_days_close_volume",
                    "observed_value": "[]",
                    "source_table": TABLE_DAILY,
                    "as_of_date": as_of_date.date(),
                    "verification_status": "UNAVAILABLE",
                    "note": f"no {adjust} daily rows for cross-validation",
                }
            )
        else:
            payload = []
            for item in recent.itertuples(index=False):
                payload.append(
                    {
                        "trade_date": str(item.trade_date),
                        "close": None if pd.isna(item.close) else float(item.close),
                        "volume_lot": None if pd.isna(item.volume_lot) else float(item.volume_lot),
                    }
                )
            rows.append(
                {
                    "run_id": run_id,
                    "symbol": symbol,
                    "check_item": "last_5_days_close_volume",
                    "observed_value": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    "source_table": TABLE_DAILY,
                    "as_of_date": as_of_date.date(),
                    "verification_status": "REVIEW",
                    "note": "manual cross-check of close and volume against an external quote source",
                }
            )
        revenue = _latest_financial_value(
            statements, stage10_config, symbol, "revenue"
        )
        rows.append(
            {
                "run_id": run_id,
                "symbol": symbol,
                "check_item": "latest_revenue",
                "observed_value": (
                    f"{revenue[0]}@{revenue[1]}"
                    if revenue
                    else "unavailable"
                ),
                "source_table": "fact_financial_statement",
                "as_of_date": as_of_date.date(),
                "verification_status": "REVIEW" if revenue else "UNAVAILABLE",
                "note": (
                    "point-in-time-safe latest report period"
                    if revenue
                    else "no point-in-time-safe revenue value"
                ),
            }
        )
        parent = _latest_financial_value(
            statements, stage10_config, symbol, "parent_net_profit"
        )
        fallback = _latest_financial_value(
            statements, stage10_config, symbol, "net_profit"
        )
        chosen = parent or fallback
        rows.append(
            {
                "run_id": run_id,
                "symbol": symbol,
                "check_item": "latest_net_profit",
                "observed_value": (
                    f"{chosen[0]}@{chosen[1]}"
                    if chosen
                    else "unavailable"
                ),
                "source_table": "fact_financial_statement",
                "as_of_date": as_of_date.date(),
                "verification_status": "REVIEW" if chosen else "UNAVAILABLE",
                "note": (
                    "point-in-time-safe latest report period"
                    if parent
                    else "net_profit used because parent_net_profit is unavailable"
                    if fallback
                    else "no point-in-time-safe net profit value"
                ),
            }
        )
        latest_spot = spot.loc[
            spot["symbol"].astype("string").str.zfill(6).eq(symbol)
        ].copy()
        if not latest_spot.empty:
            latest_spot = latest_spot.assign(
                _scope_rank=np.where(
                    latest_spot["snapshot_scope"].astype(str).eq("target_16"),
                    0,
                    1,
                )
            )
            latest_spot = latest_spot.sort_values(
                ["_scope_rank", "snapshot_at"], kind="mergesort"
            )
            latest_spot = latest_spot.iloc[-1:]
        for item, column in (
            ("latest_pe_dynamic", "pe_dynamic"),
            ("latest_pb", "pb"),
        ):
            value = (
                None
                if latest_spot.empty
                else latest_spot.iloc[0].get(column)
            )
            available = value is not None and not pd.isna(value)
            rows.append(
                {
                    "run_id": run_id,
                    "symbol": symbol,
                    "check_item": item,
                    "observed_value": str(value) if available else "unavailable",
                    "source_table": TABLE_SPOT,
                    "as_of_date": as_of_date.date(),
                    "verification_status": "REVIEW" if available else "UNAVAILABLE",
                    "note": (
                        "latest snapshot cross-check"
                        if available
                        else "no latest snapshot value"
                    ),
                }
            )
        if formal is None or formal.empty:
            for item, note in (
                ("recent_limit_up_day", "Stage 8 formal limit events unavailable"),
                (
                    "next_day_open_after_limit_up",
                    "Stage 8 formal limit events unavailable",
                ),
            ):
                rows.append(
                    {
                        "run_id": run_id,
                        "symbol": symbol,
                        "check_item": item,
                        "observed_value": "unavailable",
                        "source_table": TABLE_LIMIT_SOURCE,
                        "as_of_date": as_of_date.date(),
                        "verification_status": "UNAVAILABLE",
                        "note": note,
                    }
                )
        else:
            for symbol_events in (formal.loc[formal["symbol"].astype(str).eq(symbol)],):
                if symbol_events.empty:
                    rows.append(
                        {
                            "run_id": run_id,
                            "symbol": symbol,
                            "check_item": "recent_limit_up_day",
                            "observed_value": "unavailable",
                            "source_table": TABLE_LIMIT_SOURCE,
                            "as_of_date": as_of_date.date(),
                            "verification_status": "UNAVAILABLE",
                            "note": "no formal limit-up event in Stage 8 output",
                        }
                    )
                    rows.append(
                        {
                            "run_id": run_id,
                            "symbol": symbol,
                            "check_item": "next_day_open_after_limit_up",
                            "observed_value": "unavailable",
                            "source_table": TABLE_LIMIT_SOURCE,
                            "as_of_date": as_of_date.date(),
                            "verification_status": "UNAVAILABLE",
                            "note": "no formal limit-up event in Stage 8 output",
                        }
                    )
                    continue
                latest_event = symbol_events.iloc[-1]
                rows.append(
                    {
                        "run_id": run_id,
                        "symbol": symbol,
                        "check_item": "recent_limit_up_day",
                        "observed_value": str(latest_event["trade_date"]),
                        "source_table": TABLE_LIMIT_SOURCE,
                        "as_of_date": as_of_date.date(),
                        "verification_status": "REVIEW",
                        "note": "latest formal limit-up day from Stage 8",
                    }
                )
                next_open = latest_event.get("next_open")
                rows.append(
                    {
                        "run_id": run_id,
                        "symbol": symbol,
                        "check_item": "next_day_open_after_limit_up",
                        "observed_value": (
                            str(next_open)
                            if next_open is not None and not pd.isna(next_open)
                            else "unavailable"
                        ),
                        "source_table": TABLE_LIMIT_SOURCE,
                        "as_of_date": as_of_date.date(),
                        "verification_status": "REVIEW" if next_open is not None else "UNAVAILABLE",
                        "note": "next-day open after the latest formal limit-up event",
                    }
                )
    return pd.DataFrame(rows, columns=CROSS_VALIDATION_COLUMNS)


def build_risk_log(
    *,
    run_id: str,
    checked_at: pd.Timestamp,
    checks: pd.DataFrame,
    cross_validation: pd.DataFrame,
    stage8_blocker_codes: list[str],
    config: dict[str, Any],
) -> pd.DataFrame:
    """Build the Stage 15.3 risk log with the documented column contract."""
    rows: list[dict[str, Any]] = []
    for record in checks.itertuples(index=False):
        if record.status not in {"FAIL", "WARN"}:
            continue
        rows.append(
            {
                "risk_id": str(uuid.uuid4()),
                "detected_at": checked_at,
                "category": record.category,
                "interface_name": str(record.interface_name or ""),
                "symbol": "",
                "severity": record.severity,
                "description": f"{record.check_name}: {record.message or record.observed_value}",
                "impact": "Daily quality gate breached; downstream analysis may use stale or invalid data",
                "mitigation": "Inspect the affected dataset/interface and rerun Stage 15 after remediation",
                "status": "open",
            }
        )
    blocked = config["stage8"]["blocker_codes"]
    for code in stage8_blocker_codes or blocked:
        rows.append(
            {
                "risk_id": str(uuid.uuid4()),
                "detected_at": checked_at,
                "category": "blocked_input",
                "interface_name": "stage8",
                "symbol": "",
                "severity": "warning",
                "description": code,
                "impact": (
                    "Formal limit-up statistics stay fail-closed; Stage 15 "
                    "cross-validation limit-up items are unavailable"
                ),
                "mitigation": (
                    "Supply authoritative limit rules and security status "
                    "history before publishing formal annual statistics"
                ),
                "status": "blocked",
            }
        )
    if not cross_validation.empty:
        for record in cross_validation.itertuples(index=False):
            if record.verification_status != "UNAVAILABLE":
                continue
            rows.append(
                {
                    "risk_id": str(uuid.uuid4()),
                    "detected_at": checked_at,
                    "category": "data_completeness",
                    "interface_name": "",
                    "symbol": str(record.symbol),
                    "severity": "warning",
                    "description": f"cross-validation item unavailable: {record.check_item}",
                    "impact": f"Manual verification of {record.symbol} {record.check_item} cannot be completed",
                    "mitigation": "Re-run after the upstream input is available or document the gap",
                    "status": "open",
                }
            )
    return pd.DataFrame(rows, columns=RISK_LOG_COLUMNS)
