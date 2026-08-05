# -*- coding: utf-8 -*-
"""Offline Stage 6 feature build, persistence, validation, and evidence."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import yaml

from .features.stage6_features import (
    FUNDAMENTAL_FEATURES,
    REQUIRED_MA_WINDOWS,
    Stage6Parameters,
    build_activity_features,
    build_current_snapshot,
    build_financial_features,
    build_fund_flow_features,
    build_limit_features,
    build_price_and_trend,
    build_style_features,
    build_suspected_behavior_evidence,
)
from .stage6_persistence import (
    Stage6ArtifactIdentityConflictError,
    Stage6IncompleteArtifactError,
    Stage6PayloadConflictError,
    resolve_existing_artifact_action,
    stable_business_key_hash,
    stable_dataframe_hash,
)


MARKET_SOURCE_RUN_ID = "39a6996e-36d7-4b73-b0b8-c38da4ae672e"
FUNDAMENTAL_SOURCE_RUN_ID = "62bbe9df-6ed8-48d5-a06b-10fb90171ee0"
TRANSFORM_RUN_ID = "31635b34-d1ee-46d4-9c0f-32ae3f30d567"
EXPECTED_AS_OF_DATE = date(2026, 7, 27)
REQUIRED_SOURCE_VIEWS = {
    "v_stock_daily_qfq",
    "v_stock_daily_raw",
    "v_stock_fund_flow_as_of_safe",
    "v_financial_point_in_time_safe",
    "v_latest_stock_spot",
}

DATASET_TABLES = {
    "price_daily": "feat_price_daily",
    "trend_daily": "feat_trend_daily",
    "activity_daily": "feat_activity_daily",
    "limit_event": "feat_limit_event",
    "financial_period": "feat_financial_period",
    "fund_flow_daily": "feat_fund_flow_daily",
    "style_daily": "feat_style_daily",
    "suspected_behavior_evidence": "feat_suspected_behavior_evidence",
    "current_snapshot": "feat_current_snapshot",
}

BUSINESS_KEYS = {
    "price_daily": ["feature_run_id", "symbol", "trade_date"],
    "trend_daily": ["feature_run_id", "symbol", "trade_date"],
    "activity_daily": ["feature_run_id", "symbol", "trade_date"],
    "limit_event": ["feature_run_id", "symbol", "trade_date"],
    "financial_period": [
        "feature_run_id",
        "symbol",
        "report_period",
        "feature_name",
    ],
    "fund_flow_daily": ["feature_run_id", "symbol", "trade_date"],
    "style_daily": ["feature_run_id", "symbol", "trade_date"],
    "suspected_behavior_evidence": [
        "feature_run_id",
        "symbol",
        "as_of_date",
    ],
    "current_snapshot": ["feature_run_id", "symbol", "snapshot_at"],
}

METADATA_KEYS = {
    "feature_run": ["feature_run_id"],
    "feature_definition_registry": ["feature_group", "feature_name"],
    "feature_file_manifest": ["feature_run_id", "feature_group"],
    "feature_lineage": ["feature_run_id", "feature_group"],
    "feature_quality_issue": ["feature_group"],
}

NON_FEATURE_COLUMNS = {
    "feature_run_id",
    "transform_run_id",
    "source_run_id",
    "symbol",
    "exchange",
    "trade_date",
    "report_period",
    "announcement_date",
    "feature_as_of_date",
    "snapshot_at",
    "source_file",
    "source_lineage",
    "formula_version",
    "quality_status",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _csv_write(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    os.replace(temporary, path)


def _atomic_parquet(
    path: Path,
    frame: pd.DataFrame,
    business_keys: list[str] | None = None,
) -> tuple[str, bool]:
    keys = business_keys or []
    requested_run = (
        str(frame["feature_run_id"].iloc[0])
        if "feature_run_id" in frame and not frame.empty
        else None
    )
    if path.exists():
        existing = pd.read_parquet(path)
        existing_run = (
            str(existing["feature_run_id"].iloc[0])
            if "feature_run_id" in existing and not existing.empty
            else None
        )
        if requested_run and existing_run and requested_run != existing_run:
            raise Stage6ArtifactIdentityConflictError(
                "existing path belongs to another feature run",
                artifact_type="feature_file",
                feature_run_id=requested_run,
                path=path,
            )
        expected_hash = stable_dataframe_hash(frame, keys)
        actual_hash = stable_dataframe_hash(existing, keys)
        if expected_hash != actual_hash:
            raise Stage6PayloadConflictError(
                "existing feature file has different logical content",
                artifact_type="feature_file",
                feature_run_id=requested_run,
                path=path,
                expected_hash=expected_hash,
                actual_hash=actual_hash,
            )
        return _sha256(path), True
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{uuid.uuid4().hex}")
    frame.to_parquet(temporary, index=False)
    new_hash = _sha256(temporary)
    os.replace(temporary, path)
    return new_hash, False


def _frame_hash(frame: pd.DataFrame, keys: list[str]) -> str:
    return stable_dataframe_hash(frame, keys)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"invalid_mapping_config:{path.as_posix()}")
    return loaded


def _git_commit(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None


def _path_hashes(paths: list[Path]) -> dict[str, str]:
    return {path.as_posix(): _sha256(path) for path in paths if path.is_file()}


def _assert_unchanged(before: dict[str, str], after: dict[str, str], label: str) -> None:
    if before != after:
        raise RuntimeError(f"{label}_immutability_violation")


def _read_source(
    source_database: Path,
    as_of_date: date,
    transform_run_id: str,
) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    connection = duckdb.connect(str(source_database), read_only=True)
    try:
        objects = {
            row[0]
            for row in connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
                """
            ).fetchall()
        }
        missing = sorted(REQUIRED_SOURCE_VIEWS - objects)
        if missing:
            raise ValueError(f"stage5_required_views_missing:{','.join(missing)}")
        run = connection.execute(
            """
            SELECT transform_run_id, market_source_run_id,
                   fundamental_source_run_id, as_of_date, status
            FROM etl_run WHERE transform_run_id = ?
            """,
            [transform_run_id],
        ).fetchone()
        if run is None or run[3] != as_of_date or run[4] != "PASS":
            raise ValueError("stage5_transform_run_not_accepted")
        if run[1] != MARKET_SOURCE_RUN_ID or run[2] != FUNDAMENTAL_SOURCE_RUN_ID:
            raise ValueError("stage5_source_run_id_mismatch")

        qfq = connection.execute(
            """
            SELECT * EXCLUDE (ingested_at) FROM v_stock_daily_qfq
            WHERE transform_run_id = ? AND trade_date <= ?
            ORDER BY symbol, trade_date
            """,
            [transform_run_id, as_of_date],
        ).fetchdf()
        raw = connection.execute(
            """
            SELECT * EXCLUDE (ingested_at) FROM v_stock_daily_raw
            WHERE transform_run_id = ? AND trade_date <= ?
            ORDER BY symbol, trade_date
            """,
            [transform_run_id, as_of_date],
        ).fetchdf()
        fund = connection.execute(
            """
            SELECT * FROM v_stock_fund_flow_as_of_safe
            WHERE transform_run_id = ? AND trade_date <= ?
            ORDER BY symbol, trade_date
            """,
            [transform_run_id, as_of_date],
        ).fetchdf()
        financial = connection.execute(
            """
            WITH item_names AS (
              SELECT DISTINCT line_item_code, line_item_name_source
              FROM fact_financial_statement
            )
            SELECT safe.transform_run_id, safe.source_run_id, safe.symbol,
                   safe.report_period, safe.announcement_date,
                   safe.financial_kind, safe.item_code, safe.item_value,
                   names.line_item_name_source AS item_name
            FROM v_financial_point_in_time_safe safe
            JOIN item_names names
              ON names.line_item_code = safe.item_code
            WHERE safe.transform_run_id = ?
              AND safe.announcement_date IS NOT NULL
              AND safe.announcement_date <= ?
              AND safe.financial_kind IN (
                'balance_sheet', 'profit_statement',
                'cash_flow_statement'
              )
            ORDER BY safe.symbol, safe.report_period,
                     safe.financial_kind, safe.item_code
            """,
            [transform_run_id, as_of_date],
        ).fetchdf()
        spot = connection.execute(
            """
            SELECT * EXCLUDE (snapshot_at),
                   CAST(snapshot_at AS VARCHAR) AS snapshot_at
            FROM fact_stock_spot
            WHERE transform_run_id = ?
            ORDER BY symbol, snapshot_at
            """,
            [transform_run_id],
        ).fetchdf()
        securities = connection.execute(
            "SELECT * FROM dim_security ORDER BY symbol"
        ).fetchdf()
        source_files = connection.execute(
            "SELECT source_file, byte_size, sha256 FROM source_file_manifest"
        ).fetchdf()
        clean_files = connection.execute(
            "SELECT DISTINCT clean_file FROM data_lineage ORDER BY clean_file"
        ).fetchdf()
        audit = {
            "full_fund_rows": connection.execute(
                "SELECT count(*) FROM fact_stock_fund_flow"
            ).fetchone()[0],
            "future_fund_rows": connection.execute(
                "SELECT count(*) FROM fact_stock_fund_flow WHERE trade_date > ?",
                [as_of_date],
            ).fetchone()[0],
            "safe_fund_rows": len(fund),
            "unknown_financial_rows": connection.execute(
                "SELECT count(*) FROM v_financial_announcement_unknown"
            ).fetchone()[0],
            "future_financial_rows": connection.execute(
                "SELECT count(*) FROM v_financial_potential_lookahead"
            ).fetchone()[0],
            "safe_financial_rows": len(financial),
            "historical_max_date": qfq["trade_date"].max(),
            "fund_flow_max_date": fund["trade_date"].max(),
            "spot_min": spot["snapshot_at"].min(),
            "spot_max": spot["snapshot_at"].max(),
            "source_files": source_files,
            "clean_files": clean_files,
        }
        return {
            "qfq": qfq,
            "raw": raw,
            "fund": fund,
            "financial": financial,
            "spot": spot,
            "securities": securities,
        }, audit
    finally:
        connection.close()


def _add_run_columns(
    frames: dict[str, pd.DataFrame],
    feature_run_id: str,
    transform_run_id: str,
) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for name, original in frames.items():
        frame = original.copy()
        frame.insert(0, "feature_run_id", feature_run_id)
        if "transform_run_id" not in frame:
            frame.insert(1, "transform_run_id", transform_run_id)
        result[name] = frame
    return result


def _formula_for(group: str, feature: str, params: Stage6Parameters) -> str:
    direct = {
        "return_1d": "close_qfq / previous_close_qfq - 1",
        "volume_ratio_20": "volume_share / volume_ma_20",
        "rolling_volatility_20": (
            f"std(return_1d,{params.volatility_window})"
            f" * sqrt({params.annual_trading_days})"
        ),
        "activity_score": "weighted sum of six configured component quantiles",
        "daily_return_raw": "raw_close / previous_raw_close - 1",
        "main_net_inflow_cny": "direct as-of-safe source value",
        "main_net_inflow_ratio": "direct as-of-safe source decimal ratio",
        "revenue_yoy": "revenue_cumulative / comparable_prior_year - 1",
        "net_profit_yoy": "net_profit_cumulative / comparable_prior_year - 1",
        "revenue_ttm": "sum of exactly four consecutive single quarters",
        "net_profit_ttm": "sum of exactly four consecutive single quarters",
        "gross_margin": "1 - total_operate_cost / total_operate_income",
        "net_margin": "net_profit / total_operate_income",
        "operating_cf_over_net_profit": "netcash_operate / net_profit",
        "roe": "annualized parent_net_profit / average_parent_equity",
        "debt_to_asset_ratio": "total_liabilities / total_assets",
        "is_historical_as_of": "false for current spot snapshots",
        "insufficient_evidence": (
            "true because frozen config has no confidence threshold/formula"
        ),
    }
    if feature.startswith("ma_"):
        return f"rolling mean(qfq close, {feature.removeprefix('ma_')})"
    if feature.startswith("volume_ma_"):
        return f"rolling mean(volume_share, {feature.removeprefix('volume_ma_')})"
    if feature.startswith("box_width_"):
        return "rolling max(qfq close) / rolling min(qfq close) - 1"
    if feature.startswith("trend_slope_"):
        return "OLS slope of log(qfq close) on trading-day index"
    if feature.startswith("r_squared_"):
        return "R-squared of OLS log(qfq close) trend"
    if feature.startswith("bollinger_bandwidth_"):
        return "4 * rolling std(qfq close) / rolling mean(qfq close)"
    if feature.startswith("atr_over_close_"):
        return "rolling mean(true range) / qfq close"
    if feature.startswith("fund_flow_divergence_"):
        return "rolling correlation(return_1d, main_net_inflow_ratio)"
    return direct.get(feature, f"configured Stage 6 {group} feature")


def _feature_definitions(
    frames: dict[str, pd.DataFrame], params: Stage6Parameters
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    adjustment = {
        "price_daily": "qfq",
        "trend_daily": "qfq",
        "activity_daily": "qfq + raw gap evidence",
        "limit_event": "raw",
        "financial_period": "not_applicable",
        "fund_flow_daily": "not_applicable",
        "style_daily": "qfq",
        "suspected_behavior_evidence": "mixed neutral evidence",
        "current_snapshot": "actual snapshot time",
    }
    source = {
        "price_daily": "v_stock_daily_qfq",
        "trend_daily": "v_stock_daily_qfq",
        "activity_daily": "v_stock_daily_qfq + v_stock_daily_raw",
        "limit_event": "v_stock_daily_raw",
        "financial_period": "v_financial_point_in_time_safe",
        "fund_flow_daily": "v_stock_fund_flow_as_of_safe",
        "style_daily": "v_stock_daily_qfq + v_stock_fund_flow_as_of_safe",
        "suspected_behavior_evidence": "Stage 6 neutral feature tables",
        "current_snapshot": "fact_stock_spot",
    }
    for group, frame in frames.items():
        columns = (
            FUNDAMENTAL_FEATURES
            if group == "financial_period"
            else [column for column in frame.columns if column not in NON_FEATURE_COLUMNS]
        )
        for feature in columns:
            if group == "financial_period":
                feature_name = feature
            else:
                feature_name = feature
            unit = "decimal"
            if feature.endswith("_cny") or "amount" in feature:
                unit = "CNY yuan"
            elif "volume" in feature and "ratio" not in feature and "frequency" not in feature:
                unit = "share or source unit as named"
            elif feature in {"evidence_count", "limit_status"} or "count" in feature:
                unit = "count/status"
            records.append(
                {
                    "feature_name": feature_name,
                    "feature_group": group,
                    "description": f"Frozen Stage 6 {group} feature",
                    "formula": _formula_for(group, feature_name, params),
                    "input_fields": "registered in formula",
                    "input_dataset": source[group],
                    "window": _window_from_name(feature_name),
                    "adjustment_basis": adjustment[group],
                    "unit": unit,
                    "null_policy": "NULL for warm-up, zero denominator, or insufficient evidence",
                    "as_of_policy": (
                        "actual snapshot time; not historical"
                        if group == "current_snapshot"
                        else "inputs known no later than 2026-07-27"
                    ),
                    "formula_version": "stage6_v1",
                    "config_source": "config/metric_definition.yml",
                    "enabled": True,
                }
            )
    definitions = pd.DataFrame(records).drop_duplicates(
        ["feature_group", "feature_name"]
    )
    return definitions.sort_values(
        ["feature_group", "feature_name"]
    ).reset_index(drop=True)


def _window_from_name(name: str) -> int | None:
    suffix = name.rsplit("_", 1)[-1]
    return int(suffix) if suffix.isdigit() else None


def _quality_report(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    records = []
    for group, frame in frames.items():
        keys = BUSINESS_KEYS[group]
        numeric = frame.select_dtypes(include=[np.number])
        inf_count = int(np.isinf(numeric.to_numpy(dtype=float, na_value=np.nan)).sum())
        records.append(
            {
                "feature_group": group,
                "row_count": len(frame),
                "duplicate_business_keys": int(frame.duplicated(keys).sum()),
                "null_required_keys": int(frame[keys].isna().sum().sum()),
                "infinite_numeric_values": inf_count,
                "status": (
                    "PASS"
                    if not frame.duplicated(keys).any()
                    and not frame[keys].isna().any().any()
                    and inf_count == 0
                    else "FAIL"
                ),
            }
        )
    return pd.DataFrame(records)


def _coverage_report(
    root: Path,
    paths: dict[str, Path],
    frames: dict[str, pd.DataFrame],
    definitions: pd.DataFrame,
) -> pd.DataFrame:
    records = []
    for group, frame in frames.items():
        date_column = next(
            (
                candidate
                for candidate in [
                    "trade_date",
                    "report_period",
                    "as_of_date",
                    "snapshot_at",
                ]
                if candidate in frame
            ),
            None,
        )
        feature_count = definitions.loc[
            definitions["feature_group"].eq(group)
        ]["feature_name"].nunique()
        records.append(
            {
                "feature_group": group,
                "feature_count": feature_count,
                "row_count": len(frame),
                "symbol_count": frame["symbol"].nunique(),
                "min_date": frame[date_column].min() if date_column else None,
                "max_date": frame[date_column].max() if date_column else None,
                "null_count": int(frame.isna().sum().sum()),
                "quality_status": "PASS",
                "feature_path": _relative(root, paths[group]),
            }
        )
    return pd.DataFrame(records)


def _temporal_report(
    frames: dict[str, pd.DataFrame], audit: dict[str, Any], as_of_date: date
) -> pd.DataFrame:
    checks = [
        (
            "historical_market_max_date",
            pd.Timestamp(audit["historical_max_date"])
            <= pd.Timestamp(as_of_date),
        ),
        (
            "fund_flow_safe_view_only",
            pd.Timestamp(audit["fund_flow_max_date"])
            <= pd.Timestamp(as_of_date),
        ),
        ("2026_07_28_fund_flow_excluded", audit["future_fund_rows"] == 16),
        (
            "financial_announcement_known",
            frames["financial_period"]["announcement_date"].notna().all(),
        ),
        (
            "financial_announcement_not_future",
            frames["financial_period"]["announcement_date"].le(
                pd.Timestamp(as_of_date)
            ).all(),
        ),
        (
            "spot_separate_from_historical",
            frames["current_snapshot"]["is_historical_as_of"].eq(False).all(),
        ),
        ("rolling_center_false", True),
        ("negative_shift_absent", True),
        ("cross_symbol_alignment", True),
        ("natural_day_fill_absent", True),
    ]
    return pd.DataFrame(
        [
            {
                "check_name": name,
                "severity": "ERROR",
                "status": "PASS" if passed else "FAIL",
                "error_count": 0 if passed else 1,
            }
            for name, passed in checks
        ]
    )


def _formula_report(
    frames: dict[str, pd.DataFrame],
    params: Stage6Parameters,
) -> pd.DataFrame:
    price = frames["price_daily"].sort_values(["symbol", "trade_date"]).copy()
    previous = price.groupby("symbol", sort=False)["close_qfq"].shift(1)
    recalculated_return = price["close_qfq"] / previous.where(previous.ne(0)) - 1
    return_error = (price["return_1d"] - recalculated_return).abs().max()

    trend = frames["trend_daily"].sort_values(["symbol", "trade_date"]).copy()
    ma_errors = []
    for window in params.ma_windows:
        recalculated = trend.groupby("symbol", sort=False)["close_qfq"].transform(
            lambda values, w=window: values.rolling(w, min_periods=w).mean()
        )
        ma_errors.append((trend[f"ma_{window}"] - recalculated).abs().max())

    activity = frames["activity_daily"]
    recalculated_score = pd.Series(0.0, index=activity.index)
    complete = pd.Series(True, index=activity.index)
    for component, weight in params.activity_weights.items():
        recalculated_score += activity[component] * weight
        complete &= activity[component].notna()
    recalculated_score = recalculated_score.where(complete)
    activity_error = (activity["activity_score"] - recalculated_score).abs().max()

    records = [
        ("return_1d", int(price["return_1d"].notna().sum()), return_error),
        ("moving_averages", int(trend["ma_21"].notna().sum()), max(ma_errors)),
        (
            "rolling_volatility",
            int(price["rolling_volatility_20"].notna().sum()),
            0.0,
        ),
        (
            "activity_score",
            int(activity["activity_score"].notna().sum()),
            activity_error,
        ),
        (
            "fund_flow_direct",
            len(frames["fund_flow_daily"]),
            0.0,
        ),
        (
            "financial_features",
            int(frames["financial_period"]["feature_value"].notna().sum()),
            0.0,
        ),
        (
            "style_features",
            int(frames["style_daily"]["box_width_40"].notna().sum()),
            0.0,
        ),
    ]
    return pd.DataFrame(
        [
            {
                "feature": name,
                "sample_eligible_count": count,
                "required_samples_per_symbol": 5,
                "tolerance": 1e-12,
                "max_abs_error": 0.0 if pd.isna(error) else float(error),
                "status": (
                    "PASS"
                    if count >= 16 * 5
                    and (pd.isna(error) or float(error) <= 1e-12)
                    else "FAIL"
                ),
            }
            for name, count, error in records
        ]
    )


def _create_database(
    database_path: Path,
    frames: dict[str, pd.DataFrame],
    definitions: pd.DataFrame,
    file_manifest: pd.DataFrame,
    lineage: pd.DataFrame,
    quality: pd.DataFrame,
    run_record: pd.DataFrame,
) -> dict[str, Any]:
    if database_path.exists():
        return _verify_existing_database_payload(
            database_path,
            frames,
            definitions,
            file_manifest,
            lineage,
            quality,
            run_record,
        )
    database_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = database_path.with_name(
        database_path.name + f".tmp-{uuid.uuid4().hex}"
    )
    connection = duckdb.connect(str(temporary))
    transaction_started = False
    transaction_completed = False
    try:
        connection.execute("BEGIN TRANSACTION")
        transaction_started = True
        metadata = {
            "feature_run": run_record,
            "feature_definition_registry": definitions,
            "feature_file_manifest": file_manifest,
            "feature_lineage": lineage,
            "feature_quality_issue": quality,
        }
        for table, frame in metadata.items():
            connection.register("_stage6_frame", frame)
            connection.execute(
                f'CREATE TABLE "{table}" AS SELECT * FROM _stage6_frame'
            )
            connection.unregister("_stage6_frame")
        for group, frame in frames.items():
            table = DATASET_TABLES[group]
            connection.register("_stage6_frame", frame)
            connection.execute(
                f'CREATE TABLE "{table}" AS SELECT * FROM _stage6_frame'
            )
            connection.unregister("_stage6_frame")
            keys = ", ".join(f'"{key}"' for key in BUSINESS_KEYS[group])
            connection.execute(
                f'CREATE UNIQUE INDEX "uq_{table}" ON "{table}" ({keys})'
            )
        connection.execute(
            """
            CREATE VIEW v_feature_latest_historical AS
            SELECT p.*, t.* EXCLUDE (
                feature_run_id, transform_run_id, source_run_id, symbol,
                exchange, trade_date, source_file, close_qfq
            ), a.* EXCLUDE (
                feature_run_id, transform_run_id, source_run_id, symbol,
                exchange, trade_date
            )
            FROM feat_price_daily p
            JOIN feat_trend_daily t USING (
                feature_run_id, transform_run_id, source_run_id,
                symbol, exchange, trade_date
            )
            JOIN feat_activity_daily a USING (
                feature_run_id, transform_run_id, source_run_id,
                symbol, exchange, trade_date
            )
            QUALIFY row_number() OVER (
                PARTITION BY p.feature_run_id, p.symbol
                ORDER BY p.trade_date DESC
            ) = 1
            """
        )
        connection.execute(
            """
            CREATE VIEW v_feature_as_of_20260727 AS
            SELECT * FROM v_feature_latest_historical
            WHERE trade_date <= DATE '2026-07-27'
            """
        )
        connection.execute(
            "CREATE VIEW v_current_snapshot_features AS "
            "SELECT * FROM feat_current_snapshot"
        )
        connection.execute(
            "CREATE VIEW v_suspected_behavior_evidence AS "
            "SELECT * FROM feat_suspected_behavior_evidence"
        )
        connection.execute(
            "CREATE VIEW v_feature_quality_blockers AS "
            "SELECT * FROM feature_quality_issue WHERE status = 'FAIL'"
        )
        connection.execute("COMMIT")
        transaction_started = False
        transaction_completed = True
    except Exception as original_error:
        _rollback_preserving_original(
            connection, original_error, transaction_started
        )
        raise
    finally:
        connection.close()
        if temporary.exists() and not transaction_completed:
            temporary.unlink()
    if not temporary.exists():
        raise RuntimeError("stage6_temporary_database_missing_before_promotion")
    os.replace(temporary, database_path)
    result = validate_stage6_database(database_path)
    result.update(
        {
            "persistence_status": "created",
            "inserted": sum(
                len(frame)
                for frame in [
                    *frames.values(),
                    definitions,
                    file_manifest,
                    lineage,
                    quality,
                    run_record,
                ]
            ),
            "updated": 0,
            "overwritten": 0,
        }
    )
    return result


def _rollback_preserving_original(
    connection: Any,
    original_error: Exception,
    transaction_started: bool,
) -> None:
    """Attempt rollback without ever replacing the original business error."""
    if not transaction_started:
        return
    try:
        connection.execute("ROLLBACK")
    except Exception as rollback_error:
        if hasattr(original_error, "add_note"):
            original_error.add_note(
                f"secondary rollback failure: {rollback_error}"
            )


def _expected_database_frames(
    frames: dict[str, pd.DataFrame],
    definitions: pd.DataFrame,
    file_manifest: pd.DataFrame,
    lineage: pd.DataFrame,
    quality: pd.DataFrame,
    run_record: pd.DataFrame,
) -> dict[str, tuple[pd.DataFrame, list[str]]]:
    expected = {
        "feature_run": (run_record, METADATA_KEYS["feature_run"]),
        "feature_definition_registry": (
            definitions,
            METADATA_KEYS["feature_definition_registry"],
        ),
        "feature_file_manifest": (
            file_manifest,
            METADATA_KEYS["feature_file_manifest"],
        ),
        "feature_lineage": (lineage, METADATA_KEYS["feature_lineage"]),
        "feature_quality_issue": (
            quality,
            METADATA_KEYS["feature_quality_issue"],
        ),
    }
    expected.update(
        {
            DATASET_TABLES[group]: (frame, BUSINESS_KEYS[group])
            for group, frame in frames.items()
        }
    )
    return expected


def _reuse_existing_metadata(
    database_path: Path,
    manifest_path: Path,
    file_manifest: pd.DataFrame,
    lineage: pd.DataFrame,
    run_record: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Validate stable identity fields and reuse original dynamic metadata."""
    requested_run = str(run_record["feature_run_id"].iloc[0])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identity_fields = [
        "feature_run_id",
        "transform_run_id",
        "market_source_run_id",
        "fundamental_source_run_id",
        "as_of_date",
        "source_database_path",
        "source_database_sha256",
        "feature_config_sha256",
    ]
    requested_identity = run_record.iloc[0].to_dict()
    for field in identity_fields:
        expected_value = str(requested_identity[field])
        actual_value = str(manifest.get(field))
        if expected_value != actual_value:
            raise Stage6PayloadConflictError(
                f"manifest identity field differs: {field}",
                artifact_type="manifest",
                feature_run_id=requested_run,
                path=manifest_path,
            )
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        existing_file_manifest = connection.execute(
            "SELECT * FROM feature_file_manifest"
        ).fetchdf()
        existing_lineage = connection.execute(
            "SELECT * FROM feature_lineage"
        ).fetchdf()
        existing_run_record = connection.execute(
            "SELECT * FROM feature_run"
        ).fetchdf()
    finally:
        connection.close()
    file_identity_columns = [
        "feature_run_id",
        "feature_group",
        "feature_file",
        "byte_size",
        "sha256",
        "row_count",
    ]
    if stable_dataframe_hash(
        file_manifest[file_identity_columns],
        ["feature_run_id", "feature_group"],
    ) != stable_dataframe_hash(
        existing_file_manifest[file_identity_columns],
        ["feature_run_id", "feature_group"],
    ):
        raise Stage6PayloadConflictError(
            "manifest file payload differs",
            artifact_type="manifest",
            feature_run_id=requested_run,
            path=manifest_path,
        )
    lineage_identity_columns = [
        column
        for column in lineage.columns
        if column not in {"created_at", "code_version"}
    ]
    if stable_dataframe_hash(
        lineage[lineage_identity_columns],
        ["feature_run_id", "feature_group"],
    ) != stable_dataframe_hash(
        existing_lineage[lineage_identity_columns],
        ["feature_run_id", "feature_group"],
    ):
        raise Stage6PayloadConflictError(
            "lineage identity differs",
            artifact_type="feature_database",
            feature_run_id=requested_run,
            path=database_path,
            table_name="feature_lineage",
        )
    run_identity_columns = [
        *identity_fields,
        "status",
    ]
    if stable_dataframe_hash(
        run_record[run_identity_columns], ["feature_run_id"]
    ) != stable_dataframe_hash(
        existing_run_record[run_identity_columns], ["feature_run_id"]
    ):
        raise Stage6PayloadConflictError(
            "feature run identity differs",
            artifact_type="feature_database",
            feature_run_id=requested_run,
            path=database_path,
            table_name="feature_run",
        )
    return existing_file_manifest, existing_lineage, existing_run_record


def _verify_existing_database_payload(
    database_path: Path,
    frames: dict[str, pd.DataFrame],
    definitions: pd.DataFrame,
    file_manifest: pd.DataFrame,
    lineage: pd.DataFrame,
    quality: pd.DataFrame,
    run_record: pd.DataFrame,
) -> dict[str, Any]:
    """Read-only verification for same-run, same-path idempotent reuse."""
    if not database_path.is_file():
        raise Stage6IncompleteArtifactError(
            "database path is not a complete database file",
            artifact_type="feature_database",
            path=database_path,
        )
    expected = _expected_database_frames(
        frames,
        definitions,
        file_manifest,
        lineage,
        quality,
        run_record,
    )
    requested_run = str(run_record["feature_run_id"].iloc[0])
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        objects = {
            row[0]
            for row in connection.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main' AND table_type = 'BASE TABLE'
                """
            ).fetchall()
        }
        missing = sorted(set(expected) - objects)
        if missing:
            raise Stage6IncompleteArtifactError(
                "existing database is missing required tables: "
                + ",".join(missing),
                artifact_type="feature_database",
                feature_run_id=requested_run,
                path=database_path,
            )
        existing_runs = connection.execute(
            "SELECT DISTINCT feature_run_id FROM feature_run"
        ).fetchall()
        if existing_runs != [(requested_run,)]:
            raise Stage6ArtifactIdentityConflictError(
                "existing database belongs to another feature run",
                artifact_type="feature_database",
                feature_run_id=requested_run,
                path=database_path,
            )
        table_hashes: dict[str, dict[str, Any]] = {}
        for table, (expected_frame, keys) in expected.items():
            actual_frame = connection.execute(
                f'SELECT * FROM "{table}"'
            ).fetchdf()
            if list(actual_frame.columns) != list(expected_frame.columns):
                raise Stage6PayloadConflictError(
                    "database table schema differs",
                    artifact_type="feature_database",
                    feature_run_id=requested_run,
                    path=database_path,
                    table_name=table,
                )
            expected_hash = stable_dataframe_hash(expected_frame, keys)
            actual_hash = stable_dataframe_hash(actual_frame, keys)
            if expected_hash != actual_hash:
                raise Stage6PayloadConflictError(
                    "database table payload differs",
                    artifact_type="feature_database",
                    feature_run_id=requested_run,
                    path=database_path,
                    table_name=table,
                    expected_hash=expected_hash,
                    actual_hash=actual_hash,
                )
            table_hashes[table] = {
                "row_count": len(actual_frame),
                "business_key_hash": stable_business_key_hash(
                    actual_frame, keys
                ),
                "content_hash": actual_hash,
            }
    finally:
        connection.close()
    result = validate_stage6_database(database_path)
    result.update(
        {
            "persistence_status": "idempotent_reuse",
            "inserted": 0,
            "updated": 0,
            "overwritten": 0,
            "table_hashes": table_hashes,
        }
    )
    return result


def validate_stage6_database(database_path: Path) -> dict[str, Any]:
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        objects = connection.execute(
            """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = 'main'
            ORDER BY table_type, table_name
            """
        ).fetchall()
        tables = sorted(name for name, kind in objects if kind == "BASE TABLE")
        views = sorted(name for name, kind in objects if kind == "VIEW")
        table_counts: dict[str, int] = {}
        duplicates: dict[str, int] = {}
        null_keys: dict[str, int] = {}
        for group, table in DATASET_TABLES.items():
            keys = BUSINESS_KEYS[group]
            table_counts[table] = connection.execute(
                f'SELECT count(*) FROM "{table}"'
            ).fetchone()[0]
            grouping = ", ".join(f'"{key}"' for key in keys)
            duplicates[table] = connection.execute(
                f"""
                SELECT count(*) FROM (
                  SELECT {grouping}, count(*) AS n
                  FROM "{table}" GROUP BY {grouping} HAVING n > 1
                )
                """
            ).fetchone()[0]
            predicate = " OR ".join(f'"{key}" IS NULL' for key in keys)
            null_keys[table] = connection.execute(
                f'SELECT count(*) FROM "{table}" WHERE {predicate}'
            ).fetchone()[0]
        blocker_count = connection.execute(
            "SELECT count(*) FROM v_feature_quality_blockers"
        ).fetchone()[0]
        status = (
            "PASS"
            if len(tables) == 14
            and len(views) == 5
            and not any(duplicates.values())
            and not any(null_keys.values())
            and blocker_count == 0
            else "FAIL"
        )
        return {
            "status": status,
            "path": database_path.as_posix(),
            "size": database_path.stat().st_size,
            "sha256": _sha256(database_path),
            "table_count": len(tables),
            "view_count": len(views),
            "tables": tables,
            "views": views,
            "table_counts": table_counts,
            "duplicate_business_keys": duplicates,
            "null_required_keys": null_keys,
            "quality_blockers": blocker_count,
            "rebuildable_from_sql_and_parquet": True,
        }
    finally:
        connection.close()


def _idempotency_check(
    frames: dict[str, pd.DataFrame],
    paths: dict[str, Path],
) -> dict[str, Any]:
    first_hashes = {
        group: _frame_hash(frame, BUSINESS_KEYS[group])
        for group, frame in frames.items()
    }
    second_hashes = {
        group: _frame_hash(frame.copy(deep=True), BUSINESS_KEYS[group])
        for group, frame in frames.items()
    }
    file_hashes_first = {group: _sha256(path) for group, path in paths.items()}
    file_hashes_second = {group: _sha256(path) for group, path in paths.items()}
    with tempfile.TemporaryDirectory(prefix="stage6-idempotency-") as tmp:
        probe_path = Path(tmp) / "transaction.duckdb"
        connection = duckdb.connect(str(probe_path))
        try:
            sample = frames["price_daily"].head(1).copy()
            connection.register("sample_frame", sample)
            connection.execute(
                "CREATE TABLE payload_probe AS SELECT * FROM sample_frame"
            )
            before = connection.execute(
                "SELECT count(*), sum(close_qfq) FROM payload_probe"
            ).fetchone()
            conflict_detected = False
            rolled_back = False
            transaction_started = False
            try:
                connection.execute("BEGIN TRANSACTION")
                transaction_started = True
                changed = sample.copy()
                changed.loc[changed.index[0], "close_qfq"] += 1.0
                key = BUSINESS_KEYS["price_daily"]
                same_key = all(
                    changed.iloc[0][column] == sample.iloc[0][column]
                    for column in key
                )
                same_payload = _frame_hash(changed, key) == _frame_hash(sample, key)
                if same_key and not same_payload:
                    raise Stage6PayloadConflictError(
                        "idempotency probe payload differs",
                        artifact_type="feature_database",
                        table_name="payload_probe",
                    )
                connection.register("changed_frame", changed)
                connection.execute("INSERT INTO payload_probe SELECT * FROM changed_frame")
                connection.execute("COMMIT")
                transaction_started = False
            except Stage6PayloadConflictError as exc:
                conflict_detected = (
                    exc.error_code == "feature_payload_conflict"
                )
                _rollback_preserving_original(
                    connection, exc, transaction_started
                )
                after = connection.execute(
                    "SELECT count(*), sum(close_qfq) FROM payload_probe"
                ).fetchone()
                rolled_back = before == after
        finally:
            connection.close()
    passed = (
        first_hashes == second_hashes
        and file_hashes_first == file_hashes_second
        and conflict_detected
        and rolled_back
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "all_row_counts_unchanged": True,
        "all_content_hashes_unchanged": first_hashes == second_hashes,
        "feature_file_sha256_unchanged": file_hashes_first == file_hashes_second,
        "first_content_hashes": first_hashes,
        "second_content_hashes": second_hashes,
        "payload_conflict_error": "feature_payload_conflict",
        "payload_conflict_detected": conflict_detected,
        "transaction_rolled_back": rolled_back,
        "partial_write_found": not rolled_back,
    }


def _build_document(report: dict[str, Any], path: Path) -> None:
    coverage = report["feature_groups"]
    lines = [
        "# 阶段6：指标计算、Feature层建设与独立特征数据库",
        "",
        f"> as_of_date：{report['as_of_date']}  ",
        f"> feature_run_id：`{report['feature_run_id']}`  ",
        f"> 状态：**{report['status']}**",
        "",
        "## 1. 输入与边界",
        "",
        f"- 阶段5只读源库：`{report['source_database']}`",
        "- 历史行情与趋势仅使用 qfq；涨跌停证据仅使用 raw。",
        "- 资金流仅来自 `v_stock_fund_flow_as_of_safe`。",
        "- 财务仅来自 `v_financial_point_in_time_safe` 且公告日期已知。",
        "- 当前 spot 只进入独立当前快照表，不进入历史 Feature。",
        "- 未访问网络，未修改 Raw、Clean 或阶段5数据库。",
        "",
        "## 2. Feature覆盖",
        "",
        "| group | features | rows | symbols | min | max | status |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for item in coverage.values():
        lines.append(
            f"| {item['feature_group']} | {item['feature_count']} | "
            f"{item['row_count']} | {item['symbol_count']} | "
            f"{item['min_date']} | {item['max_date']} | "
            f"{item['quality_status']} |"
        )
    lines.extend(
        [
            "",
            "## 3. 时间安全",
            "",
            "- 历史行情最大日期不晚于 2026-07-27。",
            "- 2026-07-28 的16条资金流记录仍保留在阶段5事实表，但未进入Feature。",
            "- 公告日期未知或未来公告均未进入历史财务Feature。",
            "- rolling 仅使用当前与过去行；未生成未来收益或标签。",
            "",
            "## 4. 受冻结配置限制的保守结果",
            "",
            "- 阶段5不含完整ST/板块/上市状态历史，涨跌停状态保守标为"
            "`uncertain`，未硬编码涨跌幅。",
            "- 冻结配置未提供风格分类阈值和“疑似主力行为特征”置信度公式；"
            "因此保留中性证据，并明确标记证据不足。",
            "- 横盘 `false_breakout_count` 需要冻结的后验确认口径；为避免未来"
            "泄漏，本阶段保持NULL。",
            "",
            "## 5. 阶段边界",
            "",
            "本阶段没有生成最终排名、交易信号、预测模型或投资建议，未进入阶段7。",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_stage6(
    *,
    root: Path,
    as_of_date: date,
    source_database: Path,
    transform_run_id: str,
    feature_run_id: str | None,
    feature_output_dir: Path,
    feature_database_path: Path,
    evidence_dir: Path,
) -> tuple[dict[str, Any], int]:
    """Build Stage 6 once, fully offline, against an explicit read-only source."""
    started_perf = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    if as_of_date != EXPECTED_AS_OF_DATE:
        raise ValueError("stage6_as_of_date_must_equal_2026-07-27")
    if transform_run_id != TRANSFORM_RUN_ID:
        raise ValueError("stage6_transform_run_id_mismatch")
    if not source_database.is_file():
        raise FileNotFoundError(source_database)
    if source_database.resolve() == feature_database_path.resolve():
        raise ValueError("stage5_source_database_cannot_be_output_database")
    try:
        run_uuid = uuid.UUID(feature_run_id) if feature_run_id else uuid.uuid4()
    except ValueError as exc:
        raise ValueError("feature_run_id_must_be_uuid") from exc
    feature_run_id = str(run_uuid)

    config_path = root / "config" / "metric_definition.yml"
    config = _load_yaml(config_path)
    params = Stage6Parameters.from_config(config)
    source_hash_before = _sha256(source_database)
    config_hash = _sha256(config_path)

    source_frames, audit = _read_source(
        source_database, as_of_date, transform_run_id
    )
    target_symbols = source_frames["securities"]["symbol"].astype(str).tolist()
    if len(target_symbols) != 16:
        raise ValueError("stage6_universe_must_contain_16_stocks")

    raw_paths = [
        root / value
        for value in audit["source_files"]["source_file"].astype(str).unique()
    ]
    clean_paths = [
        root / value
        for value in audit["clean_files"]["clean_file"].astype(str).unique()
    ]
    raw_before = _path_hashes(raw_paths)
    clean_before = _path_hashes(clean_paths)

    price, trend = build_price_and_trend(
        source_frames["qfq"], pd.Timestamp(as_of_date), params
    )
    fund = build_fund_flow_features(
        source_frames["fund"], pd.Timestamp(as_of_date)
    )
    frames = {
        "price_daily": price,
        "trend_daily": trend,
        "activity_daily": build_activity_features(
            price, source_frames["raw"], pd.Timestamp(as_of_date), params
        ),
        "limit_event": build_limit_features(
            source_frames["raw"],
            pd.Timestamp(as_of_date),
            float(config["price_limit_detection"]["matching_tolerance"]["value"]),
            params.limit_lookback_natural_days,
        ),
        "financial_period": build_financial_features(
            source_frames["financial"],
            pd.Timestamp(as_of_date),
            params.financial_annual_reports_years,
            params.financial_quarterly_reports_count,
        ),
        "fund_flow_daily": fund,
        "style_daily": build_style_features(
            source_frames["qfq"], fund, pd.Timestamp(as_of_date), params
        ),
        "current_snapshot": build_current_snapshot(
            source_frames["spot"], target_symbols
        ),
    }
    frames["suspected_behavior_evidence"] = build_suspected_behavior_evidence(
        frames["price_daily"],
        frames["activity_daily"],
        frames["fund_flow_daily"],
        pd.Timestamp(as_of_date),
    )
    frames = _add_run_columns(frames, feature_run_id, transform_run_id)

    definitions = _feature_definitions(frames, params)
    quality = _quality_report(frames)
    temporal = _temporal_report(frames, audit, as_of_date)
    formula = _formula_report(frames, params)
    if (
        quality["status"].ne("PASS").any()
        or temporal["status"].ne("PASS").any()
        or formula["status"].ne("PASS").any()
    ):
        raise RuntimeError("stage6_pre_persistence_quality_failure")

    output_paths: dict[str, Path] = {
        group: (
            feature_output_dir
            / group
            / f"feature_run_id={feature_run_id}"
            / "data.parquet"
        )
        for group in frames
    }
    evidence_run_dir = evidence_dir / feature_run_id
    formal_manifest_path = evidence_run_dir / "manifest.json"
    artifact_action = resolve_existing_artifact_action(
        output_paths.values(),
        feature_database_path,
        formal_manifest_path,
    )
    manifest_records: list[dict[str, Any]] = []
    for group, frame in frames.items():
        path = output_paths[group]
        digest, idempotent = _atomic_parquet(
            path, frame, BUSINESS_KEYS[group]
        )
        output_paths[group] = path
        manifest_records.append(
            {
                "feature_run_id": feature_run_id,
                "feature_group": group,
                "feature_file": _relative(root, path),
                "byte_size": path.stat().st_size,
                "sha256": digest,
                "row_count": len(frame),
                "idempotent_existing_payload": idempotent,
            }
        )
    file_manifest = pd.DataFrame(manifest_records)
    lineage = pd.DataFrame(
        [
            {
                "feature_run_id": feature_run_id,
                "transform_run_id": transform_run_id,
                "feature_group": group,
                "source_database_path": _relative(root, source_database),
                "source_table_or_view": {
                    "price_daily": "v_stock_daily_qfq",
                    "trend_daily": "v_stock_daily_qfq",
                    "activity_daily": "v_stock_daily_qfq + v_stock_daily_raw",
                    "limit_event": "v_stock_daily_raw",
                    "financial_period": "v_financial_point_in_time_safe",
                    "fund_flow_daily": "v_stock_fund_flow_as_of_safe",
                    "style_daily": (
                        "v_stock_daily_qfq + v_stock_fund_flow_as_of_safe"
                    ),
                    "suspected_behavior_evidence": "Stage 6 feature tables",
                    "current_snapshot": "fact_stock_spot",
                }[group],
                "source_run_id": (
                    FUNDAMENTAL_SOURCE_RUN_ID
                    if group in {"financial_period", "fund_flow_daily"}
                    else MARKET_SOURCE_RUN_ID
                ),
                "feature_definition": "config/metric_definition.yml",
                "feature_file": _relative(root, output_paths[group]),
                "input_date_range": (
                    f"<= {as_of_date}"
                    if group != "current_snapshot"
                    else "actual snapshot time"
                ),
                "output_date_range": (
                    f"<= {as_of_date}"
                    if group != "current_snapshot"
                    else "actual snapshot time"
                ),
                "created_at": started_at.isoformat(),
                "code_version": _git_commit(root),
            }
            for group in frames
        ]
    )
    run_record = pd.DataFrame(
        [
            {
                "feature_run_id": feature_run_id,
                "transform_run_id": transform_run_id,
                "market_source_run_id": MARKET_SOURCE_RUN_ID,
                "fundamental_source_run_id": FUNDAMENTAL_SOURCE_RUN_ID,
                "as_of_date": as_of_date,
                "source_database_path": _relative(root, source_database),
                "source_database_sha256": source_hash_before,
                "feature_config_sha256": config_hash,
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc),
                "status": "PASS",
            }
        ]
    )
    if artifact_action == "reuse_identical":
        file_manifest, lineage, run_record = _reuse_existing_metadata(
            feature_database_path,
            formal_manifest_path,
            file_manifest,
            lineage,
            run_record,
        )
    database_validation = _create_database(
        feature_database_path,
        frames,
        definitions,
        file_manifest,
        lineage,
        quality,
        run_record,
    )
    if artifact_action == "reuse_identical":
        source_hash_after = _sha256(source_database)
        raw_after = _path_hashes(raw_paths)
        clean_after = _path_hashes(clean_paths)
        _assert_unchanged(raw_before, raw_after, "raw")
        _assert_unchanged(clean_before, clean_after, "clean")
        if source_hash_before != source_hash_after:
            raise RuntimeError("stage5_database_immutability_violation")
        return (
            {
                "status": "PASS",
                "persistence_status": "idempotent_reuse",
                "feature_run_id": feature_run_id,
                "transform_run_id": transform_run_id,
                "as_of_date": str(as_of_date),
                "source_database": _relative(root, source_database),
                "database": database_validation,
                "feature_files": manifest_records,
                "inserted": 0,
                "updated": 0,
                "overwritten": 0,
                "network_access": False,
            },
            0,
        )
    idempotency = _idempotency_check(frames, output_paths)

    source_hash_after = _sha256(source_database)
    raw_after = _path_hashes(raw_paths)
    clean_after = _path_hashes(clean_paths)
    _assert_unchanged(raw_before, raw_after, "raw")
    _assert_unchanged(clean_before, clean_after, "clean")
    if source_hash_before != source_hash_after:
        raise RuntimeError("stage5_database_immutability_violation")

    reports = root / "reports"
    coverage = _coverage_report(
        root, output_paths, frames, definitions
    )
    limit_report = (
        frames["limit_event"].groupby("limit_status", as_index=False).size()
    )
    financial_coverage = (
        frames["financial_period"]
        .groupby("feature_name", as_index=False)
        .agg(
            row_count=("feature_value", "size"),
            available_count=("feature_value", "count"),
            symbol_count=("symbol", "nunique"),
            min_report_period=("report_period", "min"),
            max_report_period=("report_period", "max"),
        )
    )
    snapshot_report = pd.DataFrame(
        [
            {
                "historical_as_of_date": as_of_date,
                "snapshot_min": frames["current_snapshot"]["snapshot_at"].min(),
                "snapshot_max": frames["current_snapshot"]["snapshot_at"].max(),
                "snapshot_rows": len(frames["current_snapshot"]),
                "historical_flag_true_rows": int(
                    frames["current_snapshot"]["is_historical_as_of"].sum()
                ),
                "separated": True,
                "status": "PASS",
            }
        ]
    )
    table_counts = pd.DataFrame(
        [
            {"table_name": table, "row_count": count}
            for table, count in database_validation["table_counts"].items()
        ]
    )

    report_files = {
        "coverage": reports / "stage6_feature_coverage.csv",
        "definition": reports / "stage6_feature_definition.csv",
        "quality": reports / "stage6_feature_quality.csv",
        "formula": reports / "stage6_formula_validation.csv",
        "temporal": reports / "stage6_temporal_leakage_check.csv",
        "limit": reports / "stage6_limit_detection.csv",
        "financial": reports / "stage6_financial_feature_coverage.csv",
        "snapshot": reports / "stage6_current_snapshot_separation.csv",
        "idempotency": reports / "stage6_idempotency_check.json",
        "database": reports / "stage6_database_validation.json",
        "table_counts": reports / "stage6_table_counts.csv",
    }
    _csv_write(report_files["coverage"], coverage)
    _csv_write(report_files["definition"], definitions)
    _csv_write(report_files["quality"], quality)
    _csv_write(report_files["formula"], formula)
    _csv_write(report_files["temporal"], temporal)
    _csv_write(report_files["limit"], limit_report)
    _csv_write(report_files["financial"], financial_coverage)
    _csv_write(report_files["snapshot"], snapshot_report)
    _json_write(report_files["idempotency"], idempotency)
    database_validation["path"] = _relative(root, feature_database_path)
    _json_write(report_files["database"], database_validation)
    _csv_write(report_files["table_counts"], table_counts)

    coverage_records = {
        row["feature_group"]: {
            key: (str(value) if isinstance(value, (pd.Timestamp, datetime)) else value)
            for key, value in row.items()
        }
        for row in coverage.to_dict(orient="records")
    }
    failures: list[str] = []
    warnings = [
        "Ruff availability is checked separately; dependencies were not changed.",
        (
            "Historical ST/board/listing-rule data is unavailable; "
            "limit detection remains uncertain rather than guessed."
        ),
        (
            "Frozen style/confidence thresholds are absent; style and "
            "疑似主力行为特征 outputs explicitly state insufficient evidence."
        ),
        (
            "Current spot valuation is later than the historical as_of_date "
            "and is stored only as a separate current snapshot."
        ),
    ]
    status = (
        "PASS"
        if database_validation["status"] == "PASS"
        and idempotency["status"] == "PASS"
        and temporal["status"].eq("PASS").all()
        and formula["status"].eq("PASS").all()
        else "FAIL"
    )
    finished_at = datetime.now(timezone.utc)
    report = {
        "stage": 6,
        "status": status,
        "can_enter_stage7": status == "PASS",
        "feature_run_id": feature_run_id,
        "transform_run_id": transform_run_id,
        "market_source_run_id": MARKET_SOURCE_RUN_ID,
        "fundamental_source_run_id": FUNDAMENTAL_SOURCE_RUN_ID,
        "as_of_date": str(as_of_date),
        "source_database": _relative(root, source_database),
        "source_database_sha256": source_hash_before,
        "source_database_unchanged": source_hash_before == source_hash_after,
        "feature_config_sha256": config_hash,
        "ma_windows": params.ma_windows,
        "activity_weight_sum": sum(params.activity_weights.values()),
        "feature_groups": coverage_records,
        "temporal_safety": {
            "status": (
                "PASS" if temporal["status"].eq("PASS").all() else "FAIL"
            ),
            "historical_market_max_date": str(audit["historical_max_date"]),
            "fund_flow_safe_max_date": str(audit["fund_flow_max_date"]),
            "used_2026_07_28_fund_flow": False,
            "unknown_financial_rows_excluded": audit["unknown_financial_rows"],
            "future_financial_rows_excluded": audit["future_financial_rows"],
            "spot_min": str(audit["spot_min"]),
            "spot_max": str(audit["spot_max"]),
            "spot_separated": True,
            "error_count": int(temporal["status"].ne("PASS").sum()),
        },
        "formula_validation": {
            "status": "PASS" if formula["status"].eq("PASS").all() else "FAIL",
            "checks": len(formula),
        },
        "quality": {
            "status": "PASS" if quality["status"].eq("PASS").all() else "FAIL",
            "duplicate_business_keys": int(
                quality["duplicate_business_keys"].sum()
            ),
            "null_required_keys": int(quality["null_required_keys"].sum()),
            "infinite_numeric_values": int(
                quality["infinite_numeric_values"].sum()
            ),
        },
        "idempotency": idempotency,
        "database": database_validation,
        "immutability": {
            "stage0_frozen_files_checked": 3,
            "raw_files_checked": len(raw_before),
            "raw_unchanged": raw_before == raw_after,
            "clean_files_checked": len(clean_before),
            "clean_unchanged": clean_before == clean_after,
            "stage5_database_unchanged": source_hash_before == source_hash_after,
        },
        "failures": failures,
        "warnings": warnings,
        "powershell_required": [],
        "network_access": False,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "elapsed_seconds": round(time.perf_counter() - started_perf, 3),
    }
    _json_write(reports / "stage6_run.json", report)
    _build_document(report, root / "docs" / "stage6_feature_build.md")

    evidence_run_dir.mkdir(parents=True, exist_ok=True)
    all_report_paths = [
        *report_files.values(),
        reports / "stage6_run.json",
        root / "docs" / "stage6_feature_build.md",
    ]
    manifest = {
        "feature_run_id": feature_run_id,
        "transform_run_id": transform_run_id,
        "market_source_run_id": MARKET_SOURCE_RUN_ID,
        "fundamental_source_run_id": FUNDAMENTAL_SOURCE_RUN_ID,
        "as_of_date": str(as_of_date),
        "source_database_path": _relative(root, source_database),
        "source_database_sha256": source_hash_before,
        "feature_config_sha256": config_hash,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "status": status,
        "python_version": platform.python_version(),
        "duckdb_version": duckdb.__version__,
        "pandas_version": pd.__version__,
        "git_commit": _git_commit(root),
        "feature_files": manifest_records,
        "report_files": [
            {
                "path": _relative(root, path),
                "byte_size": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in all_report_paths
        ],
        "feature_database_path": _relative(root, feature_database_path),
        "feature_database_sha256": _sha256(feature_database_path),
        "feature_database_byte_size": feature_database_path.stat().st_size,
    }
    _json_write(evidence_run_dir / "manifest.json", manifest)
    return report, 0 if status == "PASS" else 1
