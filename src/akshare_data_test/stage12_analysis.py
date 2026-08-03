"""Unified offline orchestration for reproducible Stage 12 analyses."""
from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

from .analysis.active_stocks import analyze_active_stocks
from .analysis.fundamental_price_volume import analyze_fundamental_price_volume
from .analysis.range_bound import analyze_range_bound
from .analysis.stage12_common import canonical_frame_hash, normalize_price_frame
from .analysis.volume_breakout import analyze_volume_breakouts
from .quality.stage12_checks import run_stage12_quality_checks
from .stage12_config import load_stage12_config
from .storage.stage12_repository import write_stage12_run


def _visible_fundamentals(frame: pd.DataFrame | None, cutoff: pd.Timestamp) -> tuple[pd.DataFrame | None, int]:
    if frame is None:
        return None, 0
    data = frame.copy()
    if "symbol" in data and "instrument" not in data:
        data = data.rename(columns={"symbol": "instrument"})
    if "instrument" not in data:
        raise ValueError("Stage 12 fundamental input missing instrument")
    data["instrument"] = data["instrument"].astype("string").str.strip().str.zfill(6)
    if data["instrument"].isna().any() or data["instrument"].eq("").any():
        raise ValueError("Stage 12 fundamental instrument cannot be empty")
    date_column = next((name for name in ("available_date", "announcement_date", "fundamental_as_of_date") if name in data), None)
    if date_column is None:
        raise ValueError("Stage 12 fundamental input requires available_date or announcement_date")
    data[date_column] = pd.to_datetime(data[date_column], errors="coerce").dt.normalize()
    if data[date_column].isna().any():
        raise ValueError("Stage 12 fundamental availability date is invalid")
    if data.duplicated(["instrument", date_column]).any():
        raise ValueError("Stage 12 fundamental input contains duplicate business keys")
    future_count = int(data[date_column].gt(cutoff).sum())
    visible = data.loc[data[date_column].le(cutoff)].copy()
    score_ranges = {
        "valuation_score": (0.0, 1.0),
        "growth_score": (0.0, 1.0),
        "profitability_score": (0.0, 100.0),
        "quality_score": (0.0, 100.0),
        "financial_health_score": (0.0, 100.0),
    }
    raw_numeric = ("revenue_growth", "profit_growth")
    for column, (minimum, maximum) in score_ranges.items():
        if column not in visible:
            continue
        numeric = pd.to_numeric(visible[column], errors="coerce")
        invalid = numeric.isna() | ~np.isfinite(numeric.to_numpy(dtype=float))
        if invalid.any():
            raise ValueError(
                f"fundamental.{column} must be a finite numeric value when the field is present"
            )
        outside = numeric.lt(minimum) | numeric.gt(maximum)
        if outside.any():
            value = visible.loc[outside, column].iloc[0]
            raise ValueError(
                f"fundamental.{column} must be within [{minimum:g}, {maximum:g}], got {value!r}"
            )
        visible[column] = numeric
    for column in raw_numeric:
        if column not in visible:
            continue
        numeric = pd.to_numeric(visible[column], errors="coerce")
        invalid = numeric.isna() | ~np.isfinite(numeric.to_numpy(dtype=float))
        if invalid.any():
            raise ValueError(
                f"fundamental.{column} must be a finite numeric value when the field is present"
            )
        visible[column] = numeric
    return visible, future_count


def _blocked_fundamental_manifest(
    *, run_id: str, cutoff: pd.Timestamp, config: Any, visible_price_rows: int,
    future_price_rows: int, reason: str, dry_run: bool, output_type: str,
) -> dict[str, Any]:
    deterministic_time = cutoff.tz_localize("UTC")
    return {
        "stage": 12, "run_id": run_id, "status": "BLOCKED",
        "as_of_date": cutoff.date().isoformat(),
        "started_at": deterministic_time.isoformat(),
        "completed_at": deterministic_time.isoformat(),
        "input_row_counts": {
            "price_visible": visible_price_rows,
            "price_future_excluded": future_price_rows,
            "fundamental_visible": 0,
            "fundamental_future_excluded": 0,
        },
        "output_row_counts": {
            "active": 0, "breakouts": 0, "ranges": 0, "combined": 0, "quality": 0,
        },
        "blocking_reasons": [f"invalid_fundamental_input:{reason}"],
        "warnings": [], "config_sha256": config.sha256,
        "input_sha256": None, "canonical_sha256": None, "output_hashes": {},
        "database_write_status": "not_written_blocked", "dry_run": bool(dry_run),
        "model_version": config.model_version, "network_calls": 0,
        "price_adjust_type": config.raw["price_adjust_type"],
        "output_type": str(output_type),
    }


def _combined_hash(hashes: dict[str, str]) -> str:
    payload = json.dumps(hashes, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _csv_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    if "reason_codes" in result:
        result["reason_codes"] = result["reason_codes"].map(
            lambda value: json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        )
    return result


def render_stage12_report(manifest: dict[str, Any]) -> str:
    blockers = "\n".join(f"- {value}" for value in manifest["blocking_reasons"]) or "- 无"
    warnings = "\n".join(f"- {value}" for value in manifest["warnings"]) or "- 无"
    return f"""# Stage 12：量化分析示例与结果验证

## 分析目标与范围

- 截止日期：`{manifest['as_of_date']}`
- run_id：`{manifest['run_id']}`
- 状态：**{manifest['status']}**
- 输出类型：`{manifest['output_type']}`
- 价格口径：前复权 `qfq`；成交量为股、成交额为人民币元、换手率为小数。
- 数据边界：所有价格和基本面记录均在计算前按显式截止日期过滤。

## 指标定义

- 活跃度：120 个有效交易日内成交量、成交额和换手率横截面分位数的配置化加权分数。
- 成交量突破：观察日成交量相对此前 20 个交易日均值、中位数及总体标准差；观察日不进入基线。
- 区间震荡：40 日高低区间、相对宽度、log 收盘价归一化斜率、R² 和内部分位区间外比例联合判断。
- 基本面与价量：只使用可用日期不晚于截止日的财务子分数，并与活跃度、突破、区间和近期动量透明加权。
- 缺失子分数：不填零；按可用权重重新归一化，并保存完整度。

## 结果与质量

- 输入行数：`{manifest['input_row_counts']}`
- 输出行数：`{manifest['output_row_counts']}`
- 规范化结果 SHA-256：`{manifest['canonical_sha256']}`
- 阻塞项：
{blockers}
- 警告：
{warnings}

## 无未来数据保证

价格仅使用 `trade_date <= as_of_date`；基本面仅使用公告日或可用日不晚于截止日的记录。
未来记录数量单独审计，不参与排名、阈值、历史基线、区间或综合评分。

## 测试与 Git 证据

运行时分析不会伪造测试通过结论。真实专项测试、完整回归、稳定导出复跑、事务故障注入、
冻结文件哈希和 `stage11-complete` 祖先检查记录在 `docs/stage12_acceptance.md`。

## 已知限制与复现

- 组合分数是描述性、可解释的研究指标，不是交易信号或投资建议。
- 缺少可靠基本面可用日期时拒绝输入，不使用报告期替代公告日期。
- 复现需使用相同输入、`config/stage12.yml`、截止日期和 run_id 调用 `analyze-stage12`。
- 本项目仅用于研究和数据能力测试，不构成投资建议。
"""


def _write_reports(reports_dir: Path, *, frames: dict[str, pd.DataFrame], quality: pd.DataFrame,
                   manifest: dict[str, Any], encoding: str, precision: int) -> None:
    reports_dir.mkdir(parents=True, exist_ok=True)
    mapping = {
        "active": "stage12_active_stocks.csv",
        "breakouts": "stage12_volume_breakouts.csv",
        "ranges": "stage12_range_bound.csv",
        "combined": "stage12_fundamental_price_volume.csv",
    }
    for name, filename in mapping.items():
        _csv_frame(frames[name]).to_csv(
            reports_dir / filename, index=False, encoding=encoding,
            float_format=f"%.{precision}g", lineterminator="\n",
        )
    quality.to_csv(reports_dir / "stage12_quality.csv", index=False, encoding=encoding, lineterminator="\n")
    (reports_dir / "stage12_run.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    (reports_dir / "stage12_analysis.md").write_text(render_stage12_report(manifest), encoding="utf-8")


def analyze_stage12(
    *, root: Path, as_of_date: pd.Timestamp, price_frame: pd.DataFrame,
    fundamental_frame: pd.DataFrame | None, config_path: Path,
    output_database: Path, run_id: str | None = None, dry_run: bool = False,
    reports_dir: Path | None = None, output_type: str = "analysis_data",
) -> tuple[dict[str, Any], int]:
    """Run all Stage 12 analyses without network or global mutable state."""
    cutoff = pd.Timestamp(as_of_date).normalize()
    if pd.isna(cutoff):
        raise ValueError("Stage 12 as_of_date is invalid")
    effective_run_id = str(run_id or uuid.uuid4()).strip()
    if not effective_run_id:
        raise ValueError("Stage 12 run_id cannot be empty")
    config = load_stage12_config(config_path)
    visible_prices, future_price_rows = normalize_price_frame(price_frame, as_of_date=cutoff)
    if visible_prices.empty:
        raise ValueError("Stage 12 has no visible price rows at or before as_of_date")
    try:
        visible_fundamentals, future_fundamental_rows = _visible_fundamentals(
            fundamental_frame, cutoff
        )
    except ValueError as exc:
        return _blocked_fundamental_manifest(
            run_id=effective_run_id, cutoff=cutoff, config=config,
            visible_price_rows=len(visible_prices), future_price_rows=future_price_rows,
            reason=str(exc), dry_run=dry_run, output_type=output_type,
        ), 2
    active_config = {**config.raw["active_stock"], "ranking_method": config.raw["ranking_method"]}
    active = analyze_active_stocks(visible_prices, as_of_date=cutoff, config=active_config)
    breakouts = analyze_volume_breakouts(
        visible_prices, as_of_date=cutoff, config=config.raw["volume_breakout"]
    )
    ranges = analyze_range_bound(visible_prices, as_of_date=cutoff, config=config.raw["range_bound"])
    combined = analyze_fundamental_price_volume(
        visible_fundamentals, as_of_date=cutoff, active=active, breakouts=breakouts,
        ranges=ranges, prices=visible_prices, config=config.raw["fundamental_price_volume"],
    )
    deterministic_time = cutoff.tz_localize("UTC")
    instruments = sorted(visible_prices["instrument"].astype(str).unique())
    quality = run_stage12_quality_checks(
        run_id=effective_run_id, prices=visible_prices,
        future_price_rows=future_price_rows, future_fundamental_rows=future_fundamental_rows,
        active=active, breakouts=breakouts, ranges=ranges, combined=combined,
        expected_instruments=instruments, checked_at=deterministic_time,
    )
    blockers = sorted(quality.loc[
        quality["severity"].eq("ERROR") & quality["status"].eq("FAIL"), "check_name"
    ].astype(str))
    warnings: list[str] = []
    if future_price_rows:
        warnings.append(f"future_price_rows_excluded:{future_price_rows}")
    if future_fundamental_rows:
        warnings.append(f"future_fundamental_rows_excluded:{future_fundamental_rows}")
    if visible_fundamentals is None or visible_fundamentals.empty:
        warnings.append("fundamental_input_unavailable")
    precision = int(config.raw["output"]["float_precision"])
    frames = {"active": active, "breakouts": breakouts, "ranges": ranges, "combined": combined}
    output_hashes = {
        name: canonical_frame_hash(frame, sort_by=["instrument", "as_of_date"], precision=precision)
        for name, frame in frames.items()
    }
    price_hash = canonical_frame_hash(
        visible_prices, sort_by=["instrument", "trade_date", "adjust_type"], precision=precision
    )
    if visible_fundamentals is None:
        fundamental_hash = hashlib.sha256(b"null").hexdigest()
    else:
        fundamental_date = next(
            name for name in ("available_date", "announcement_date", "fundamental_as_of_date")
            if name in visible_fundamentals
        )
        fundamental_hash = canonical_frame_hash(
            visible_fundamentals, sort_by=["instrument", fundamental_date], precision=precision
        )
    input_sha = _combined_hash({"price": price_hash, "fundamental": fundamental_hash})
    canonical_sha = _combined_hash(output_hashes)
    status = "READY" if not blockers else "BLOCKED"
    manifest: dict[str, Any] = {
        "stage": 12, "run_id": effective_run_id, "status": status,
        "as_of_date": cutoff.date().isoformat(),
        "started_at": deterministic_time.isoformat(), "completed_at": deterministic_time.isoformat(),
        "input_row_counts": {
            "price_visible": len(visible_prices), "price_future_excluded": future_price_rows,
            "fundamental_visible": 0 if visible_fundamentals is None else len(visible_fundamentals),
            "fundamental_future_excluded": future_fundamental_rows,
        },
        "output_row_counts": {name: len(frame) for name, frame in frames.items()} | {"quality": len(quality)},
        "blocking_reasons": blockers, "warnings": sorted(warnings),
        "config_sha256": config.sha256, "input_sha256": input_sha,
        "canonical_sha256": canonical_sha, "output_hashes": output_hashes,
        "database_write_status": "not_written_dry_run" if dry_run else "written",
        "dry_run": bool(dry_run), "model_version": config.model_version,
        "network_calls": 0, "price_adjust_type": config.raw["price_adjust_type"],
        "output_type": str(output_type),
    }
    if dry_run:
        return manifest, 0 if status == "READY" else 2
    target_reports = reports_dir or root / "reports"
    write_stage12_run(
        output_database, schema_path=root / "sql/stage12_schema.sql", run_id=effective_run_id,
        frames=frames, quality=quality, manifest=manifest, created_at=deterministic_time,
    )
    _write_reports(
        target_reports, frames=frames, quality=quality, manifest=manifest,
        encoding=config.raw["output"]["csv_encoding"], precision=precision,
    )
    return manifest, 0 if status == "READY" else 2
