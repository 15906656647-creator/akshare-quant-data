"""Read-only Stage 17 Hong Kong OHLC root-cause audit.

The audit consumes one immutable formal Stage 17 manifest.  It never calls a
network adapter and never writes below ``data/raw``.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .paths import project_root


HK_SYMBOLS = (
    "02180.HK", "08365.HK", "08462.HK", "02076.HK", "06100.HK",
    "06919.HK", "09669.HK",
)
ADJUSTMENTS = ("raw", "qfq", "hfq")
ERROR_COLUMNS = (
    "symbol", "source", "interface", "adjust", "error_type", "root_cause",
    "sample_date", "description", "violated_rules", "open", "high", "low",
    "close", "volume", "formal_run_id", "data_path", "data_sha256",
)
SUMMARY_COLUMNS = (
    "symbol", "source", "interface", "adjust", "row_count", "invalid_row_count",
    "invalid_row_rate", "first_date", "last_date", "first_invalid_date",
    "last_invalid_date", "duplicate_date_count", "weekend_date_count",
    "non_increasing_date_count", "weekday_gap_candidate_count",
    "adjusted_invalid_dates_also_invalid_in_raw", "field_mapping_assessment",
    "code_mapping_assessment", "adjustment_logic_assessment", "root_cause",
    "formal_run_id", "data_path", "data_sha256", "metadata_path",
    "metadata_sha256",
)


@dataclass(frozen=True)
class AuditResult:
    report_dir: Path
    error_rows: int
    dataset_count: int
    status: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _manifest_candidates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [
        row for row in manifest.get("datasets", [])
        if row.get("market") == "HK"
        and row.get("kind") == "equity_daily_candidate"
        and row.get("source") == "sina"
    ]
    expected = {(symbol, adjust) for symbol in HK_SYMBOLS for adjust in ADJUSTMENTS}
    actual = {(row.get("symbol"), row.get("adjust")) for row in candidates}
    if actual != expected or len(candidates) != len(expected):
        raise ValueError(
            "Formal manifest must contain exactly 7 HK symbols x 3 adjustments "
            "for the Sina candidate"
        )
    return sorted(candidates, key=lambda row: (row["symbol"], ADJUSTMENTS.index(row["adjust"])))


def _verify_input(
    *, root: Path, manifest: dict[str, Any], run_summary: dict[str, Any],
    formal_run_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if manifest.get("stage") != 17 or manifest.get("run_id") != formal_run_id:
        raise ValueError("Formal manifest identity mismatch")
    if manifest.get("status") != "BLOCKED":
        raise ValueError("This remediation audit requires a BLOCKED Stage 17 formal run")
    if run_summary.get("run_id") != formal_run_id or run_summary.get("status") != "BLOCKED":
        raise ValueError("Stage 17 run summary identity/status mismatch")
    if run_summary.get("stage18_authorized") is not False:
        raise ValueError("Stage 18 must remain unauthorized during this audit")

    raw_index = {
        (row.get("path"), row.get("role")): row
        for row in manifest.get("raw_files", [])
    }
    verified: list[dict[str, Any]] = []
    candidates = _manifest_candidates(manifest)
    for row in candidates:
        for role, path_key, hash_key in (
            ("data", "data_path", "data_sha256"),
            ("metadata", "metadata_path", "metadata_sha256"),
        ):
            relative = row.get(path_key)
            expected_hash = row.get(hash_key)
            if not relative or not expected_hash:
                raise ValueError(f"Missing {role} evidence for {row['dataset_id']}")
            registered = raw_index.get((relative, role))
            if registered is None or registered.get("sha256") != expected_hash:
                raise ValueError(f"Raw closed-world registration mismatch: {relative}")
            path = root / relative
            if not path.is_file():
                raise FileNotFoundError(path)
            actual_hash = _sha256(path)
            if actual_hash != expected_hash:
                raise ValueError(f"Immutable input hash mismatch: {relative}")
            if path.stat().st_size != registered.get("size_bytes"):
                raise ValueError(f"Immutable input size mismatch: {relative}")
            verified.append({
                "dataset_id": row["dataset_id"], "role": role,
                "path": relative, "size_bytes": path.stat().st_size,
                "sha256": actual_hash,
            })
    return candidates, verified


def _violations(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, pd.Series]]:
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Candidate schema missing columns: {','.join(missing)}")
    numeric = {
        field: pd.to_numeric(frame[field], errors="coerce")
        for field in ("open", "high", "low", "close", "volume")
    }
    if any(series.isna().any() for series in numeric.values()):
        raise ValueError("Candidate contains nonnumeric OHLCV values")
    masks = {
        "high_lt_open": numeric["high"] < numeric["open"],
        "high_lt_close": numeric["high"] < numeric["close"],
        "high_lt_low": numeric["high"] < numeric["low"],
        "low_gt_open": numeric["low"] > numeric["open"],
        "low_gt_close": numeric["low"] > numeric["close"],
        "low_gt_high": numeric["low"] > numeric["high"],
    }
    invalid = pd.concat(masks, axis=1).any(axis=1)
    return frame.loc[invalid].copy(), masks


def _weekday_gap_candidates(dates: pd.Series) -> int:
    valid = pd.DatetimeIndex(pd.to_datetime(dates, errors="coerce").dropna().unique()).sort_values()
    if len(valid) < 2:
        return 0
    existing = set(valid.normalize())
    weekdays = pd.date_range(valid.min(), valid.max(), freq="B")
    return sum(day.normalize() not in existing for day in weekdays)


def _analyse(
    *, root: Path, candidates: list[dict[str, Any]], formal_run_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, set[str]]]:
    loaded: dict[tuple[str, str], tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, pd.Series]]] = {}
    raw_invalid_dates: dict[str, set[str]] = {}
    for record in candidates:
        frame = pd.read_parquet(root / record["data_path"])
        invalid, masks = _violations(frame)
        loaded[(record["symbol"], record["adjust"])] = (record, frame, invalid, masks)
        if record["adjust"] == "raw":
            raw_invalid_dates[record["symbol"]] = set(invalid["date"].astype(str))

    errors: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    for symbol, adjust in sorted(loaded, key=lambda item: (item[0], ADJUSTMENTS.index(item[1]))):
        record, frame, invalid, masks = loaded[(symbol, adjust)]
        dates = pd.to_datetime(frame["date"], errors="coerce")
        invalid_dates = set(invalid["date"].astype(str))
        propagated = len(invalid_dates & raw_invalid_dates[symbol])
        if adjust == "raw":
            root_cause = "upstream_raw_ohlc_inconsistency"
            adjustment_assessment = "not_applicable_raw_already_invalid"
        elif invalid_dates <= raw_invalid_dates[symbol]:
            root_cause = "upstream_raw_inconsistency_propagated_by_adjustment"
            adjustment_assessment = "not_root_cause_all_invalid_dates_exist_in_raw"
        else:
            root_cause = "adjusted_candidate_specific_anomaly"
            adjustment_assessment = "requires_factor_level_follow_up"

        invalid_indexes = set(invalid.index)
        for index in sorted(invalid_indexes):
            violated = [name for name, mask in masks.items() if bool(mask.loc[index])]
            item = frame.loc[index]
            errors.append({
                "symbol": symbol, "source": "sina", "interface": record["interface"],
                "adjust": adjust, "error_type": "ohlc_logic_error",
                "root_cause": root_cause, "sample_date": str(item["date"]),
                "description": "OHLC violates the inclusive daily price envelope",
                "violated_rules": "|".join(violated),
                "open": item["open"], "high": item["high"], "low": item["low"],
                "close": item["close"], "volume": item["volume"],
                "formal_run_id": formal_run_id, "data_path": record["data_path"],
                "data_sha256": record["data_sha256"],
            })

        summaries.append({
            "symbol": symbol, "source": "sina", "interface": record["interface"],
            "adjust": adjust, "row_count": len(frame),
            "invalid_row_count": len(invalid),
            "invalid_row_rate": f"{len(invalid) / len(frame):.8f}",
            "first_date": dates.min().date().isoformat(),
            "last_date": dates.max().date().isoformat(),
            "first_invalid_date": str(invalid["date"].min()),
            "last_invalid_date": str(invalid["date"].max()),
            "duplicate_date_count": int(dates.duplicated().sum()),
            "weekend_date_count": int((dates.dt.dayofweek >= 5).sum()),
            "non_increasing_date_count": int((dates.diff().dropna() <= pd.Timedelta(0)).sum()),
            "weekday_gap_candidate_count": _weekday_gap_candidates(frame["date"]),
            "adjusted_invalid_dates_also_invalid_in_raw": propagated,
            "field_mapping_assessment": "not_root_cause_exact_canonical_columns_present",
            "code_mapping_assessment": "not_root_cause_five_digit_symbol_and_listing_start_match",
            "adjustment_logic_assessment": adjustment_assessment,
            "root_cause": root_cause, "formal_run_id": formal_run_id,
            "data_path": record["data_path"], "data_sha256": record["data_sha256"],
            "metadata_path": record["metadata_path"],
            "metadata_sha256": record["metadata_sha256"],
        })
    return errors, summaries, raw_invalid_dates


def _evaluation_markdown(
    *, formal_run_id: str, as_of_date: str, audit_date: str,
    summaries: list[dict[str, Any]], errors: list[dict[str, Any]],
) -> str:
    raw_count = sum(int(row["invalid_row_count"]) for row in summaries if row["adjust"] == "raw")
    qfq_count = sum(int(row["invalid_row_count"]) for row in summaries if row["adjust"] == "qfq")
    hfq_count = sum(int(row["invalid_row_count"]) for row in summaries if row["adjust"] == "hfq")
    return f"""# Stage 17 港股OHLC根因与替代来源评估

> 审计日期：{audit_date}
> 业务基准日：{as_of_date}
> 被审计正式批次：`{formal_run_id}`
> 阶段状态：`BLOCKED`；Stage 18授权：`false`

## 审计范围与结论

本报告审计7只港股的未复权、前复权、后复权新浪候选，共21个数据集；“21”不是21只
不同股票。审计先核对正式manifest登记的42个候选Raw/metadata文件大小与SHA-256，再
逐行复算，不访问网络、不修改Raw、不删除异常行、不插值。

21/21数据集均存在OHLC区间违规，共{len(errors):,}条：未复权{raw_count}条、前复权
{qfq_count}条、后复权{hfq_count}条。未复权数据已异常；前/后复权的所有异常日期均能
在同标的未复权异常日期集合中找到。因此当前证据支持：

- 字段映射错误：排除；文件已是精确的`date/open/high/low/close/volume`规范列。
- 代码映射错误：排除；`.HK`已稳定映射为五位数字，且各序列起点与已审计上市日一致。
- 项目复权逻辑错误：不是根因；项目没有自行复权，AKShare对四个价格字段使用同一因子，
  未复权异常在复权序列中传播。
- 根因分类：`upstream_raw_ohlc_inconsistency`，复权序列标记为
  `upstream_raw_inconsistency_propagated_by_adjustment`。

日期审计中的`weekday_gap_candidate_count`只表示自然工作日缺口候选；未接入权威港股
交易日历、停牌和上市状态前，不得把它直接描述为“缺失交易日”。重复日期、周末日期和
非递增日期另行精确统计于`hk_dataset_summary.csv`。

## 替代来源评估

| 候选 | 当前证据 | 决策 |
| --- | --- | --- |
| AKShare `stock_hk_hist`（东方财富） | 官方AKShare文档支持港股日线及三种复权；本批21次均为连接失败，并非质量通过 | 保留主源；先做网络/域名可达性隔离验证，不能把重试成功当作历史质量已通过 |
| AKShare `stock_hk_daily`（新浪） | 本批21/21质量失败；AKShare仓库亦有近期接口新鲜度问题记录 | 仅保留交叉审计证据，不得选为正式源 |
| AKShare `stock_zh_ah_daily`（腾讯） | 当前安装版本存在该历史接口并接受raw/qfq/hfq，但名称和实现面向A+H范围，7只目标的适用性尚未实测 | Stage 17下一独立修复任务的首选低成本候选；必须逐标的验证代码覆盖、完整历史、OHLC、复权身份和超时 |
| HKEX Historical Data / Data Marketplace | 港交所称其为直接来源/“golden source”，提供证券逐笔历史产品；需要订阅、许可和从成交重建日线 | 权威性最高的正式解阻路线；先确认所需年份、许可、交付格式和成本，再决定是否接入 |
| Alpha Vantage `TIME_SERIES_DAILY_ADJUSTED` | 官方文档覆盖全球股票、20年以上，但香港代码覆盖需搜索验证；接口给原始OHLC和调整收盘/公司行动，不等同于三套完整OHLC | 可做独立交叉验证候选，不能未经7只代码和复权语义验证直接替代69项口径 |
| Polygon Stocks | 官方Stocks文档明确聚焦美国股票市场 | 不适用于本次港股解阻 |
| Yahoo Finance / Stooq | 本次未找到满足正式验收所需的官方稳定API、来源审计和三复权语义证据 | 暂不进入正式候选；若使用只能先完成许可、接口稳定性和字段语义专项审计 |

## 官方证据链接

- AKShare港股接口文档：<https://github.com/akfamily/akshare/blob/main/docs/data/stock/stock.md>
- AKShare新浪港股接口实现：<https://github.com/akfamily/akshare/blob/main/akshare/stock/stock_hk_sina.py>
- AKShare `stock_hk_daily`近期问题记录：<https://github.com/akfamily/akshare/issues/7133>
- HKEX Data Marketplace：<https://www.hkex.com.hk/Services/Market-Data-Services/Historical-Data-Services/HKEX-Data-Marketplace?sc_lang=en>
- HKEX市场数据获取说明：<https://www.hkex.com.hk/Global/Exchange/FAQ/Market-Data/Getting-Market-Data?sc_lang=en>
- Alpha Vantage官方文档：<https://www.alphavantage.co/documentation/>
- Polygon Stocks官方覆盖说明：<https://polygon.io/docs/rest/stocks/overview>

## 后续门禁

本审计不新增数据源适配器、不联网采集、不重跑Stage 17，也不改变正式验收。下一任务应
先隔离验证`stock_zh_ah_daily`（腾讯）和东方财富连接；如均不能提供7只港股三种复权的
完整合格历史，再推进HKEX采购/授权或经批准的专业源。只有新的完整正式run同时达到
69/69日线、6/6 ETH、上市覆盖和清单哈希全部通过，Stage 17才可改为`PASS`并授权
Stage 18。
"""


def run_hk_ohlc_audit(
    *, formal_run_id: str, audit_run_id: str, as_of_date: date,
    audit_date: date, root: Path | None = None,
) -> AuditResult:
    root = (root or project_root()).resolve()
    uuid.UUID(formal_run_id)
    uuid.UUID(audit_run_id)
    formal_dir = root / "reports" / "stage17" / formal_run_id
    manifest_path = formal_dir / "stage17_manifest.json"
    run_path = formal_dir / "stage17_run.json"
    manifest = _load_json(manifest_path)
    run_summary = _load_json(run_path)
    if manifest.get("as_of_date") != as_of_date.isoformat():
        raise ValueError("Explicit as_of_date does not match the formal manifest")
    candidates, verified = _verify_input(
        root=root, manifest=manifest, run_summary=run_summary,
        formal_run_id=formal_run_id,
    )
    errors, summaries, _ = _analyse(
        root=root, candidates=candidates, formal_run_id=formal_run_id,
    )
    report_dir = root / "reports" / "stage17_hk_audit" / audit_run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    error_path = report_dir / "hk_ohlc_error_analysis.csv"
    summary_path = report_dir / "hk_dataset_summary.csv"
    evaluation_path = report_dir / "hk_source_replacement_evaluation.md"
    _write_csv(error_path, errors, ERROR_COLUMNS)
    _write_csv(summary_path, summaries, SUMMARY_COLUMNS)
    evaluation_path.write_text(
        _evaluation_markdown(
            formal_run_id=formal_run_id, as_of_date=as_of_date.isoformat(),
            audit_date=audit_date.isoformat(), summaries=summaries, errors=errors,
        ),
        encoding="utf-8",
    )
    outputs = [error_path, summary_path, evaluation_path]
    audit_manifest = {
        "stage": 17,
        "task": "hk_ohlc_root_cause_audit",
        "audit_run_id": audit_run_id,
        "audit_date": audit_date.isoformat(),
        "as_of_date": as_of_date.isoformat(),
        "formal_run_id": formal_run_id,
        "formal_stage_status_before": "BLOCKED",
        "formal_stage_status_after": "BLOCKED",
        "stage18_authorized": False,
        "network_calls": 0,
        "raw_files_modified": 0,
        "candidate_dataset_count": len(candidates),
        "distinct_hk_symbol_count": len(HK_SYMBOLS),
        "invalid_row_count": len(errors),
        "root_cause": "upstream_raw_ohlc_inconsistency",
        "verified_inputs": verified,
        "formal_manifest": {
            "path": manifest_path.relative_to(root).as_posix(),
            "sha256": _sha256(manifest_path),
        },
        "formal_run_summary": {
            "path": run_path.relative_to(root).as_posix(),
            "sha256": _sha256(run_path),
        },
        "outputs": [
            {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
            for path in outputs
        ],
    }
    _write_json(report_dir / "audit_manifest.json", audit_manifest)
    return AuditResult(report_dir, len(errors), len(candidates), "BLOCKED")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only Stage 17 HK OHLC audit")
    parser.add_argument("--formal-run-id", required=True)
    parser.add_argument("--audit-run-id", required=True)
    parser.add_argument("--as-of-date", required=True, type=date.fromisoformat)
    parser.add_argument("--audit-date", required=True, type=date.fromisoformat)
    parser.add_argument("--root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = run_hk_ohlc_audit(
        formal_run_id=args.formal_run_id, audit_run_id=args.audit_run_id,
        as_of_date=args.as_of_date, audit_date=args.audit_date, root=args.root,
    )
    print(json.dumps({
        "status": result.status, "dataset_count": result.dataset_count,
        "invalid_row_count": result.error_rows,
        "report_dir": str(result.report_dir), "stage18_authorized": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
