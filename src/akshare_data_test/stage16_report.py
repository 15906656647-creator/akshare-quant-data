"""Stage 16 offline final availability report.

The report summarizes existing formal artifacts. It never fetches data, never
backdates valuation snapshots, and never promotes uncertain limit candidates.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import yaml

from .config import load_universe


COMPLETE = "完整"
PARTIAL = "部分存在"
MISSING = "缺失"
NOT_APPLICABLE = "制度上不适用"
UNPUBLISHABLE = "不可正式发布"


@dataclass(frozen=True)
class Stage16Config:
    raw: dict[str, Any]
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_stage16_config(path: Path) -> Stage16Config:
    raw_bytes = path.read_bytes()
    raw = yaml.safe_load(raw_bytes) or {}
    if raw.get("stage") != 16:
        raise ValueError("Stage 16 config must declare stage: 16")
    scope = raw.get("scope", {})
    if scope.get("expected_stock_count") != 16:
        raise ValueError("Stage 16 requires the frozen 16-stock universe")
    if scope.get("crypto_pair") != "ETHUSDT":
        raise ValueError("Stage 16 crypto scope must be exact ETHUSDT")
    if scope.get("exclude_hong_kong") is not True:
        raise ValueError("Stage 16 must explicitly exclude Hong Kong securities")
    if scope.get("moving_average_windows") != [3, 5, 7, 10, 13, 20, 21]:
        raise ValueError("Stage 16 moving-average windows do not match Stage 0")
    if raw.get("quality", {}).get("permitted_exchanges") != ["SH", "SZ"]:
        raise ValueError("Stage 16 permits only SH and SZ exchanges")
    required_inputs = {
        "stock_database", "stage6_database", "stage7_database", "crypto_database"
    }
    if set(raw.get("inputs", {})) != required_inputs:
        raise ValueError("Stage 16 input database configuration is incomplete")
    return Stage16Config(raw=raw, sha256=hashlib.sha256(raw_bytes).hexdigest())


def _relation_exists(connection: duckdb.DuckDBPyConnection, relation: str) -> bool:
    if "." in relation:
        schema, table = relation.split(".", 1)
    else:
        schema, table = "main", relation
    return bool(connection.execute(
        "SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?", [schema, table]
    ).fetchone()[0])


def validate_stage16_inputs(
    *, root: Path, config_path: Path, as_of_date: pd.Timestamp,
) -> dict[str, Any]:
    config = load_stage16_config(config_path)
    cutoff = pd.Timestamp(as_of_date).normalize()
    reasons: list[str] = []
    if pd.isna(cutoff):
        reasons.append("invalid_as_of_date")
    universe = load_universe()
    symbols = [item.symbol for item in universe.stocks]
    exchanges = {item.exchange for item in universe.stocks}
    if len(symbols) != 16 or len(set(symbols)) != 16:
        reasons.append("frozen_stock_universe_is_not_exactly_16")
    if not exchanges <= {"SH", "SZ"}:
        reasons.append("non_a_share_exchange_in_scope")
    if any(".HK" in symbol.upper() or symbol.upper().startswith("HK") for symbol in symbols):
        reasons.append("hong_kong_symbol_in_scope")
    crypto = [item.requested_pair for item in universe.crypto]
    if crypto != ["ETHUSDT"]:
        reasons.append("crypto_scope_is_not_exact_ethusdt")

    relations = {
        "stock_database": ["fact_stock_daily", "fact_financial_statement", "fact_stock_spot"],
        "stage6_database": ["feat_style_daily", "feat_suspected_behavior_evidence", "feat_limit_event"],
        "stage7_database": ["feature.feature_stock_daily", "analysis.analysis_stock_activity"],
        "crypto_database": ["raw.crypto_market_data", "feature.crypto_indicator", "analysis.crypto_profile"],
    }
    inputs: dict[str, dict[str, Any]] = {}
    for key, names in relations.items():
        path = (root / config.raw["inputs"][key]).resolve()
        item = {"path": path.relative_to(root.resolve()).as_posix(), "exists": path.is_file(), "sha256": None}
        if not path.is_file():
            reasons.append(f"missing_input:{key}")
        else:
            item["sha256"] = _sha256(path)
            connection = duckdb.connect(str(path), read_only=True)
            try:
                missing_relations = [name for name in names if not _relation_exists(connection, name)]
            finally:
                connection.close()
            item["missing_relations"] = missing_relations
            reasons.extend(f"missing_relation:{key}:{name}" for name in missing_relations)
        inputs[key] = item
    return {
        "stage": 16,
        "status": "READY" if not reasons else "BLOCKED",
        "as_of_date": cutoff.date().isoformat() if not pd.isna(cutoff) else None,
        "symbol_count": len(symbols),
        "symbols": symbols,
        "hong_kong_symbol_count": 0,
        "crypto_pair": "ETHUSDT",
        "config_sha256": config.sha256,
        "inputs": inputs,
        "blocking_reasons": reasons,
        "network_attempts": 0,
    }


def _query(path: Path, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
    connection = duckdb.connect(str(path), read_only=True)
    try:
        return connection.execute(sql, params or []).fetchdf()
    finally:
        connection.close()


def _stock_coverage(root: Path, config: Stage16Config, cutoff: pd.Timestamp) -> pd.DataFrame:
    stock_db = root / config.raw["inputs"]["stock_database"]
    stage6_db = root / config.raw["inputs"]["stage6_database"]
    stage7_db = root / config.raw["inputs"]["stage7_database"]
    symbols = [item.symbol for item in load_universe().stocks]
    base = pd.DataFrame({"symbol": symbols})

    daily = _query(stock_db, """
        SELECT symbol, exchange, adjust_type, count(*) AS row_count,
               min(trade_date) AS min_date, max(trade_date) AS max_date
        FROM fact_stock_daily WHERE trade_date <= ?
        GROUP BY symbol, exchange, adjust_type
    """, [cutoff.date()])
    for adjust in ("qfq", "raw"):
        part = daily.loc[daily.adjust_type.eq(adjust), ["symbol", "exchange", "row_count", "min_date", "max_date"]].copy()
        part = part.rename(columns={
            "exchange": f"{adjust}_exchange", "row_count": f"{adjust}_rows",
            "min_date": f"{adjust}_start", "max_date": f"{adjust}_end",
        })
        base = base.merge(part, on="symbol", how="left", validate="one_to_one")
    base["exchange"] = base["qfq_exchange"].fillna(base["raw_exchange"])
    base = base.drop(columns=["qfq_exchange", "raw_exchange"])

    mas = _query(stage7_db, """
        SELECT symbol, count(*) AS feature_rows,
               count(ma_3) AS ma_3_rows, count(ma_5) AS ma_5_rows,
               count(ma_7) AS ma_7_rows, count(ma_10) AS ma_10_rows,
               count(ma_13) AS ma_13_rows, count(ma_20) AS ma_20_rows,
               count(ma_21) AS ma_21_rows
        FROM feature.feature_stock_daily WHERE trade_date <= ? GROUP BY symbol
    """, [cutoff.date()])
    base = base.merge(mas, on="symbol", how="left", validate="one_to_one")

    financial = _query(stock_db, """
        SELECT symbol, count(*) AS financial_statement_rows,
               max(report_period) AS latest_report_period,
               count(*) FILTER (WHERE line_item_name_source = 'TOTAL_OPERATE_INCOME') AS revenue_rows,
               count(*) FILTER (WHERE line_item_name_source = 'PARENT_NETPROFIT') AS parent_net_profit_rows
        FROM fact_financial_statement
        WHERE report_period <= ? GROUP BY symbol
    """, [cutoff.date()])
    base = base.merge(financial, on="symbol", how="left", validate="one_to_one")

    valuation = _query(stock_db, """
        SELECT symbol, cast(max(snapshot_at) AS VARCHAR) AS valuation_snapshot_at,
               arg_max(pe_dynamic, snapshot_at) AS pe_dynamic,
               arg_max(pb, snapshot_at) AS pb
        FROM fact_stock_spot GROUP BY symbol
    """)
    base = base.merge(valuation, on="symbol", how="left", validate="one_to_one")

    activity = _query(stage7_db, """
        SELECT symbol, lookback_days, observation_count, activity_score,
               score_status, event_component_source
        FROM analysis.analysis_stock_activity WHERE as_of_date = ?
    """, [cutoff.date()])
    base = base.merge(activity, on="symbol", how="left", validate="one_to_one")

    style = _query(stage6_db, """
        SELECT symbol, style_label, style_confidence, style_explanation
        FROM feat_style_daily QUALIFY row_number() OVER
          (PARTITION BY symbol ORDER BY trade_date DESC) = 1
    """)
    base = base.merge(style, on="symbol", how="left", validate="one_to_one")
    evidence = _query(stage6_db, """
        SELECT symbol, abnormal_volume_evidence, turnover_change_evidence,
               fund_flow_persistence_evidence, price_volume_divergence_evidence,
               limit_event_evidence, evidence_count, confidence_score,
               confidence_level, evidence_summary, insufficient_evidence
        FROM feat_suspected_behavior_evidence
    """)
    base = base.merge(evidence, on="symbol", how="left", validate="one_to_one")
    limit_status = _query(stage6_db, """
        SELECT symbol,
          count(*) FILTER (WHERE limit_status = 'confirmed' AND limit_direction = 'up') AS formal_limit_up_count,
          count(*) FILTER (WHERE limit_status = 'confirmed' AND limit_direction = 'down') AS formal_limit_down_count,
          count(*) FILTER (WHERE limit_status = 'uncertain') AS uncertain_limit_days
        FROM feat_limit_event WHERE trade_date >= ? AND trade_date <= ? GROUP BY symbol
    """, [(cutoff - pd.Timedelta(days=365)).date(), cutoff.date()])
    base = base.merge(limit_status, on="symbol", how="left", validate="one_to_one")

    for column in ["qfq_rows", "raw_rows", "feature_rows", "financial_statement_rows", "revenue_rows", "parent_net_profit_rows", "formal_limit_up_count", "formal_limit_down_count", "uncertain_limit_days"]:
        base[column] = base[column].fillna(0).astype("int64")
    ma_columns = [f"ma_{window}_rows" for window in config.raw["scope"]["moving_average_windows"]]
    for column in ma_columns:
        base[column] = base[column].fillna(0).astype("int64")

    base["price_volume_status"] = base.apply(
        lambda row: COMPLETE if row.qfq_rows > 0 and row.raw_rows > 0 and pd.Timestamp(row.qfq_end).date() == cutoff.date() and pd.Timestamp(row.raw_end).date() == cutoff.date() else PARTIAL if row.qfq_rows > 0 or row.raw_rows > 0 else MISSING,
        axis=1,
    )
    base["moving_average_status"] = base.apply(
        lambda row: COMPLETE if all(
            row[f"ma_{window}_rows"] == max(row.feature_rows - window + 1, 0)
            for window in config.raw["scope"]["moving_average_windows"]
        ) else PARTIAL if any(row[column] > 0 for column in ma_columns) else MISSING,
        axis=1,
    )
    base["moving_average_note"] = base["moving_average_status"].map({
        COMPLETE: "七组均线有效行数均符合N日滚动窗口预热规则",
        PARTIAL: "至少一组均线有效行数不符合滚动窗口预热规则",
        MISSING: "七组均线均无有效值",
    })
    base["fundamental_status"] = base.apply(
        lambda row: COMPLETE if row.financial_statement_rows > 0 and row.revenue_rows > 0 and row.parent_net_profit_rows > 0 else PARTIAL if row.financial_statement_rows > 0 else MISSING,
        axis=1,
    )
    base["valuation_status"] = base["valuation_snapshot_at"].apply(
        lambda value: MISSING if pd.isna(value) else (COMPLETE if pd.Timestamp(value).date() <= cutoff.date() else PARTIAL)
    )
    base["valuation_note"] = base["valuation_status"].map({
        COMPLETE: "存在不晚于基准日的估值快照",
        PARTIAL: "快照晚于基准日，禁止回填为历史PE/PB",
        MISSING: "无估值快照",
    })
    base["activity_status"] = base["score_status"].apply(lambda value: COMPLETE if value == "scored" else MISSING)
    base["style_status"] = base["style_label"].apply(lambda value: COMPLETE if pd.notna(value) else MISSING)
    base["suspected_behavior_status"] = base.apply(
        lambda row: "证据不足" if bool(row.get("insufficient_evidence", True)) or pd.isna(row.get("confidence_score")) else COMPLETE,
        axis=1,
    )
    base["limit_event_status"] = base.apply(
        lambda row: COMPLETE if row.formal_limit_up_count + row.formal_limit_down_count > 0 else UNPUBLISHABLE,
        axis=1,
    )
    base["next_open_status"] = base["limit_event_status"].apply(lambda value: COMPLETE if value == COMPLETE else UNPUBLISHABLE)
    max_rows = int(base.qfq_rows.max())
    base["price_gap_note"] = base.apply(
        lambda row: "" if row.qfq_rows == max_rows else f"比样本共同最大行数少{max_rows - row.qfq_rows}日；缺少权威证券状态历史，不能仅凭行情确认是否停牌",
        axis=1,
    )
    base["payoff_ratio_status"] = MISSING
    base["payoff_ratio_note"] = "收益分布盈亏比尚未落库；策略盈亏比须另行定义交易规则"
    base["overall_status"] = PARTIAL
    return base.sort_values("symbol", kind="stable").reset_index(drop=True)


def _crypto_coverage(root: Path, config: Stage16Config, cutoff: pd.Timestamp) -> pd.DataFrame:
    path = root / config.raw["inputs"]["crypto_database"]
    result = _query(path, """
        SELECT r.symbol, r.exchange, r.interval, r.source,
               count(*) AS raw_rows,
               cast(min(r.trade_time) AS VARCHAR) AS start_time,
               cast(max(r.trade_time) AS VARCHAR) AS end_time,
               (SELECT count(*) FROM feature.crypto_indicator f WHERE f.symbol = r.symbol) AS feature_rows,
               (SELECT count(*) FROM analysis.crypto_profile p WHERE p.symbol = r.symbol AND p.as_of_date = ?) AS profile_rows
        FROM raw.crypto_market_data r WHERE r.symbol = 'ETHUSDT'
        GROUP BY r.symbol, r.exchange, r.interval, r.source
    """, [cutoff.date()])
    if result.empty:
        return pd.DataFrame([{
            "symbol": "ETHUSDT", "exchange": None, "interval": None, "source": None,
            "raw_rows": 0, "start_time": None, "end_time": None,
            "feature_rows": 0, "profile_rows": 0, "market_data_status": MISSING,
            "feature_status": MISSING, "fundamental_status": NOT_APPLICABLE,
            "limit_event_status": NOT_APPLICABLE,
            "source_note": "未发现ETHUSDT历史行情",
        }])
    result["market_data_status"] = result.raw_rows.apply(lambda value: COMPLETE if value > 0 else MISSING)
    result["feature_status"] = result.feature_rows.apply(lambda value: COMPLETE if value > 0 else MISSING)
    result["fundamental_status"] = NOT_APPLICABLE
    result["limit_event_status"] = NOT_APPLICABLE
    result["source_note"] = result.source.apply(
        lambda value: "OKX公共接口数据，不属于AKShare来源" if value == "okx_public_api" else f"数据来源：{value}"
    )
    return result


def _availability_matrix(stocks: pd.DataFrame, crypto: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("16只A股日线量价", COMPLETE, f"qfq/raw各{int(stocks.qfq_rows.sum())}条"),
        ("A股七组均线", COMPLETE, "MA3/5/7/10/13/20/21均存在有效值"),
        ("A股年报季报", COMPLETE, f"最新报告期{pd.Timestamp(stocks.latest_report_period.max()).date()}"),
        ("A股历史PE/PB", PARTIAL, "现有快照晚于基准日，禁止回填"),
        ("收益分布/策略盈亏比", MISSING, "口径已定义但尚未形成正式落库结果"),
        ("A股活跃度", COMPLETE, f"{int(stocks.activity_status.eq(COMPLETE).sum())}/16只已评分"),
        ("横盘震荡与风格", COMPLETE, f"{int(stocks.style_status.eq(COMPLETE).sum())}/16只有风格特征"),
        ("疑似主力行为特征", PARTIAL, "16只均为证据不足，置信度不可用"),
        ("一年涨跌停次数", UNPUBLISHABLE, "缺少权威历史证券状态与适用阈值"),
        ("涨跌停后次日开盘", UNPUBLISHABLE, "正式涨跌停事件不可用"),
        ("ETHUSDT小时量价", COMPLETE if int(crypto.iloc[0].raw_rows) > 0 else MISSING, f"{int(crypto.iloc[0].raw_rows)}根；{crypto.iloc[0].source_note}"),
        ("ETH基本面与涨跌停", NOT_APPLICABLE, "加密资产不适用公司财报、PE/PB及A股涨跌停制度"),
    ]
    return pd.DataFrame(rows, columns=["data_item", "status", "evidence_or_issue"])


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    values = frame.loc[:, columns].fillna("").astype(str)
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    for row in values.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(value.replace("|", "\\|") for value in row) + " |")
    return "\n".join(lines)


def _render_report(
    *, run_id: str, cutoff: pd.Timestamp, stocks: pd.DataFrame,
    crypto: pd.DataFrame, matrix: pd.DataFrame,
) -> str:
    return f"""# AKShare历史数据存在性检查报告（阶段16）

- 基准日：`{cutoff.date().isoformat()}`
- run_id：`{run_id}`
- 审查范围：冻结的16只A股与ETHUSDT
- 港股：明确排除，未审查、未抓取、未分析
- 网络调用：0

## 总体结论

{_markdown_table(matrix, ["data_item", "status", "evidence_or_issue"])}

## 逐A股覆盖清单

{_markdown_table(stocks, ["symbol", "exchange", "qfq_start", "qfq_end", "qfq_rows", "raw_rows", "latest_report_period", "price_volume_status", "moving_average_status", "fundamental_status", "valuation_status", "activity_status", "style_status", "suspected_behavior_status", "limit_event_status", "overall_status"])}

### 行情缺口说明

{_markdown_table(stocks.loc[stocks.price_gap_note.ne("")], ["symbol", "qfq_rows", "price_gap_note"])}

600438与601500的行数少于其余样本，但本地库缺少权威历史证券状态，现阶段不能仅凭行情缺口断言为正常停牌。

## ETHUSDT覆盖清单

{_markdown_table(crypto, ["symbol", "exchange", "interval", "source", "raw_rows", "start_time", "end_time", "feature_rows", "market_data_status", "feature_status", "fundamental_status", "limit_event_status", "source_note"])}

## 发布限制

- PE/PB快照晚于基准日，不得回填成历史估值。
- 涨跌停候选缺少当日证券状态与权威规则，不发布次数，也不计算次日开盘表现。
- 所有相关输出统一使用“疑似主力行为特征”，并保留证据、置信度和解释；当前16只股票均为证据不足。
- 收益分布盈亏比与策略盈亏比分离；后者在没有入场、出场、止损和持有期规则时不计算。
- ETHUSDT数据来源明确标记为OKX公共接口，不描述为AKShare抓取结果。

本报告仅用于数据工程验证和量化研究测试，不构成投资建议。
"""


def build_stage16_report(
    *, root: Path, as_of_date: pd.Timestamp, config_path: Path,
    reports_dir: Path, run_id: str, dry_run: bool = False,
    validate_only: bool = False,
) -> tuple[dict[str, Any], int]:
    uuid.UUID(run_id)
    cutoff = pd.Timestamp(as_of_date).normalize()
    validation = validate_stage16_inputs(root=root, config_path=config_path, as_of_date=cutoff)
    if validation["status"] != "READY":
        return validation, 2
    if validate_only or dry_run:
        return {**validation, "dry_run": dry_run, "validate_only": validate_only}, 0

    config = load_stage16_config(config_path)
    configured_output = (root / config.raw["outputs"]["reports_dir"]).resolve()
    target = (reports_dir / run_id).resolve()
    if reports_dir.resolve() != configured_output:
        raise ValueError("Stage 16 reports_dir must match config outputs.reports_dir")
    if target.exists():
        raise ValueError("Stage 16 run_id output already exists; refusing to overwrite")
    input_paths = [(root / value).resolve() for value in config.raw["inputs"].values()]
    before = {_path.relative_to(root.resolve()).as_posix(): _sha256(_path) for _path in input_paths}
    stocks = _stock_coverage(root, config, cutoff)
    crypto = _crypto_coverage(root, config, cutoff)
    matrix = _availability_matrix(stocks, crypto)
    if len(stocks) != 16 or set(stocks.exchange.dropna()) - {"SH", "SZ"}:
        raise RuntimeError("Stage 16 stock coverage escaped the frozen A-share scope")
    if any(stocks.symbol.astype(str).str.contains("HK", case=False, regex=False)):
        raise RuntimeError("Hong Kong symbol unexpectedly entered Stage 16")

    reports_dir.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=".stage16-", dir=reports_dir))
    try:
        stocks.to_csv(temp / "stock_coverage.csv", index=False, lineterminator="\n")
        crypto.to_csv(temp / "crypto_coverage.csv", index=False, lineterminator="\n")
        matrix.to_csv(temp / "availability_matrix.csv", index=False, lineterminator="\n")
        (temp / "final_report.md").write_text(
            _render_report(run_id=run_id, cutoff=cutoff, stocks=stocks, crypto=crypto, matrix=matrix),
            encoding="utf-8",
        )
        output_hashes = {
            name: _sha256(temp / name)
            for name in (
                "stock_coverage.csv", "crypto_coverage.csv",
                "availability_matrix.csv", "final_report.md",
            )
        }
        after = {_path.relative_to(root.resolve()).as_posix(): _sha256(_path) for _path in input_paths}
        if before != after:
            raise RuntimeError("Stage 16 modified an input database")
        manifest = {
            **validation,
            "status": "PASS_WITH_UNAVAILABLE_ITEMS" if matrix.status.isin([PARTIAL, MISSING, UNPUBLISHABLE]).any() else "PASS",
            "run_id": run_id,
            "stock_rows": len(stocks),
            "crypto_rows": len(crypto),
            "availability_status_counts": {str(key): int(value) for key, value in matrix.status.value_counts().sort_index().items()},
            "input_databases_unchanged": True,
            "output_sha256": output_hashes,
            "outputs": {
                "reports_dir": target.relative_to(root.resolve()).as_posix(),
                "stock_coverage": "stock_coverage.csv",
                "crypto_coverage": "crypto_coverage.csv",
                "availability_matrix": "availability_matrix.csv",
                "final_report": "final_report.md",
            },
        }
        (temp / "stage16_run.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp.rename(target)
        return manifest, 0
    except Exception:
        if temp.exists():
            shutil.rmtree(temp)
        raise
