"""Stage 10 financial normalization, indicators, valuation, and summaries.

The module is deliberately network-free.  It consumes the point-in-time-safe
Stage 5 facts and never manufactures missing financial or valuation values.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml


RAW_COLUMNS = [
    "run_id", "symbol", "statement_type", "report_period", "announcement_date",
    "update_time", "source_name", "source_reference", "source_run_id",
    "source_column", "source_item_code", "source_item_name", "source_value",
    "source_unit", "cumulative_flag", "version", "version_key",
]
FACT_COLUMNS = [
    "run_id", "symbol", "statement_type", "report_period", "announcement_date",
    "update_time", "item_code", "source_field", "selected_source",
    "conflict_flag", "conflict_value_mismatch", "item_value", "cumulative_value",
    "single_quarter_value", "period_type", "conversion_status", "unit",
    "cumulative_flag", "source_name", "source_reference", "source_run_id",
    "version", "version_key",
]
INDICATOR_COLUMNS = [
    "run_id", "symbol", "report_period", "indicator_code", "indicator_value",
    "calculation_status", "calculation_version", "source_period_start",
    "source_period_end", "created_at",
]
VALUATION_COLUMNS = [
    "run_id", "snapshot_time", "symbol", "pe", "pb", "market_cap", "source",
    "valuation_type", "pe_status", "pb_status", "valuation_status",
    "source_run_id", "created_at",
]
SUMMARY_COLUMNS = [
    "run_id", "symbol", "as_of_date", "revenue_growth", "profit_growth",
    "profitability_score", "financial_health_score", "valuation_status",
    "summary_explanation", "model_version", "config_version",
    "publication_status", "created_at",
]


def load_stage10_config(path: Path) -> tuple[dict[str, Any], str]:
    """Load and validate Stage 10 configuration with a reproducible hash."""
    raw = path.read_bytes()
    config = yaml.safe_load(raw)
    required = {
        "schema_version", "model_version", "calculation_version",
        "statement_mappings", "flow_statement_types", "required_items",
    }
    missing = sorted(required.difference(config or {}))
    if missing:
        raise ValueError(f"Stage 10 configuration missing keys: {missing}")
    aliases: set[str] = set()
    for mapping in config["statement_mappings"].values():
        for specification in mapping.values():
            values = specification.get("priority") if isinstance(specification, dict) else specification
            if not isinstance(values, list) or not values:
                raise ValueError("Every Stage 10 statement mapping requires a non-empty priority list")
            aliases.update(str(value) for value in values)
    if not aliases:
        raise ValueError("Stage 10 statement mappings are empty")
    return config, hashlib.sha256(raw).hexdigest()


def _period_type(value: pd.Timestamp) -> str:
    month = pd.Timestamp(value).month
    labels = {3: "Q1", 6: "H1", 9: "Q1-Q3", 12: "FY"}
    if month not in labels:
        raise ValueError(f"Unsupported financial report period: {value.date()}")
    return labels[month]


def _version_key(row: pd.Series) -> str:
    values = [
        row.get("symbol"), row.get("statement_type"), row.get("report_period"),
        row.get("source_run_id"), row.get("announcement_date"),
        row.get("source_file"), row.get("source_row_number"),
    ]
    return hashlib.sha256("\x1f".join("" if pd.isna(v) else str(v) for v in values).encode()).hexdigest()[:24]


def _mapping_lookup(config: dict[str, Any]) -> dict[tuple[str, str], tuple[str, int]]:
    result: dict[tuple[str, str], tuple[str, int]] = {}
    for statement_type, mapping in config["statement_mappings"].items():
        for canonical, specification in mapping.items():
            aliases = specification.get("priority") if isinstance(specification, dict) else specification
            for priority, alias in enumerate(aliases):
                key = (str(statement_type), str(alias))
                if key in result:
                    raise ValueError(f"Duplicate financial source alias: {key}")
                result[key] = (str(canonical), priority)
    return result


def normalize_financial_statements(
    statements: pd.DataFrame, *, run_id: str, config: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Map Stage 5 long-form statements to the Stage 10 canonical facts.

    Different source runs are preserved as distinct versions.  Only mapped
    fields are selected; no value is imputed and no announcement date is made up.
    """
    required = {
        "symbol", "statement_type", "report_period", "announcement_date",
        "line_item_code", "line_item_name_source", "line_item_value",
        "unit_canonical", "source_column", "source_file", "source_run_id",
        "source_row_number",
    }
    missing = sorted(required.difference(statements.columns))
    if missing:
        raise ValueError(f"Financial statement input missing columns: {missing}")
    source = statements.copy()
    source["symbol"] = source["symbol"].astype("string").str.zfill(6)
    source["report_period"] = pd.to_datetime(source["report_period"], errors="coerce").dt.normalize()
    source["announcement_date"] = pd.to_datetime(source["announcement_date"], errors="coerce").dt.normalize()
    if source["report_period"].isna().any():
        raise ValueError("Financial statement report_period contains invalid values")
    source["period_type"] = source["report_period"].map(_period_type)
    lookup = _mapping_lookup(config)
    mapped = [
        lookup.get((str(kind), str(column)))
        for kind, column in zip(source["statement_type"], source["source_column"])
    ]
    source["item_code"] = [value[0] if value else None for value in mapped]
    source["_priority"] = [value[1] if value else None for value in mapped]
    source = source.loc[source["item_code"].notna()].copy()
    allowed_units = {"CNY_yuan", "CNY_per_share", "decimal"}
    invalid_units = sorted(set(source["unit_canonical"].dropna().astype(str)).difference(allowed_units))
    if invalid_units:
        raise ValueError(f"Unsupported financial units: {invalid_units}")
    source["cumulative_flag"] = source["statement_type"].isin(config["flow_statement_types"])
    source["version"] = source["source_run_id"].astype(str)
    source["version_key"] = source.apply(_version_key, axis=1)
    source["update_time"] = pd.NaT
    source["source_name"] = str(config.get("source_name", "AKShare"))
    source["source_reference"] = source["source_file"].astype(str)
    source["source_value"] = pd.to_numeric(source["line_item_value"], errors="coerce")
    source["source_unit"] = source["unit_canonical"].fillna("unknown").astype(str)
    source["run_id"] = run_id
    raw = source.rename(columns={
        "line_item_code": "source_item_code",
        "line_item_name_source": "source_item_name",
    })[RAW_COLUMNS].copy()
    duplicate_key = [
        "run_id", "symbol", "statement_type", "report_period",
        "source_column", "version_key",
    ]
    if raw.duplicated(duplicate_key).any():
        raise ValueError("Duplicate financial report rows in the same source version")
    if source.empty:
        return raw.reset_index(drop=True), pd.DataFrame(columns=FACT_COLUMNS)
    selected_rows: list[pd.Series] = []
    selection_key = [
        "symbol", "statement_type", "report_period", "announcement_date",
        "item_code", "source_run_id",
    ]
    for _, candidates in source.groupby(selection_key, dropna=False, sort=False):
        duplicate_sources = candidates["source_column"].astype(str).duplicated()
        if duplicate_sources.any():
            raise ValueError("Duplicate source field within the same financial report version")
        ordered = candidates.sort_values(
            ["_priority", "source_row_number"], kind="mergesort"
        )
        available = ordered.loc[ordered["source_value"].notna()]
        chosen = (available.iloc[0] if not available.empty else ordered.iloc[0]).copy()
        values = available["source_value"].astype(float).tolist()
        mismatch = any(
            not np.isclose(values[0], value, rtol=0, atol=1e-12)
            for value in values[1:]
        ) if values else False
        chosen["source_field"] = str(chosen["source_column"])
        chosen["selected_source"] = str(chosen["source_column"])
        chosen["conflict_flag"] = bool(candidates["source_column"].nunique() > 1)
        chosen["conflict_value_mismatch"] = bool(mismatch)
        selected_rows.append(chosen)
    selected = pd.DataFrame(selected_rows)
    facts = pd.DataFrame({
        "run_id": selected["run_id"], "symbol": selected["symbol"],
        "statement_type": selected["statement_type"],
        "report_period": selected["report_period"],
        "announcement_date": selected["announcement_date"],
        "update_time": selected["update_time"], "item_code": selected["item_code"],
        "source_field": selected["source_field"],
        "selected_source": selected["selected_source"],
        "conflict_flag": selected["conflict_flag"],
        "conflict_value_mismatch": selected["conflict_value_mismatch"],
        "item_value": selected["source_value"],
        "cumulative_value": selected["source_value"].where(selected["cumulative_flag"]),
        "single_quarter_value": selected["source_value"].where(~selected["cumulative_flag"]),
        "period_type": selected["period_type"],
        "conversion_status": np.where(selected["cumulative_flag"], "pending", "not_applicable"),
        "unit": selected["source_unit"], "cumulative_flag": selected["cumulative_flag"],
        "source_name": selected["source_name"], "source_reference": selected["source_reference"],
        "source_run_id": selected["source_run_id"], "version": selected["version"],
        "version_key": selected["version_key"],
    })
    return raw.reset_index(drop=True), facts[FACT_COLUMNS].reset_index(drop=True)


def cumulative_to_single_quarter(facts: pd.DataFrame) -> pd.DataFrame:
    """Convert cumulative flow facts to Q1/Q2/Q3/Q4 without hiding gaps."""
    result = facts.copy()
    if result.empty:
        return result
    key = ["symbol", "statement_type", "item_code", "version"]
    period_key = key + ["report_period"]
    if result.duplicated(period_key).any():
        raise ValueError("Duplicate report period within a financial version")
    result = result.sort_values(period_key, kind="mergesort").reset_index(drop=True)
    for _, indexes in result.groupby(key, sort=False).groups.items():
        group = result.loc[indexes]
        if not bool(group["cumulative_flag"].iloc[0]):
            continue
        by_period = {pd.Timestamp(row.report_period): row for row in group.itertuples()}
        for index in indexes:
            row = result.loc[index]
            period = pd.Timestamp(row["report_period"])
            current = row["cumulative_value"]
            if pd.isna(current):
                result.at[index, "single_quarter_value"] = np.nan
                result.at[index, "conversion_status"] = "source_missing"
                continue
            label = row["period_type"]
            if label == "Q1":
                result.at[index, "single_quarter_value"] = current
                result.at[index, "conversion_status"] = "direct_q1"
                continue
            prior_month = {"H1": 3, "Q1-Q3": 6, "FY": 9}[label]
            prior_period = pd.Timestamp(year=period.year, month=prior_month, day=1) + pd.offsets.MonthEnd(0)
            prior = by_period.get(prior_period)
            if prior is None or pd.isna(prior.cumulative_value):
                result.at[index, "single_quarter_value"] = np.nan
                result.at[index, "conversion_status"] = "missing_prior_cumulative"
            elif str(prior.unit) != str(row["unit"]):
                raise ValueError(
                    f"Financial unit mismatch for {row['symbol']} {row['item_code']} {period.date()}"
                )
            else:
                result.at[index, "single_quarter_value"] = float(current) - float(prior.cumulative_value)
                result.at[index, "conversion_status"] = "derived_from_cumulative"
    return result[FACT_COLUMNS]


def _safe_divide(numerator: Any, denominator: Any) -> float | None:
    if pd.isna(numerator) or pd.isna(denominator) or float(denominator) == 0:
        return None
    value = float(numerator) / float(denominator)
    return value if np.isfinite(value) else None


def _latest_versions(facts: pd.DataFrame) -> pd.DataFrame:
    ordered = facts.copy()
    ordered["_announcement"] = pd.to_datetime(ordered["announcement_date"], errors="coerce")
    ordered = ordered.sort_values(
        ["symbol", "statement_type", "item_code", "report_period", "_announcement", "version"],
        na_position="first", kind="mergesort",
    )
    return ordered.drop_duplicates(
        ["symbol", "statement_type", "item_code", "report_period"], keep="last"
    ).drop(columns="_announcement")


def calculate_fundamental_indicators(
    facts: pd.DataFrame, *, run_id: str, calculation_version: str,
    created_at: pd.Timestamp,
) -> pd.DataFrame:
    """Calculate point-in-time quarterly/TTM fundamental indicators."""
    if facts.empty:
        return pd.DataFrame(columns=INDICATOR_COLUMNS)
    latest = _latest_versions(facts)
    values = latest.pivot_table(
        index=["symbol", "report_period"], columns="item_code",
        values="single_quarter_value", aggfunc="first",
    ).sort_index()
    direct = latest.pivot_table(
        index=["symbol", "report_period"], columns="item_code",
        values="item_value", aggfunc="first",
    ).sort_index()
    rows: list[dict[str, Any]] = []
    base_codes = [
        "total_assets", "total_liabilities", "shareholders_equity", "revenue",
        "operating_cost", "operating_profit", "total_profit", "net_profit",
        "parent_net_profit", "deducted_parent_net_profit", "operating_cashflow", "eps",
    ]
    for symbol in sorted(set(latest["symbol"].astype(str))):
        periods = sorted(set(pd.Timestamp(value) for value in latest.loc[latest.symbol.eq(symbol), "report_period"]))
        for period in periods:
            index = (symbol, period)
            quarter_periods = list(pd.date_range(end=period, periods=4, freq="QE"))

            def direct_value(code: str) -> Any:
                return direct.at[index, code] if index in direct.index and code in direct.columns else np.nan

            def quarter_value(code: str, target: pd.Timestamp = period) -> Any:
                key = (symbol, target)
                return values.at[key, code] if key in values.index and code in values.columns else np.nan

            def ttm(code: str) -> float | None:
                observed = [quarter_value(code, target) for target in quarter_periods]
                return float(sum(observed)) if all(not pd.isna(value) for value in observed) else None

            metrics: dict[str, tuple[Any, str]] = {}
            for code in base_codes:
                value = quarter_value(code) if code in {"revenue", "operating_cost", "operating_profit", "total_profit", "net_profit", "parent_net_profit", "deducted_parent_net_profit", "operating_cashflow"} else direct_value(code)
                metrics[code] = (value, "calculated" if not pd.isna(value) else "unavailable")
            revenue_ttm = ttm("revenue")
            cost_ttm = ttm("operating_cost")
            profit_ttm = ttm("parent_net_profit")
            if profit_ttm is None:
                profit_ttm = ttm("net_profit")
            cash_ttm = ttm("operating_cashflow")
            prior_year = period - pd.DateOffset(years=1)
            revenue_yoy = _safe_divide(
                quarter_value("revenue") - quarter_value("revenue", prior_year)
                if not pd.isna(quarter_value("revenue")) and not pd.isna(quarter_value("revenue", prior_year)) else np.nan,
                abs(quarter_value("revenue", prior_year)),
            )
            current_profit = quarter_value("parent_net_profit")
            prior_profit = quarter_value("parent_net_profit", prior_year)
            net_profit_yoy = _safe_divide(
                current_profit - prior_profit if not pd.isna(current_profit) and not pd.isna(prior_profit) else np.nan,
                abs(prior_profit),
            )
            gross_margin = _safe_divide(
                revenue_ttm - cost_ttm if revenue_ttm is not None and cost_ttm is not None else np.nan,
                revenue_ttm,
            )
            net_margin = _safe_divide(profit_ttm, revenue_ttm)
            equity = direct_value("shareholders_equity")
            prior_equity_key = (symbol, prior_year)
            prior_equity = direct.at[prior_equity_key, "shareholders_equity"] if prior_equity_key in direct.index and "shareholders_equity" in direct.columns else np.nan
            average_equity = (float(equity) + float(prior_equity)) / 2 if not pd.isna(equity) and not pd.isna(prior_equity) else equity
            roe = _safe_divide(profit_ttm, average_equity)
            leverage = _safe_divide(direct_value("total_liabilities"), direct_value("total_assets"))
            metrics.update({
                "revenue_ttm": (revenue_ttm, "calculated" if revenue_ttm is not None else "insufficient_four_quarters"),
                "net_profit_ttm": (profit_ttm, "calculated" if profit_ttm is not None else "insufficient_four_quarters"),
                "revenue_yoy": (revenue_yoy, "calculated" if revenue_yoy is not None else "missing_prior_year"),
                "net_profit_yoy": (net_profit_yoy, "calculated" if net_profit_yoy is not None else "missing_prior_year"),
                "gross_margin": (gross_margin, "calculated" if gross_margin is not None else "unavailable"),
                "net_margin": (net_margin, "calculated" if net_margin is not None else "unavailable"),
                "roe": (roe, "calculated" if roe is not None else "unavailable"),
                "operating_cashflow_ttm": (cash_ttm, "calculated" if cash_ttm is not None else "insufficient_four_quarters"),
                "cashflow_profit_ratio": (_safe_divide(cash_ttm, profit_ttm), "calculated" if _safe_divide(cash_ttm, profit_ttm) is not None else "unavailable"),
                "asset_liability_ratio": (leverage, "calculated" if leverage is not None else "unavailable"),
            })
            for code, (value, status) in metrics.items():
                rows.append({
                    "run_id": run_id, "symbol": symbol, "report_period": period,
                    "indicator_code": code,
                    "indicator_value": None if pd.isna(value) else float(value),
                    "calculation_status": status,
                    "calculation_version": calculation_version,
                    "source_period_start": quarter_periods[0] if code.endswith("_ttm") or code in {"gross_margin", "net_margin", "roe", "cashflow_profit_ratio"} else period,
                    "source_period_end": period, "created_at": created_at,
                })
    return pd.DataFrame(rows, columns=INDICATOR_COLUMNS)


def normalize_valuation_snapshot(
    spot: pd.DataFrame, *, run_id: str, source: str, created_at: pd.Timestamp,
    valuation_type: str = "snapshot",
) -> pd.DataFrame:
    """Normalize current valuation snapshots without backfilling history."""
    if valuation_type != "snapshot":
        raise ValueError("Stage 10 only accepts current valuation snapshot input; historical values require an audited historical source")
    required = {"snapshot_at", "symbol", "pe_dynamic", "pb", "market_cap_cny", "source_run_id"}
    missing = sorted(required.difference(spot.columns))
    if missing:
        raise ValueError(f"Valuation input missing columns: {missing}")
    result = pd.DataFrame({
        "run_id": run_id,
        "snapshot_time": pd.to_datetime(spot["snapshot_at"], errors="coerce", utc=True),
        "symbol": spot["symbol"].astype("string").str.zfill(6),
        "pe": pd.to_numeric(spot["pe_dynamic"], errors="coerce"),
        "pb": pd.to_numeric(spot["pb"], errors="coerce"),
        "market_cap": pd.to_numeric(spot["market_cap_cny"], errors="coerce"),
        "source": source, "valuation_type": valuation_type,
        "source_run_id": spot["source_run_id"].astype(str), "created_at": created_at,
    })
    if result["snapshot_time"].isna().any():
        raise ValueError("Valuation snapshot_time contains invalid values")
    result["pe_status"] = np.select(
        [result["pe"].isna(), result["pe"].le(0)],
        ["unavailable", "loss-making"], default="available",
    )
    result["pb_status"] = np.select(
        [result["pb"].isna(), result["pb"].le(0)],
        ["unavailable", "invalid"], default="available",
    )
    result["valuation_status"] = [
        "current valuation snapshot"
        + (f"; PE {pe_status}" if pe_status != "available" else "")
        + (f"; PB {pb_status}" if pb_status != "available" else "")
        for pe_status, pb_status in zip(result["pe_status"], result["pb_status"])
    ]
    return result[VALUATION_COLUMNS].drop_duplicates(
        ["run_id", "snapshot_time", "symbol", "source_run_id"], keep="last"
    ).reset_index(drop=True)


def build_fundamental_summary(
    indicators: pd.DataFrame, valuations: pd.DataFrame, *, run_id: str,
    as_of_date: pd.Timestamp, config: dict[str, Any], created_at: pd.Timestamp,
) -> pd.DataFrame:
    """Create descriptive, evidence-based summaries without investment advice."""
    rows: list[dict[str, Any]] = []
    for symbol in sorted(set(indicators["symbol"].astype(str))):
        subset = indicators.loc[indicators.symbol.eq(symbol)].copy()
        latest_period = subset["report_period"].max()
        current = subset.loc[subset.report_period.eq(latest_period)].set_index("indicator_code")

        def metric(code: str) -> float | None:
            if code not in current.index:
                return None
            value = current.at[code, "indicator_value"]
            if isinstance(value, pd.Series):
                value = value.iloc[-1]
            return None if pd.isna(value) else float(value)

        revenue_growth = metric("revenue_yoy")
        profit_growth = metric("net_profit_yoy")
        gross_margin, net_margin, roe = metric("gross_margin"), metric("net_margin"), metric("roe")
        leverage = metric("asset_liability_ratio")
        cash = metric("operating_cashflow_ttm")
        cash_ratio = metric("cashflow_profit_ratio")
        profitability = sum([
            config["score"]["profitability"]["gross_margin_positive"] if gross_margin is not None and gross_margin > 0 else 0,
            config["score"]["profitability"]["net_margin_positive"] if net_margin is not None and net_margin > 0 else 0,
            config["score"]["profitability"]["roe_positive"] if roe is not None and roe > 0 else 0,
        ])
        health_cfg = config["score"]["financial_health"]
        health = sum([
            health_cfg["leverage_score"] if leverage is not None and leverage <= health_cfg["asset_liability_ratio_below"] else 0,
            health_cfg["operating_cashflow_positive"] if cash is not None and cash > 0 else 0,
            health_cfg["cashflow_profit_ratio_positive"] if cash_ratio is not None and cash_ratio > 0 else 0,
        ])
        valuation = valuations.loc[valuations.symbol.eq(symbol)].sort_values("snapshot_time")
        if valuation.empty:
            valuation_status = "current valuation snapshot unavailable"
        else:
            latest_valuation = valuation.iloc[-1]
            valuation_status = "current valuation snapshot"
            if latest_valuation["pe_status"] != "available":
                valuation_status += f"; PE {latest_valuation['pe_status']}"
            if latest_valuation["pb_status"] != "available":
                valuation_status += f"; PB {latest_valuation['pb_status']}"
        evidence = [f"报告期 {pd.Timestamp(latest_period).date()}"]
        for label, value in [
            ("营业收入同比", revenue_growth), ("归母净利润同比", profit_growth),
            ("毛利率", gross_margin), ("净利率", net_margin), ("ROE", roe),
            ("资产负债率", leverage), ("经营现金流/利润", cash_ratio),
        ]:
            evidence.append(f"{label}={'不可用' if value is None else f'{value:.4f}'}")
        rows.append({
            "run_id": run_id, "symbol": symbol, "as_of_date": pd.Timestamp(as_of_date).normalize(),
            "revenue_growth": revenue_growth, "profit_growth": profit_growth,
            "profitability_score": float(profitability), "financial_health_score": float(health),
            "valuation_status": valuation_status,
            "summary_explanation": "；".join(evidence) + "。结果仅为财务数据分析，不构成投资建议。",
            "model_version": config["model_version"], "config_version": config["schema_version"],
            "publication_status": "pending",
            "created_at": created_at,
        })
    return pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
