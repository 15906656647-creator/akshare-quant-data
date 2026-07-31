"""Stage 3 market-fetch orchestration and evidence generation."""
from __future__ import annotations

import csv
import json
import subprocess
import time
import uuid
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .adapters.stock_market import StockMarketAdapter
from .collectors.market_collector import DatasetRecord, MarketCollector
from .config import load_metrics, load_universe
from .paths import project_root
from .storage.raw_store import RawStore, file_record

COVERAGE_COLUMNS = (
    "run_id",
    "dataset_id",
    "symbol",
    "adjust",
    "status",
    "row_count",
    "column_count",
    "min_date",
    "max_date",
    "schema_hash",
    "quality_status",
    "warning_count",
    "error_count",
    "raw_path",
    "error_type",
    "error_message",
)


def historical_start_date(as_of_date: date, years: int) -> date:
    """Subtract calendar years deterministically, including leap-day handling."""
    try:
        return as_of_date.replace(year=as_of_date.year - years)
    except ValueError:
        return as_of_date.replace(year=as_of_date.year - years, day=28)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


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
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except OSError:
        return ""


def _documentation(
    *,
    run_id: str,
    status: str,
    as_of_date: date,
    start_date: date,
    spot: dict[str, Any],
    history_success: int,
    expected: int,
) -> str:
    return f"""# 阶段3：行情与实时估值抓取

- Run ID：`{run_id}`
- 阶段状态：**{status}**
- 历史日线业务区间：`{start_date}` 至 `{as_of_date}`
- 开始日期算法：从业务结束日期确定性减去阶段0配置的3个自然年
- 历史日线成功：`{history_success}/{expected}`
- 实时快照时间：`{spot.get('snapshot_at', '')}`
- 全市场实时行情行数：`{spot.get('full_market_rows', 0)}`
- 目标股票数量：`{spot.get('target_count', 0)}/16`
- 缺失代码：`{', '.join(spot.get('missing_symbols', [])) or '无'}`

## 数据边界

历史日线截至 `{as_of_date}`；实时行情是本次任务实际执行时采集的快照，
没有回填为历史估值。Raw 文件保留 AKShare 原始字段，按 run_id 追加保存。

本阶段只调用 `stock_zh_a_hist` 和 `stock_zh_a_spot_em`。未抓取财务、
资金流、涨跌停或加密货币数据；未创建 Clean、Feature 或业务数据库；
未计算均线、收益率、波动率、活跃度或其他分析指标。
"""


def run_market_fetch(
    *,
    as_of_date: date,
    output_dir: str | Path = "data/raw",
    evidence_dir: str | Path = "reports/evidence/stage3",
    run_id: str | None = None,
    only_symbol: str | None = None,
    skip_spot: bool = False,
    adapter: StockMarketAdapter | None = None,
    inter_symbol_delay_seconds: float = 0.3,
    now: Any | None = None,
    project_root_override: str | Path | None = None,
) -> tuple[dict[str, Any], int]:
    root = (
        Path(project_root_override).resolve()
        if project_root_override is not None
        else project_root()
    )
    universe = load_universe()
    metrics = load_metrics()
    years = int(metrics.raw["data_ranges"]["stock_daily"]["default_years"])
    start_date = historical_start_date(as_of_date, years)
    chosen = universe.stocks
    if only_symbol:
        chosen = [item for item in chosen if item.symbol == only_symbol]
        if not chosen:
            raise ValueError(f"--only-symbol is not in configured universe: {only_symbol}")
    actual_run_id = run_id or str(uuid.uuid4())
    # Strict UUID validation keeps run partitions stable and path-safe.
    uuid.UUID(actual_run_id)
    clock = now or (lambda: datetime.now(ZoneInfo(universe.timezone)))
    market_adapter = adapter or StockMarketAdapter()
    raw_root = Path(output_dir)
    if not raw_root.is_absolute():
        raw_root = root / raw_root
    evidence_root = Path(evidence_dir)
    if not evidence_root.is_absolute():
        evidence_root = root / evidence_root
    store = RawStore(raw_root)
    collector = MarketCollector(
        adapter=market_adapter,
        store=store,
        now=clock,
        project_root=root,
    )
    started_at = clock()
    records: list[DatasetRecord] = []
    for index, stock in enumerate(chosen):
        for adjust in ("qfq", ""):
            records.append(
                collector.collect_history(
                    run_id=actual_run_id,
                    symbol=stock.symbol,
                    exchange=stock.exchange,
                    adjust=adjust,
                    start_date=start_date,
                    as_of_date=as_of_date,
                )
            )
        if inter_symbol_delay_seconds > 0 and index < len(chosen) - 1:
            time.sleep(inter_symbol_delay_seconds)
    spot_summary: dict[str, Any] = {
        "snapshot_at": "",
        "full_market_rows": 0,
        "target_count": 0,
        "missing_symbols": [x.symbol for x in chosen],
        "field_availability": [],
        "full_market_raw_path": "",
        "target_raw_path": "",
        "skipped": skip_spot,
    }
    if not skip_spot:
        spot_records, spot_summary, _ = collector.collect_spot(
            run_id=actual_run_id,
            target_symbols=[x.symbol for x in chosen],
            as_of_date=as_of_date,
        )
        spot_summary["skipped"] = False
        records.extend(spot_records)
    finished_at = clock()
    history_records = [r for r in records if r.interface_name == "stock_zh_a_hist"]
    expected_history = len(chosen) * 2
    history_success = sum(
        r.status == "success" and r.quality_status != "ERROR" for r in history_records
    )
    spot_ok = skip_spot or (
        spot_summary["target_count"] == len(chosen)
        and any(
            r.dataset_id == "stock_zh_a_spot_em:full_market" and r.status == "success"
            for r in records
        )
    )
    status = "PASS" if history_success == expected_history and spot_ok else "PARTIAL"
    coverage_path = root / "reports/stage3_market_coverage.csv"
    run_path = root / "reports/stage3_market_run.json"
    field_path = root / "reports/stage3_spot_field_availability.csv"
    doc_path = root / "docs/stage3_market_fetch.md"
    record_dicts = [item.to_dict() for item in records]
    _write_csv(coverage_path, record_dicts, COVERAGE_COLUMNS)
    _write_csv(
        field_path,
        [
            {
                "run_id": actual_run_id,
                "snapshot_at": spot_summary["snapshot_at"],
                **item,
            }
            for item in spot_summary["field_availability"]
        ],
        ("run_id", "snapshot_at", "field", "available"),
    )
    comparisons: list[dict[str, Any]] = []
    for stock in chosen:
        pair = {("raw" if r.adjust == "" else r.adjust): r for r in history_records if r.symbol == stock.symbol}
        qfq = pair.get("qfq")
        raw = pair.get("raw")
        comparisons.append(
            {
                "symbol": stock.symbol,
                "qfq_row_count": 0 if qfq is None else qfq.row_count,
                "raw_row_count": 0 if raw is None else raw.row_count,
                "qfq_min_date": "" if qfq is None else qfq.min_date,
                "qfq_max_date": "" if qfq is None else qfq.max_date,
                "raw_min_date": "" if raw is None else raw.min_date,
                "raw_max_date": "" if raw is None else raw.max_date,
                "date_key_match": bool(
                    qfq
                    and raw
                    and qfq.row_count == raw.row_count
                    and qfq.min_date == raw.min_date
                    and qfq.max_date == raw.max_date
                ),
            }
        )
    run_report = {
        "run_id": actual_run_id,
        "status": status,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "as_of_date": as_of_date.isoformat(),
        "historical_start_date": start_date.isoformat(),
        "historical_start_rule": f"as_of_date minus {years} calendar years",
        "stock_count": len(chosen),
        "daily_expected_count": expected_history,
        "daily_success_count": history_success,
        "spot": spot_summary,
        "qfq_raw_comparison": comparisons,
        "status_counts": dict(Counter(r.status for r in records)),
        "datasets": record_dicts,
    }
    _write_json(run_path, run_report)
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(
        _documentation(
            run_id=actual_run_id,
            status=status,
            as_of_date=as_of_date,
            start_date=start_date,
            spot=spot_summary,
            history_success=history_success,
            expected=expected_history,
        ),
        encoding="utf-8",
    )
    raw_paths = sorted({r.raw_path for r in records if r.raw_path})
    report_paths = [coverage_path, run_path, field_path, doc_path]
    manifest_path = evidence_root / actual_run_id / "manifest.json"
    manifest = {
        "run_id": actual_run_id,
        "created_at": clock().isoformat(),
        "as_of_date": as_of_date.isoformat(),
        "historical_start_date": start_date.isoformat(),
        "snapshot_at": spot_summary["snapshot_at"],
        "python_version": history_records[0].python_version if history_records else "",
        "akshare_version": market_adapter.akshare_version,
        "git_commit": _git_commit(root),
        "stock_count": len(chosen),
        "daily_expected_count": expected_history,
        "daily_success_count": history_success,
        "spot_status": "skipped" if skip_spot else ("success" if spot_ok else "failed"),
        "spot_target_count": spot_summary["target_count"],
        "status_counts": dict(Counter(r.status for r in records)),
        "raw_files": [file_record(root / path, root) for path in raw_paths],
        "report_files": [file_record(path, root) for path in report_paths],
    }
    _write_json(manifest_path, manifest)
    run_report["manifest_path"] = manifest_path.resolve().relative_to(root.resolve()).as_posix()
    return run_report, 0 if status == "PASS" else 1
