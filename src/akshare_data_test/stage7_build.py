"""Offline Stage 7 feature and activity build orchestration."""
from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .config import load_metrics, load_universe
from .features.activity_score import compute_activity_scores
from .features.stock_daily_features import (
    Stage7Parameters,
    compute_stock_daily_features,
)
from .quality.feature_checks import run_stage7_quality_checks
from .storage.feature_repository import (
    read_stage7_results,
    read_qfq_daily,
    upsert_quality_results,
    upsert_stage7_results,
)

LOGGER = logging.getLogger(__name__)


def _load_stage7_parameters(root: Path) -> Stage7Parameters:
    stage7_path = root / "config" / "stage7.yml"
    stage7_raw = yaml.safe_load(stage7_path.read_text(encoding="utf-8"))
    return Stage7Parameters.from_config(load_metrics().raw, stage7_raw)


def _display_path(root: Path, path: Path) -> str:
    """Return a portable project-relative path when possible."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _select_target_universe(
    daily: pd.DataFrame, target_symbols: list[str]
) -> tuple[pd.DataFrame, list[str]]:
    """Restrict the cross-sectional scoring universe to configured stocks."""
    symbols = daily["symbol"].astype("string").str.zfill(6)
    extra_symbols = sorted(set(symbols.dropna()).difference(target_symbols))
    selected = daily.loc[symbols.isin(target_symbols)].copy()
    selected["symbol"] = symbols.loc[selected.index]
    if selected.empty:
        raise ValueError("Stage 7 source contains no configured target stocks")
    return selected.reset_index(drop=True), extra_symbols


def _post_write_check(
    name: str, passed: bool, observed: object, expected: object
) -> dict[str, str]:
    return {
        "check_name": name,
        "status": "PASS" if passed else "FAIL",
        "severity": "ERROR",
        "observed_value": str(observed),
        "expected_value": str(expected),
        "details": "formal DuckDB post-write verification",
    }


def _write_reports(
    root: Path,
    report: dict[str, Any],
    features: pd.DataFrame,
    activity: pd.DataFrame,
    quality: pd.DataFrame,
) -> None:
    reports = root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    feature_sample = (
        features.sort_values(["symbol", "trade_date"], ascending=[True, False])
        .groupby("symbol", group_keys=False)
        .head(3)
    )
    feature_sample.to_csv(
        reports / "stage7_feature_sample.csv", index=False, encoding="utf-8-sig"
    )
    activity.sort_values("activity_score", ascending=False).to_csv(
        reports / "stage7_activity_ranking.csv",
        index=False,
        encoding="utf-8-sig",
    )
    quality.to_csv(
        reports / "stage7_feature_quality.csv", index=False, encoding="utf-8-sig"
    )
    (reports / "stage7_run.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )

    ranking_lines = []
    for row in report["activity_ranking"]:
        score = "NULL" if row["activity_score"] is None else f"{row['activity_score']:.6f}"
        ranking_lines.append(
            f"| {row['symbol']} | {score} | {row['observation_count']} | "
            f"{row['score_status']} |"
        )
    quality_lines = [
        f"| {row.check_name} | {row.status} | {row.severity} | {row.details or '-'} |"
        for row in quality.itertuples(index=False)
    ]
    missing_lines = [
        f"| {column} | {rate:.6f} |"
        for column, rate in report["feature_missing_rate"].items()
    ]
    document = f"""# 阶段 7 每日特征与活跃度评分验证

- 执行时间（UTC）：{report["calculated_at"]}
- run_id：`{report["run_id"]}`
- 数据来源表：`{report["source_table"]}`
- 源数据库：`{report["source_database"]}`
- 结果数据库：`{report["output_database"]}`
- as_of_date：{report["as_of_date"]}
- 复权口径：`qfq`
- 活跃度窗口：最近 {report["lookback_days"]} 个有效交易日
- 数据日期范围：{report["date_range"]["min"]} 至 {report["date_range"]["max"]}
- 股票覆盖：{report["symbol_count"]}/{report["target_symbol_count"]}
- 缺失股票：{", ".join(report["missing_symbols"]) or "无"}
- 输入/每日特征/活跃度行数：{report["input_rows"]}/{report["feature_rows"]}/{report["activity_profiles"]}
- 评分版本：`{report["score_version"]}`

## 评分口径

`activity_score = 0.25 × amount_percentile + 0.20 × turnover_percentile
+ 0.20 × volatility_percentile + 0.15 × volume_spike_percentile
+ 0.10 × large_move_percentile + 0.10 × event_frequency_percentile`。

放量和大幅波动频率的分母分别为最近窗口内对应布尔指标非空的有效交易日；
跳空频率的分母为 `gap_return` 非空的有效交易日。当前完整样本中各股票三个
频率分母均为 120。

横截面分位数仅在 `config/universe.yml` 配置的 16 只目标股票之间计算；
构建会排除额外证券，并由正式数据库质量检查验证目标代码集合。

## 每日特征缺失率

| 字段 | 缺失率 |
|---|---:|
{chr(10).join(missing_lines)}

## 活跃度排名

| 股票 | activity_score | observation_count | score_status |
|---|---:|---:|---|
{chr(10).join(ranking_lines)}

## 数据质量

| 检查 | 状态 | 严重级别 | 说明 |
|---|---|---|---|
{chr(10).join(quality_lines)}

通过检查：{report["quality_checks_passed"]}/{report["quality_checks_total"]}；
失败检查：{report["quality_checks_failed"]}；警告：{report["quality_warnings"]}。

## 事件代理指标说明

`event_frequency_percentile` 使用跳空频率 `gap_frequency` 的横截面分位数，
`event_component_source='gap_proxy'`。它不是正式涨停或跌停统计，也不是市场操纵
或任何“主力行为”的证据。下一阶段完成基于不复权行情和证券状态历史的真实涨跌停
事件表后，必须升级评分版本。

## 已知限制

- 最近 120 个有效交易日不足时使用实际交易日并保留 `observation_count`。
- 少于配置的最小观察数时标记 `insufficient_observations`，不将缺失分项填为 0。
- 本阶段仅使用前复权日线，不抓取网络数据，不实施正式涨跌停、横盘风格或基本面分析。
"""
    (reports / "stage7_feature_validation.md").write_text(
        document, encoding="utf-8"
    )


def build_stage7(
    *,
    root: Path,
    as_of_date: pd.Timestamp,
    source_database: Path,
    output_database: Path,
    adjust_type: str = "qfq",
    lookback_days: int | None = None,
    run_id: str | None = None,
) -> tuple[dict[str, Any], int]:
    """Build Stage 7 outputs fully offline from the existing Clean database."""
    started = time.perf_counter()
    effective_run_id = run_id or str(uuid.uuid4())
    calculated_at = pd.Timestamp.now(tz="UTC")
    parameters = _load_stage7_parameters(root)
    if adjust_type != "qfq":
        raise ValueError("Stage 7 supports only --adjust qfq")
    effective_lookback = (
        parameters.activity_lookback_days
        if lookback_days is None
        else lookback_days
    )
    if effective_lookback <= 0:
        raise ValueError("lookback_days must be positive")

    daily, source_table = read_qfq_daily(
        source_database, as_of_date=pd.Timestamp(as_of_date)
    )
    universe = load_universe()
    target_symbols = [stock.symbol for stock in universe.stocks]
    daily, excluded_symbols = _select_target_universe(daily, target_symbols)
    LOGGER.info(
        "stage7 source_database=%s source_table=%s output_database=%s "
        "input_rows=%d symbols=%d excluded_non_target_symbols=%d "
        "min_date=%s max_date=%s run_id=%s",
        source_database,
        source_table,
        output_database,
        len(daily),
        daily["symbol"].nunique(),
        len(excluded_symbols),
        daily["trade_date"].min(),
        daily["trade_date"].max(),
        effective_run_id,
    )
    features = compute_stock_daily_features(
        daily, parameters, adjust_type=adjust_type
    )
    activity = compute_activity_scores(
        features,
        parameters,
        as_of_date=pd.Timestamp(as_of_date),
        lookback_days=effective_lookback,
    )
    checks = run_stage7_quality_checks(
        daily, features, activity, parameters, target_symbols
    )
    quality = pd.DataFrame(checks)
    quality["run_id"] = effective_run_id
    quality["calculated_at"] = calculated_at
    failures = quality.loc[quality["status"].eq("FAIL")]
    if not failures.empty:
        names = ", ".join(failures["check_name"].tolist())
        raise RuntimeError(f"Stage 7 quality blockers: {names}")

    features["calculated_at"] = calculated_at
    features["run_id"] = effective_run_id
    infinite_values_cleaned = int(
        features.attrs.get("infinite_values_cleaned", 0)
    )
    activity["calculated_at"] = calculated_at
    activity["run_id"] = effective_run_id
    write_started = time.perf_counter()
    upsert_stage7_results(
        output_database,
        root / "sql" / "create_feature_tables.sql",
        features,
        activity,
        quality,
    )
    write_seconds = time.perf_counter() - write_started

    formal_features, formal_activity = read_stage7_results(output_database)
    post_checks = run_stage7_quality_checks(
        daily, formal_features, formal_activity, parameters, target_symbols
    )
    post_checks.extend(
        [
            _post_write_check(
                "database_feature_run_id_current",
                formal_features["run_id"].eq(effective_run_id).all(),
                formal_features["run_id"].nunique(),
                1,
            ),
            _post_write_check(
                "database_activity_run_id_current",
                formal_activity["run_id"].eq(effective_run_id).all(),
                formal_activity["run_id"].nunique(),
                1,
            ),
            _post_write_check(
                "database_activity_row_count",
                len(formal_activity) == len(target_symbols),
                len(formal_activity),
                len(target_symbols),
            ),
        ]
    )
    quality = pd.DataFrame(post_checks)
    quality["run_id"] = effective_run_id
    quality["calculated_at"] = calculated_at
    upsert_quality_results(output_database, quality)
    post_failures = quality.loc[quality["status"].eq("FAIL")]
    if not post_failures.empty:
        names = ", ".join(post_failures["check_name"].tolist())
        raise RuntimeError(f"Stage 7 formal database quality blockers: {names}")
    features = formal_features
    activity = formal_activity

    finite_columns = [
        "return_1d",
        "volume_ratio_20",
        "intraday_range",
        "gap_return",
        "volatility_20",
    ]
    target_present = sorted(set(features["symbol"]).intersection(target_symbols))
    missing_symbols = sorted(set(target_symbols).difference(target_present))
    ranking = activity.sort_values(
        "activity_score", ascending=False, na_position="last"
    )
    ranking_records = []
    for row in ranking[
        ["symbol", "activity_score", "observation_count", "score_status"]
    ].to_dict("records"):
        row["activity_score"] = (
            None if pd.isna(row["activity_score"]) else float(row["activity_score"])
        )
        ranking_records.append(row)
    missing_rates = {
        column: float(features[column].isna().mean())
        for column in [
            "ma_3",
            "ma_5",
            "ma_7",
            "ma_10",
            "ma_13",
            "ma_20",
            "ma_21",
            *finite_columns,
        ]
    }
    report: dict[str, Any] = {
        "status": "PASS",
        "run_id": effective_run_id,
        "calculated_at": calculated_at.isoformat(),
        "as_of_date": str(pd.Timestamp(as_of_date).date()),
        "source_database": _display_path(root, source_database),
        "source_table": source_table,
        "output_database": _display_path(root, output_database),
        "input_rows": int(len(daily)),
        "feature_rows": int(len(features)),
        "activity_profiles": int(len(activity)),
        "symbol_count": len(target_present),
        "target_symbol_count": len(target_symbols),
        "missing_symbols": missing_symbols,
        "excluded_non_target_symbols": excluded_symbols,
        "lookback_days": effective_lookback,
        "date_range": {
            "min": str(features["trade_date"].min().date()),
            "max": str(features["trade_date"].max().date()),
        },
        "feature_missing_rate": missing_rates,
        "missing_metric_values": int(features[finite_columns].isna().sum().sum()),
        "infinite_values_cleaned": infinite_values_cleaned,
        "quality_checks_total": int(len(quality)),
        "quality_checks_passed": int(quality["status"].eq("PASS").sum()),
        "quality_checks_failed": int(quality["status"].eq("FAIL").sum()),
        "quality_warnings": int(quality["status"].eq("WARNING").sum()),
        "score_version": parameters.score_version,
        "event_component_source": parameters.event_component_source,
        "activity_ranking": ranking_records,
        "write_seconds": write_seconds,
        "elapsed_seconds": time.perf_counter() - started,
    }
    _write_reports(root, report, features, activity, quality)
    LOGGER.info(
        "stage7 feature_rows=%d activity_rows=%d missing_metrics=%d "
        "infinite_cleaned=%d write_seconds=%.3f run_id=%s",
        len(features),
        len(activity),
        report["missing_metric_values"],
        report["infinite_values_cleaned"],
        write_seconds,
        effective_run_id,
    )
    return report, 0
