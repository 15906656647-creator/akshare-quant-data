"""Stage 17 multi-market Raw collection, quality checks, and audit reports."""
from __future__ import annotations

import csv
import hashlib
import json
import queue
import re
import threading
import time
import uuid
from dataclasses import asdict
from datetime import date, datetime, time as clock_time, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .adapters.hk_market import HkMarketAdapter, hk_source_symbol
from .adapters.hk_provider_registry import HkProviderRegistry
from .adapters.hk_tencent_adapter import HkTencentAdapter
from .adapters.hk_tencent_direct import HkTencentDirectAdapter
from .adapters.stage17_a_market import Stage17AShareAdapter, a_sina_symbol
from .adapters.stage17_crypto import Stage17OkxAdapter
from .adapters.stock_market import MarketCall
from .paths import project_root
from .stage17_config import EquityTarget, Stage17Config, load_stage17_config
from .storage.raw_store import file_sha256
from .storage.stage17_raw_store import Stage17RawStore


DAILY_REQUIRED = {
    "date": ("日期", "date", "trade_date"),
    "open": ("开盘", "open"),
    "high": ("最高", "high"),
    "low": ("最低", "low"),
    "close": ("收盘", "close"),
    "volume": ("成交量", "volume"),
}
INTERVAL_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "1h": 3600,
    "1d": 86400,
}
DATE_PATTERN = re.compile(r"(?<!\d)(20\d{2}|19\d{2})[-/.年]?(\d{1,2})[-/.月]?(\d{1,2})(?:日)?(?!\d)")


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Stage 17 report already exists: {path}")
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"Stage 17 report already exists: {path}")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _resolve_columns(frame: pd.DataFrame) -> tuple[dict[str, str], list[str]]:
    columns = {str(column).strip().casefold(): str(column) for column in frame.columns}
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for field, candidates in DAILY_REQUIRED.items():
        found = next((columns[item.casefold()] for item in candidates if item.casefold() in columns), None)
        if found is None:
            missing.append(field)
        else:
            resolved[field] = found
    return resolved, missing


def validate_equity_daily(frame: pd.DataFrame) -> dict[str, Any]:
    resolved, missing = _resolve_columns(frame)
    errors: list[str] = []
    if missing:
        return {
            "status": "FAIL", "errors": [f"missing_columns:{','.join(missing)}"],
            "min_date": None, "max_date": None,
        }
    dates = pd.to_datetime(frame[resolved["date"]], errors="coerce")
    if dates.isna().any():
        errors.append("invalid_trade_date")
    if dates.duplicated().any():
        errors.append("duplicate_trade_date")
    if not dates.is_monotonic_increasing:
        errors.append("trade_date_not_increasing")
    numeric = {
        name: pd.to_numeric(frame[column], errors="coerce")
        for name, column in resolved.items() if name != "date"
    }
    if any(series.isna().any() for series in numeric.values()):
        errors.append("nonnumeric_ohlcv")
    if "volume" in numeric and (numeric["volume"] < 0).any():
        errors.append("negative_volume")
    if all(name in numeric for name in ("open", "high", "low", "close")):
        upper = pd.concat([numeric["open"], numeric["close"], numeric["low"]], axis=1).max(axis=1)
        lower = pd.concat([numeric["open"], numeric["close"], numeric["high"]], axis=1).min(axis=1)
        if (numeric["high"] < upper).any() or (numeric["low"] > lower).any():
            errors.append("ohlc_logic_error")
    valid_dates = dates.dropna()
    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "min_date": valid_dates.min().date().isoformat() if not valid_dates.empty else None,
        "max_date": valid_dates.max().date().isoformat() if not valid_dates.empty else None,
    }


def extract_listing_date(frame: pd.DataFrame) -> date | None:
    """Extract an explicitly labelled listing date from heterogeneous profiles."""
    for column in frame.columns:
        label = str(column).strip()
        if "上市" not in label or not any(token in label for token in ("日期", "时间", "日")):
            continue
        for value in frame[column].astype("string").fillna(""):
            match = DATE_PATTERN.search(str(value).strip())
            if match:
                try:
                    return date(
                        int(match.group(1)), int(match.group(2)), int(match.group(3))
                    )
                except ValueError:
                    continue
    for row in frame.astype("string").fillna("").itertuples(index=False, name=None):
        values = [str(value).strip() for value in row]
        for index, value in enumerate(values):
            explicit_label = value.replace("：", ":").rstrip(":").strip()
            if explicit_label not in {"上市日期", "上市时间", "上市日"}:
                continue
            candidates = values[index + 1:] + [value]
            for candidate in candidates:
                match = DATE_PATTERN.search(candidate)
                if match:
                    try:
                        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
                    except ValueError:
                        continue
    return None


def listing_coverage_status(listing: date | None, earliest: str | None) -> str:
    if listing is None:
        return "listing_date_unavailable"
    if earliest is None:
        return "history_unavailable"
    first = date.fromisoformat(earliest)
    if first > listing + timedelta(days=10):
        return "provider_history_shorter_than_listing"
    return "complete_to_verified_listing_date"


def validate_crypto(frame: pd.DataFrame, interval: str) -> dict[str, Any]:
    required = {
        "raw_instrument", "data_provider", "raw_exchange", "instrument_type",
        "bar_interval", "confirmed", "trade_time", "open", "high", "low",
        "close", "volume", "quote_volume",
    }
    errors: list[str] = []
    missing = sorted(required - set(frame.columns))
    if missing:
        return {"status": "FAIL", "errors": [f"missing_columns:{','.join(missing)}"]}
    times = pd.to_datetime(frame.trade_time, errors="coerce", utc=True)
    if times.isna().any():
        errors.append("invalid_trade_time")
    if times.duplicated().any():
        errors.append("duplicate_trade_time")
    if not times.is_monotonic_increasing:
        errors.append("trade_time_not_increasing")
    if not frame.raw_instrument.astype(str).eq("ETH-USDT").all():
        errors.append("instrument_identity_mismatch")
    if not frame.data_provider.astype(str).eq("okx_public_api").all():
        errors.append("provider_identity_mismatch")
    if not frame.bar_interval.astype(str).eq(interval).all():
        errors.append("interval_identity_mismatch")
    if not frame.confirmed.astype(bool).all():
        errors.append("unconfirmed_candle")
    numeric = {
        name: pd.to_numeric(frame[name], errors="coerce")
        for name in ("open", "high", "low", "close", "volume", "quote_volume")
    }
    if any(series.isna().any() for series in numeric.values()):
        errors.append("nonnumeric_ohlcv")
    if (numeric["volume"] < 0).any() or (numeric["quote_volume"] < 0).any():
        errors.append("negative_volume")
    upper = pd.concat([numeric["open"], numeric["close"], numeric["low"]], axis=1).max(axis=1)
    lower = pd.concat([numeric["open"], numeric["close"], numeric["high"]], axis=1).min(axis=1)
    if (numeric["high"] < upper).any() or (numeric["low"] > lower).any():
        errors.append("ohlc_logic_error")
    diffs = times.dropna().sort_values().diff().dropna().dt.total_seconds()
    if not diffs.empty and not diffs.eq(INTERVAL_SECONDS[interval]).all():
        errors.append("time_continuity_gap")
    return {
        "status": "PASS" if not errors else "FAIL", "errors": errors,
        "min_time": times.min().isoformat() if not times.empty else None,
        "max_time": times.max().isoformat() if not times.empty else None,
    }


def _bounded_minute_fetch(
    adapter: Any, *, hard_timeout_seconds: float, **parameters: Any,
) -> MarketCall:
    """Bound AKShare minute probes even when an upstream call ignores HTTP timeout."""
    results: queue.Queue[Any] = queue.Queue(maxsize=1)

    def invoke() -> None:
        try:
            results.put(adapter.fetch_minutes(**parameters))
        except BaseException as exc:  # adapter boundary normalizes heterogeneous failures
            results.put(exc)

    worker = threading.Thread(target=invoke, daemon=True)
    worker.start()
    worker.join(max(0.1, hard_timeout_seconds))
    if worker.is_alive():
        return MarketCall(
            None, 1, "failed", "timeout",
            f"minute probe exceeded outer hard timeout {hard_timeout_seconds:.1f}s",
        )
    result = results.get_nowait()
    if isinstance(result, BaseException):
        return MarketCall(None, 1, "failed", type(result).__name__, str(result)[:500])
    if not isinstance(result, MarketCall):
        return MarketCall(None, 1, "failed", "unexpected_return_type", type(result).__name__)
    return result


def _should_disable_minute_network(call: MarketCall) -> bool:
    return call.status != "success" and call.error_type in {"timeout", "connection_error"}


def build_collection_plan(config: Stage17Config, as_of_date: date) -> dict[str, Any]:
    return {
        "stage": 17,
        "as_of_date": as_of_date.isoformat(),
        "daily_expected_count": config.daily_expected_count,
        "profile_expected_count": len(config.equities),
        "minute_probe_expected_count": len(config.minute_samples) * len(config.minute_direct_intervals),
        "crypto_expected_count": len(config.crypto_intervals),
        "a_share_count": sum(target.market == "A" for target in config.equities),
        "h_share_count": sum(target.market == "HK" for target in config.equities),
        "adjustments": list(config.adjustments),
        "crypto_intervals": list(config.crypto_intervals),
        "network_required": True,
        "writes_raw": True,
        "stage18_started": False,
    }


def _metadata(
    *, run_id: str, dataset_id: str, target: EquityTarget | None,
    provider: str, interface: str, parameters: dict[str, Any], fetched_at: datetime,
    quality: dict[str, Any], adjust: str | None = None, interval: str | None = None,
    audit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "stage": 17, "run_id": run_id, "dataset_id": dataset_id,
        "provider": provider, "interface": interface, "request_parameters": parameters,
        "symbol": target.symbol if target else "ETHUSDT",
        "source_symbol": target.source_symbol if target else "ETH-USDT",
        "market": target.market if target else "crypto",
        "exchange": target.exchange if target else "OKX",
        "currency": target.currency if target else "USDT",
        "timezone": target.timezone if target else "UTC",
        "adjust": adjust, "interval": interval, "fetched_at": fetched_at.isoformat(),
        "quality_status": quality.get("status"), "quality_errors": quality.get("errors", []),
        "actual_min": quality.get("min_date") or quality.get("min_time"),
        "actual_max": quality.get("max_date") or quality.get("max_time"),
    }
    metadata.update(audit or {})
    return metadata


def _record_failure(
    dataset_id: str, kind: str, symbol: str, status: str, error_type: str,
    error_message: str, *, market: str, adjust: str | None = None,
    interval: str | None = None, source: str | None = None,
    interface: str | None = None, attempt_count: int = 0,
    selected_source: str | None = None, selection_reason: str = "",
    trigger_reason: str = "", blocker_category: str = "",
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id, "kind": kind, "symbol": symbol,
        "market": market, "adjust": adjust, "interval": interval,
        "status": status, "quality_status": "NOT_RUN", "row_count": 0,
        "min_value": None, "max_value": None, "listing_date": None,
        "coverage_status": None, "error_type": error_type,
        "error_message": error_message, "data_path": None, "metadata_path": None,
        "source": source, "interface": interface, "attempt_count": attempt_count,
        "selected_source": selected_source, "selection_reason": selection_reason,
        "trigger_reason": trigger_reason, "blocker_category": blocker_category,
    }


def _success_record(
    *, dataset_id: str, kind: str, symbol: str, market: str,
    stored: dict[str, Any], quality: dict[str, Any], root: Path,
    adjust: str | None = None, interval: str | None = None,
    source: str | None = None, interface: str | None = None,
    attempt_count: int = 0, selected_source: str | None = None,
    selection_reason: str = "", trigger_reason: str = "",
    blocker_category: str = "",
) -> dict[str, Any]:
    return {
        "dataset_id": dataset_id, "kind": kind, "symbol": symbol,
        "market": market, "adjust": adjust, "interval": interval,
        "status": "success", "quality_status": quality["status"],
        "row_count": stored["row_count"],
        "min_value": quality.get("min_date") or quality.get("min_time"),
        "max_value": quality.get("max_date") or quality.get("max_time"),
        "listing_date": None, "coverage_status": None, "error_type": "",
        "error_message": ";".join(quality.get("errors", [])),
        "data_path": _relative(stored["data_path"], root),
        "metadata_path": _relative(stored["metadata_path"], root),
        "data_sha256": stored["data_sha256"],
        "metadata_sha256": file_sha256(stored["metadata_path"]),
        "source": source, "interface": interface, "attempt_count": attempt_count,
        "selected_source": selected_source, "selection_reason": selection_reason,
        "trigger_reason": trigger_reason, "blocker_category": blocker_category,
    }


def _quality_trigger(call: Any, quality: dict[str, Any] | None) -> str:
    if call.status != "success":
        return call.error_type or call.status
    if quality and quality.get("status") != "PASS":
        return str((quality.get("errors") or ["dataset_quality_failure"])[0])
    return ""


def _blocker_category(status: str, error_type: str, trigger: str) -> str:
    value = error_type or trigger
    if value in {"connection_error", "timeout", "rate_limit"}:
        return "connection_failure"
    if value == "empty_result":
        return "empty_result"
    if value == "ohlc_logic_error":
        return "upstream_ohlc_inconsistency"
    if status == "success":
        return "dataset_quality_failure"
    return "source_candidate_failure"


def _daily_parameters(
    target: EquityTarget, *, role: str, start_date: str, end_date: str,
    adjust: str, timeout: float,
) -> dict[str, Any]:
    if role == "primary":
        parameters = {
            "symbol": target.source_symbol, "period": "daily",
            "start_date": start_date, "end_date": end_date, "adjust": adjust,
        }
        if target.market == "A":
            parameters["timeout"] = timeout
        return parameters
    if target.market == "A":
        return {
            "symbol": a_sina_symbol(target.symbol), "start_date": start_date,
            "end_date": end_date, "adjust": adjust,
        }
    return {
        "symbol": hk_source_symbol(target.symbol), "adjust": adjust,
        "client_side_start_date": start_date, "client_side_end_date": end_date,
    }


def _collect_equity_daily_dataset(
    *, config: Stage17Config, target: EquityTarget, adapter: Any,
    store: Stage17RawStore, root: Path, run_id: str, fetched_at: datetime,
    listing_date: date | None, start_date: str, end_date: str, adjust: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    market_key = "a_share" if target.market == "A" else "h_share"
    policy = config.provider_policy[market_key]
    dataset_id = f"daily:{target.symbol}:{adjust}"
    source_adjust = "" if adjust == "raw" else adjust
    candidates: list[dict[str, Any]] = []

    primary_call = adapter.fetch_history(
        symbol=target.symbol, start_date=start_date,
        end_date=end_date, adjust=source_adjust,
    )
    primary_quality = (
        validate_equity_daily(primary_call.dataframe)
        if primary_call.status == "success" and primary_call.dataframe is not None
        else None
    )
    primary_trigger = _quality_trigger(primary_call, primary_quality)
    candidates.append({
        "role": "primary", "policy": policy["primary"], "call": primary_call,
        "quality": primary_quality, "trigger": primary_trigger,
    })

    if primary_trigger in policy["fallback_on"] and hasattr(adapter, "fetch_history_fallback"):
        fallback_call = adapter.fetch_history_fallback(
            symbol=target.symbol, start_date=start_date,
            end_date=end_date, adjust=source_adjust,
        )
        fallback_quality = (
            validate_equity_daily(fallback_call.dataframe)
            if fallback_call.status == "success" and fallback_call.dataframe is not None
            else None
        )
        candidates.append({
            "role": "fallback", "policy": policy["fallback"], "call": fallback_call,
            "quality": fallback_quality,
            "trigger": _quality_trigger(fallback_call, fallback_quality),
        })

    selected: dict[str, Any] | None = None
    if primary_quality and primary_quality["status"] == "PASS":
        selected = candidates[0]
        selection_reason = "primary_passed"
    else:
        fallback = next((item for item in candidates if item["role"] == "fallback"), None)
        fallback_coverage = (
            listing_coverage_status(listing_date, fallback["quality"].get("min_date"))
            if fallback and fallback["quality"] else None
        )
        if (
            fallback and fallback["quality"]
            and fallback["quality"]["status"] == "PASS"
            and fallback_coverage == "complete_to_verified_listing_date"
        ):
            selected = fallback
            selection_reason = f"primary_{primary_trigger};fallback_passed_strict_checks"
        else:
            selection_reason = "no_source_passed_strict_checks"

    attempt_chain = []
    for item in candidates:
        call = item["call"]
        quality = item["quality"]
        attempt_chain.append({
            "role": item["role"], "source": item["policy"]["source"],
            "interface": item["policy"]["interface"], "status": call.status,
            "attempt_count": call.attempt_count, "error_type": call.error_type,
            "error_message": call.error_message,
            "quality_status": quality.get("status") if quality else "NOT_RUN",
            "quality_errors": quality.get("errors", []) if quality else [],
        })

    audit_rows: list[dict[str, Any]] = []
    formal_row: dict[str, Any] | None = None
    for item in candidates:
        source = item["policy"]["source"]
        interface = item["policy"]["interface"]
        call = item["call"]
        quality = item["quality"]
        is_selected = item is selected
        coverage = listing_coverage_status(
            listing_date, quality.get("min_date") if quality else None
        )
        category = _blocker_category(call.status, call.error_type, item["trigger"])
        if call.status == "success" and call.dataframe is not None and quality is not None:
            raw_dataset_id = dataset_id if is_selected else f"{dataset_id}:candidate:{source}"
            directory = store.dataset_dir(
                dataset="equity_daily", run_id=run_id, market=target.market,
                symbol=target.symbol, adjust=adjust, source=source,
            )
            stored = store.write_dataset(call.dataframe, directory, _metadata(
                run_id=run_id, dataset_id=raw_dataset_id, target=target,
                provider="AKShare", interface=interface,
                parameters=_daily_parameters(
                    target, role=item["role"], start_date=start_date,
                    end_date=end_date, adjust=source_adjust,
                    timeout=config.request_timeout_seconds,
                ),
                fetched_at=fetched_at, quality=quality, adjust=adjust,
                audit={
                    "source": source, "source_role": item["role"],
                    "selected_for_formal_dataset": is_selected,
                    "selection_reason": selection_reason,
                    "trigger_reason": primary_trigger if item["role"] == "fallback" else "",
                    "attempt_count": call.attempt_count, "attempt_chain": attempt_chain,
                },
            ))
            row = _success_record(
                dataset_id=raw_dataset_id,
                kind="equity_daily" if is_selected else "equity_daily_candidate",
                symbol=target.symbol, market=target.market, stored=stored,
                quality=quality, root=root, adjust=adjust, source=source,
                interface=interface, attempt_count=call.attempt_count,
                selected_source=source if is_selected else None,
                selection_reason=selection_reason,
                trigger_reason=primary_trigger if item["role"] == "fallback" else "",
                blocker_category="" if quality["status"] == "PASS" else category,
            )
            row["listing_date"] = listing_date.isoformat() if listing_date else None
            row["coverage_status"] = coverage
            if is_selected:
                formal_row = row
            else:
                audit_rows.append(row)
        else:
            row = _record_failure(
                f"{dataset_id}:attempt:{source}", "equity_daily_attempt",
                target.symbol, call.status, call.error_type, call.error_message,
                market=target.market, adjust=adjust, source=source,
                interface=interface, attempt_count=call.attempt_count,
                selection_reason=selection_reason,
                trigger_reason=primary_trigger if item["role"] == "fallback" else "",
                blocker_category=category,
            )
            row["listing_date"] = listing_date.isoformat() if listing_date else None
            row["coverage_status"] = coverage
            audit_rows.append(row)

    if formal_row is None:
        detail = " | ".join(
            f"{item['policy']['source']}:{item['trigger'] or item['call'].status}"
            for item in candidates
        )
        candidate_categories = {
            _blocker_category(
                item["call"].status, item["call"].error_type, item["trigger"]
            ) for item in candidates
        }
        formal_category = (
            next(iter(candidate_categories))
            if len(candidate_categories) == 1 else "source_candidate_failure"
        )
        formal_row = _record_failure(
            dataset_id, "equity_daily", target.symbol, "failed",
            "all_sources_unusable", detail, market=target.market, adjust=adjust,
            selection_reason=selection_reason, trigger_reason=primary_trigger,
            blocker_category=formal_category,
        )
        if any(item["quality"] is not None for item in candidates):
            formal_row["quality_status"] = "FAIL"
        formal_row["listing_date"] = listing_date.isoformat() if listing_date else None
        formal_row["coverage_status"] = "history_unavailable"
    return formal_row, audit_rows


def _collect_hk_registry_daily_dataset(
    *, config: Stage17Config, target: EquityTarget, registry: HkProviderRegistry,
    store: Stage17RawStore, root: Path, run_id: str, fetched_at: datetime,
    listing_date: date | None, as_of_date: date, adjust: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    dataset_id = f"daily:{target.symbol}:{adjust}"
    selection = registry.select_history(
        symbol=target.symbol, listing_date=listing_date, as_of_date=as_of_date,
        adjust=adjust, quality_validator=validate_equity_daily,
        coverage_validator=listing_coverage_status,
    )
    attempt_chain = []
    for attempt in selection.attempts:
        call = attempt.call
        attempt_chain.append({
            "provider": attempt.provider, "interface": attempt.interface,
            "status": call.status, "attempt_count": call.attempt_count,
            "error_type": call.error_type, "error_message": call.error_message,
            "quality_result": attempt.quality,
            "coverage_result": attempt.coverage_status,
            "rejection_reason": attempt.rejection_reason,
            "selected": attempt is selection.selected,
        })
    audit_rows: list[dict[str, Any]] = []
    formal_row: dict[str, Any] | None = None
    for attempt in selection.attempts:
        call = attempt.call
        quality = attempt.quality
        selected = attempt is selection.selected
        blocks = list(getattr(call, "blocks", ()))
        compatibility = {
            "requested_response_keys": [block.requested_key for block in blocks],
            "used_response_keys": [block.used_key for block in blocks],
            "response_field_fallback": any(block.field_fallback for block in blocks),
            "response_field_fallback_reason": (
                "AKShare 1.18.80 expects qfqday/hfqday; Tencent returned day"
                if any(block.field_fallback for block in blocks) else ""
            ),
            "duplicate_rows_removed": getattr(call, "duplicate_rows_removed", 0),
        }
        if call.status == "success" and call.dataframe is not None and quality is not None:
            raw_dataset_id = dataset_id if selected else f"{dataset_id}:candidate:{attempt.provider}"
            directory = store.dataset_dir(
                dataset="equity_daily", run_id=run_id, market="HK",
                symbol=target.symbol, adjust=adjust, source=attempt.provider,
            )
            stored = store.write_dataset(call.dataframe, directory, _metadata(
                run_id=run_id, dataset_id=raw_dataset_id, target=target,
                provider=attempt.provider, interface=attempt.interface,
                parameters={
                    "symbol": target.source_symbol,
                    "listing_date": listing_date.isoformat() if listing_date else None,
                    "end_date": as_of_date.isoformat(), "adjust": adjust,
                    "configured_route": list(config.hk_provider_routes[target.symbol][adjust]),
                }, fetched_at=fetched_at, quality=quality, adjust=adjust,
                audit={
                    "source": attempt.provider,
                    "selected_for_formal_dataset": selected,
                    "selected_provider": selection.selected.provider if selection.selected else None,
                    "selected_interface": selection.selected.interface if selection.selected else None,
                    "selection_reason": selection.selection_reason,
                    "provider_attempts": attempt_chain,
                    "coverage_result": attempt.coverage_status,
                    "provider_adjust_semantics": (
                        f"Provider endpoint explicitly requested {adjust}"
                        if adjust != "raw" else "Provider raw daily request"
                    ), **compatibility,
                },
            ))
            row = _success_record(
                dataset_id=raw_dataset_id,
                kind="equity_daily" if selected else "equity_daily_candidate",
                symbol=target.symbol, market="HK", stored=stored, quality=quality,
                root=root, adjust=adjust, source=attempt.provider,
                interface=attempt.interface, attempt_count=call.attempt_count,
                selected_source=attempt.provider if selected else None,
                selection_reason=selection.selection_reason,
                blocker_category=("" if quality["status"] == "PASS" else
                                  _blocker_category(call.status, call.error_type,
                                                    attempt.rejection_reason)),
            )
            row.update({
                "listing_date": listing_date.isoformat() if listing_date else None,
                "coverage_status": attempt.coverage_status,
                "provider_attempts": attempt_chain,
                "selected_provider": selection.selected.provider if selection.selected else None,
                "selected_interface": selection.selected.interface if selection.selected else None,
                "quality_result": quality, "coverage_result": attempt.coverage_status,
                **compatibility,
            })
            if selected:
                formal_row = row
            else:
                audit_rows.append(row)
        else:
            row = _record_failure(
                f"{dataset_id}:attempt:{attempt.provider}", "equity_daily_attempt",
                target.symbol, call.status, call.error_type, call.error_message,
                market="HK", adjust=adjust, source=attempt.provider,
                interface=attempt.interface, attempt_count=call.attempt_count,
                selection_reason=selection.selection_reason,
                blocker_category=_blocker_category(
                    call.status, call.error_type, attempt.rejection_reason,
                ),
            )
            row.update({
                "listing_date": listing_date.isoformat() if listing_date else None,
                "coverage_status": attempt.coverage_status,
                "provider_attempts": attempt_chain,
                "selected_provider": selection.selected.provider if selection.selected else None,
                "selected_interface": selection.selected.interface if selection.selected else None,
                "quality_result": quality, "coverage_result": attempt.coverage_status,
                **compatibility,
            })
            audit_rows.append(row)
    if formal_row is None:
        detail = " | ".join(
            f"{attempt.provider}:{attempt.rejection_reason}" for attempt in selection.attempts
        ) or selection.selection_reason
        formal_row = _record_failure(
            dataset_id, "equity_daily", target.symbol, "failed",
            "all_sources_unusable", detail, market="HK", adjust=adjust,
            selection_reason=selection.selection_reason,
            blocker_category="source_candidate_failure",
        )
        formal_row.update({
            "listing_date": listing_date.isoformat() if listing_date else None,
            "coverage_status": "history_unavailable",
            "provider_attempts": attempt_chain,
            "selected_provider": None, "selected_interface": None,
            "quality_result": None, "coverage_result": "history_unavailable",
        })
    return formal_row, audit_rows

def _write_reports(
    *, root: Path, report_dir: Path, run_id: str, as_of_date: date,
    config: Stage17Config, records: list[dict[str, Any]], status: str,
    blockers: list[str], blocker_details: list[dict[str, Any]],
    unavailable: list[str], started_at: datetime, finished_at: datetime,
) -> dict[str, Any]:
    if report_dir.exists():
        raise FileExistsError(f"Stage 17 report run directory already exists: {report_dir}")
    report_dir.mkdir(parents=True)
    raw_files: list[dict[str, Any]] = []
    for record in records:
        for key, role in (("data_path", "data"), ("metadata_path", "metadata")):
            value = record.get(key)
            if value:
                path = root / value
                raw_files.append({
                    "dataset_id": record["dataset_id"], "role": role, "path": value,
                    "size_bytes": path.stat().st_size, "sha256": file_sha256(path),
                })
    actual_raw = sorted(
        _relative(path, root)
        for path in (root / config.raw_root).rglob("*")
        if path.is_file() and f"run_id={run_id}" in path.parts
    )
    listed_raw = sorted(item["path"] for item in raw_files)
    closed_world = actual_raw == listed_raw
    if not closed_world:
        status = "BLOCKED"
        blockers = sorted(set(blockers + ["raw_manifest_closed_world_failed"]))
        blocker_details = blocker_details + [{
            "dataset_id": "stage17", "category": "manifest_integrity_failure",
            "status": "BLOCKED", "error_type": "raw_manifest_closed_world_failed",
            "detail": "Raw files differ from the closed manifest",
        }]
    manifest = {
        "stage": 17, "run_id": run_id, "as_of_date": as_of_date.isoformat(),
        "config_path": _relative(config.path, root),
        "config_sha256": file_sha256(config.path),
        "expected": build_collection_plan(config, as_of_date),
        "status": status, "blocked_risks": blockers,
        "blocker_details": blocker_details, "unavailable_items": unavailable,
        "raw_manifest_closed_world": closed_world,
        "raw_files": raw_files, "datasets": records,
    }
    _json(report_dir / "stage17_manifest.json", manifest)
    columns = [
        "dataset_id", "kind", "symbol", "market", "adjust", "interval",
        "status", "quality_status", "row_count", "min_value", "max_value",
        "listing_date", "coverage_status", "error_type", "error_message",
        "source", "interface", "attempt_count", "selected_source",
        "selection_reason", "trigger_reason", "blocker_category",
        "selected_provider", "selected_interface", "provider_attempts",
        "quality_result", "coverage_result", "requested_response_keys",
        "used_response_keys", "response_field_fallback", "qfq_hfq_identical",
        "data_path", "metadata_path",
    ]
    _csv(report_dir / "stage17_manifest.csv", records, columns)
    _csv(
        report_dir / "daily_coverage.csv",
        [row for row in records if row["kind"] == "equity_daily"], columns,
    )
    _csv(
        report_dir / "crypto_coverage.csv",
        [row for row in records if row["kind"] == "crypto"], columns,
    )
    quality_rows = [{
        "dataset_id": row["dataset_id"],
        "check_name": "dataset_quality",
        "status": row["quality_status"] if row["status"] == "success" else "FAIL",
        "detail": row["error_message"],
    } for row in records]
    quality_rows.append({
        "dataset_id": "stage17", "check_name": "raw_manifest_closed_world",
        "status": "PASS" if closed_world else "FAIL", "detail": "",
    })
    _csv(
        report_dir / "stage17_quality.csv", quality_rows,
        ["dataset_id", "check_name", "status", "detail"],
    )
    minute_rows = [row for row in records if row["kind"].startswith("equity_minute")]
    minute_lines = [
        "# Stage 17 分钟级数据可行性报告", "",
        f"- 运行批次：`{run_id}`", f"- 业务基准日：`{as_of_date}`",
        "- A/H股仅为代表性可行性验证，不构成正式全市场分钟数据资产。",
        "- AKShare无直接3分钟接口；3分钟仅可由1分钟数据在报告层演示聚合，未写入Raw。",
        "", "| 标的 | 市场 | 周期 | 状态 | 行数 | 限制/错误 |",
        "|---|---|---|---|---:|---|",
    ]
    for row in minute_rows:
        minute_lines.append(
            f"| {row['symbol']} | {row['market']} | {row['interval']} | "
            f"{row['status']} | {row['row_count']} | {row['error_message'] or '-'} |"
        )
    (report_dir / "minute_data_feasibility_report.md").write_text(
        "\n".join(minute_lines) + "\n", encoding="utf-8",
    )
    run_payload = {
        "stage": 17, "run_id": run_id, "status": status,
        "as_of_date": as_of_date.isoformat(), "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(), "blocked_risks": blockers,
        "blocker_details": blocker_details, "unavailable_items": unavailable,
        "counts": {
            "daily_expected": config.daily_expected_count,
            "daily_expected_count": config.daily_expected_count,
            "daily_success": sum(
                row["kind"] == "equity_daily" and row["status"] == "success"
                for row in records
            ),
            "daily_nonempty_count": sum(
                row["kind"] == "equity_daily" and row["status"] == "success"
                for row in records
            ),
            "daily_quality_pass_count": sum(
                row["kind"] == "equity_daily" and row["status"] == "success"
                and row["quality_status"] == "PASS" for row in records
            ),
            "daily_success_semantics": "compatibility_alias_of_daily_nonempty_count",
            "crypto_expected": len(config.crypto_intervals),
            "crypto_success": sum(row["kind"] == "crypto" and row["status"] == "success" for row in records),
            "minute_probe_expected": len(config.minute_samples) * len(config.minute_direct_intervals),
            "minute_probe_success": sum(row["kind"] == "equity_minute" and row["status"] == "success" for row in records),
        },
        "stage18_authorized": status == "PASS",
    }
    _json(report_dir / "stage17_run.json", run_payload)
    return run_payload


def run_stage17(
    *, config_path: str | Path, as_of_date: date, run_id: str | None = None,
    validate_only: bool = False, dry_run: bool = False,
    root: str | Path | None = None, a_adapter: Any | None = None,
    hk_adapter: Any | None = None, crypto_adapter: Any | None = None,
    now: Any | None = None, sleeper: Any = time.sleep,
) -> tuple[dict[str, Any], int]:
    repo = Path(root) if root is not None else project_root()
    config_file = Path(config_path)
    if not config_file.is_absolute():
        config_file = repo / config_file
    config = load_stage17_config(config_file)
    if as_of_date != config.as_of_date:
        raise ValueError(
            f"Stage 17 --as-of-date must equal configured {config.as_of_date.isoformat()}"
        )
    plan = build_collection_plan(config, as_of_date)
    if validate_only or dry_run:
        return {
            "status": "READY", "mode": "validate-only" if validate_only else "dry-run",
            "config": str(config_file), "plan": plan,
        }, 0

    actual_run_id = run_id or str(uuid.uuid4())
    uuid.UUID(actual_run_id)
    clock = now or (lambda: datetime.now(timezone.utc))
    started_at = clock()
    raw_root = config.raw_root if config.raw_root.is_absolute() else repo / config.raw_root
    reports_root = config.reports_root if config.reports_root.is_absolute() else repo / config.reports_root
    report_dir = reports_root / actual_run_id
    store = Stage17RawStore(raw_root)
    a_market = a_adapter or Stage17AShareAdapter(
        max_attempts=config.max_attempts,
        retry_delay_seconds=config.akshare_retry_delay_seconds,
        max_retry_delay_seconds=config.max_retry_delay_seconds,
        request_timeout_seconds=config.request_timeout_seconds,
        sleeper=sleeper,
    )
    if hk_adapter is not None:
        hk_market = hk_adapter
    else:
        hk_base = HkMarketAdapter(
            max_attempts=config.max_attempts,
            retry_delay_seconds=config.akshare_retry_delay_seconds,
            max_retry_delay_seconds=config.max_retry_delay_seconds,
            request_timeout_seconds=config.request_timeout_seconds, sleeper=sleeper,
        )
        hk_market = HkProviderRegistry(
            routes=config.hk_provider_routes, eastmoney=hk_base,
            tencent=HkTencentAdapter(
                max_attempts=config.max_attempts,
                retry_delay_seconds=config.akshare_retry_delay_seconds,
                max_retry_delay_seconds=config.max_retry_delay_seconds,
                request_timeout_seconds=config.request_timeout_seconds, sleeper=sleeper,
            ),
            tencent_compat=HkTencentDirectAdapter(
                max_attempts=config.max_attempts,
                retry_delay_seconds=config.akshare_retry_delay_seconds,
                max_retry_delay_seconds=config.max_retry_delay_seconds,
                request_timeout_seconds=config.request_timeout_seconds, sleeper=sleeper,
            ),
        )
    okx = crypto_adapter or Stage17OkxAdapter(
        max_attempts=config.max_attempts,
        retry_delay_seconds=config.akshare_retry_delay_seconds,
        inter_request_delay_seconds=config.inter_request_delay_seconds,
        sleeper=sleeper,
    )
    records: list[dict[str, Any]] = []
    listing_dates: dict[str, date | None] = {}
    end_compact = as_of_date.strftime("%Y%m%d")
    start_compact = config.equity_start_date.strftime("%Y%m%d")

    for target in config.equities:
        adapter = a_market if target.market == "A" else hk_market
        dataset_id = f"profile:{target.symbol}"
        call = adapter.fetch_profile(symbol=target.symbol)
        if call.status != "success" or call.dataframe is None:
            listing_dates[target.symbol] = None
            records.append(_record_failure(
                dataset_id, "equity_profile", target.symbol, call.status,
                call.error_type, call.error_message, market=target.market,
            ))
        else:
            listing = extract_listing_date(call.dataframe)
            listing_dates[target.symbol] = listing
            quality = {"status": "PASS" if listing else "UNAVAILABLE", "errors": [] if listing else ["listing_date_unavailable"]}
            directory = store.dataset_dir(
                dataset="equity_profile", run_id=actual_run_id,
                market=target.market, symbol=target.symbol,
            )
            stored = store.write_dataset(call.dataframe, directory, _metadata(
                run_id=actual_run_id, dataset_id=dataset_id, target=target,
                provider="AKShare", interface="stock_profile_cninfo" if target.market == "A" else "stock_hk_security_profile_em",
                parameters={"symbol": target.source_symbol}, fetched_at=started_at, quality=quality,
            ))
            row = _success_record(
                dataset_id=dataset_id, kind="equity_profile", symbol=target.symbol,
                market=target.market, stored=stored, quality=quality, root=repo,
            )
            row["listing_date"] = listing.isoformat() if listing else None
            records.append(row)
        sleeper(config.inter_request_delay_seconds)

    for target in config.equities:
        adapter = a_market if target.market == "A" else hk_market
        for adjust in config.adjustments:
            if target.market == "HK" and hasattr(adapter, "select_history"):
                formal_row, audit_rows = _collect_hk_registry_daily_dataset(
                    config=config, target=target, registry=adapter, store=store,
                    root=repo, run_id=actual_run_id, fetched_at=started_at,
                    listing_date=listing_dates[target.symbol], as_of_date=as_of_date,
                    adjust=adjust,
                )
            else:
                formal_row, audit_rows = _collect_equity_daily_dataset(
                    config=config, target=target, adapter=adapter, store=store,
                    root=repo, run_id=actual_run_id, fetched_at=started_at,
                    listing_date=listing_dates[target.symbol], start_date=start_compact,
                    end_date=end_compact, adjust=adjust,
                )
            records.extend(audit_rows)
            records.append(formal_row)
            sleeper(config.inter_request_delay_seconds)
    compat_rows = {
        row.get("adjust"): row for row in records
        if row.get("kind") == "equity_daily" and row.get("symbol") == "09669.HK"
    }
    qfq_row, hfq_row = compat_rows.get("qfq"), compat_rows.get("hfq")
    if qfq_row and hfq_row and qfq_row.get("data_path") and hfq_row.get("data_path"):
        qfq_frame = pd.read_parquet(repo / qfq_row["data_path"])
        hfq_frame = pd.read_parquet(repo / hfq_row["data_path"])
        identical = bool(qfq_frame.equals(hfq_frame))
        for row in (qfq_row, hfq_row):
            row["qfq_hfq_identical"] = identical
            row["qfq_hfq_identical_is_failure"] = False
    target_map = {target.symbol: target for target in config.equities}
    minute_end = datetime.combine(as_of_date, clock_time(23, 59, 59)).strftime("%Y-%m-%d %H:%M:%S")
    minute_start = datetime.combine(config.minute_start_date, clock_time.min).strftime("%Y-%m-%d %H:%M:%S")
    minute_network_disabled = False
    minute_hard_timeout = (
        config.request_timeout_seconds * config.max_attempts
        + config.max_retry_delay_seconds * 2 + 5.0
    )
    for symbol in config.minute_samples:
        target = target_map[symbol]
        adapter = a_market if target.market == "A" else hk_market
        for interval in config.minute_direct_intervals:
            dataset_id = f"minute:{symbol}:{interval}"
            if minute_network_disabled:
                call = MarketCall(
                    None, 0, "failed", "timeout",
                    "minute probe skipped after an earlier connection-class failure",
                )
            else:
                call = _bounded_minute_fetch(
                    adapter, hard_timeout_seconds=minute_hard_timeout,
                    symbol=symbol, start_date=minute_start, end_date=minute_end,
                    interval=interval,
                )
                if _should_disable_minute_network(call):
                    minute_network_disabled = True
            if call.status != "success" or call.dataframe is None:
                records.append(_record_failure(
                    dataset_id, "equity_minute", symbol, call.status,
                    call.error_type, call.error_message, market=target.market,
                    interval=interval,
                ))
            else:
                date_column = next((name for name in ("时间", "日期", "time", "datetime") if name in call.dataframe.columns), None)
                times = pd.to_datetime(call.dataframe[date_column], errors="coerce") if date_column else pd.Series(dtype="datetime64[ns]")
                quality = {
                    "status": "PASS" if date_column and not times.isna().any() and not times.duplicated().any() else "FAIL",
                    "errors": [] if date_column and not times.isna().any() and not times.duplicated().any() else ["minute_time_invalid_or_duplicate"],
                    "min_time": times.min().isoformat() if not times.empty and times.notna().any() else None,
                    "max_time": times.max().isoformat() if not times.empty and times.notna().any() else None,
                }
                directory = store.dataset_dir(
                    dataset="equity_minute_feasibility", run_id=actual_run_id,
                    market=target.market, symbol=symbol, interval=interval,
                )
                stored = store.write_dataset(call.dataframe, directory, _metadata(
                    run_id=actual_run_id, dataset_id=dataset_id, target=target,
                    provider="AKShare", interface="stock_zh_a_hist_min_em" if target.market == "A" else "stock_hk_hist_min_em",
                    parameters={
                        "symbol": target.source_symbol, "start_date": minute_start,
                        "end_date": minute_end, "period": interval[:-1], "adjust": "",
                    }, fetched_at=started_at, quality=quality, interval=interval,
                ))
                records.append(_success_record(
                    dataset_id=dataset_id, kind="equity_minute", symbol=symbol,
                    market=target.market, stored=stored, quality=quality, root=repo,
                    interval=interval,
                ))
                if interval == "1m":
                    derived_rows = int(times.dt.floor("3min").nunique()) if quality["status"] == "PASS" else 0
                    records.append({
                        "dataset_id": f"minute-derived:{symbol}:3m",
                        "kind": "equity_minute_derived_report", "symbol": symbol,
                        "market": target.market, "adjust": None, "interval": "3m",
                        "status": "report_only_derived",
                        "quality_status": quality["status"], "row_count": derived_rows,
                        "min_value": quality.get("min_time"),
                        "max_value": quality.get("max_time"), "listing_date": None,
                        "coverage_status": "derived_from_1m_not_raw",
                        "error_type": "", "error_message": (
                            "由1分钟样本按3分钟分桶演示聚合；未写入Raw，不代表上游直接支持"
                        ),
                        "data_path": None, "metadata_path": None,
                    })
            sleeper(config.inter_request_delay_seconds)

    crypto_end = datetime.combine(as_of_date + timedelta(days=1), clock_time.min, tzinfo=timezone.utc)
    for interval in config.crypto_intervals:
        start = (
            crypto_end - timedelta(days=config.crypto_minute_lookback_days)
            if interval in config.crypto_minute_intervals
            else datetime.combine(config.crypto_long_start_date, clock_time.min, tzinfo=timezone.utc)
        )
        dataset_id = f"crypto:ETHUSDT:{interval}"
        try:
            frame = okx.fetch(
                symbol="ETHUSDT", interval=interval, start_time=start,
                end_time=crypto_end, limit=config.okx_page_limit,
                timeout=config.request_timeout_seconds,
            )
            if frame.empty:
                records.append(_record_failure(
                    dataset_id, "crypto", "ETHUSDT", "empty", "empty_result",
                    "OKX returned no confirmed candles", market="crypto", interval=interval,
                ))
                continue
            quality = validate_crypto(frame, interval)
            directory = store.dataset_dir(
                dataset="crypto_ohlcv", run_id=actual_run_id, market="crypto",
                symbol="ETHUSDT", interval=interval,
            )
            stored = store.write_dataset(frame, directory, _metadata(
                run_id=actual_run_id, dataset_id=dataset_id, target=None,
                provider="okx_public_api", interface="history-candles",
                parameters={
                    "instId": "ETH-USDT", "bar_interval": interval,
                    "start_time": start.isoformat(), "end_time": crypto_end.isoformat(),
                    "confirmed_only": True,
                }, fetched_at=started_at, quality=quality, interval=interval,
            ))
            records.append(_success_record(
                dataset_id=dataset_id, kind="crypto", symbol="ETHUSDT",
                market="crypto", stored=stored, quality=quality, root=repo,
                interval=interval,
            ))
        except Exception as exc:
            records.append(_record_failure(
                dataset_id, "crypto", "ETHUSDT", "failed", type(exc).__name__,
                str(exc)[:500], market="crypto", interval=interval,
            ))

    formal = [row for row in records if row["kind"] in {"equity_daily", "crypto"}]
    failed_formal = [
        row for row in formal
        if row["status"] != "success" or row["quality_status"] != "PASS"
    ]
    blockers = sorted({
        f"{row['dataset_id']}:{row['status']}:{row['error_message']}"
        for row in failed_formal
    })
    blocker_details = [{
        "dataset_id": row["dataset_id"],
        "category": row.get("blocker_category") or _blocker_category(
            row["status"], row.get("error_type", ""), row.get("error_message", "")
        ),
        "status": row["status"], "quality_status": row["quality_status"],
        "error_type": row.get("error_type", ""),
        "detail": row.get("error_message", ""),
        "selected_source": row.get("selected_source"),
    } for row in failed_formal]
    unavailable = sorted({
        f"{row['symbol']}:{row.get('coverage_status') or row.get('error_message')}"
        for row in records
        if row["kind"] == "equity_profile" and row["quality_status"] != "PASS"
        or row["kind"] == "equity_daily" and row.get("coverage_status") != "complete_to_verified_listing_date"
    })
    if blockers:
        status = "BLOCKED"
    elif unavailable:
        status = "PASS_WITH_UNAVAILABLE_ITEMS"
    else:
        status = "PASS"
    run_payload = _write_reports(
        root=repo, report_dir=report_dir, run_id=actual_run_id,
        as_of_date=as_of_date, config=config, records=records, status=status,
        blockers=blockers, blocker_details=blocker_details,
        unavailable=unavailable, started_at=started_at, finished_at=clock(),
    )
    return run_payload, {"PASS": 0, "PASS_WITH_UNAVAILABLE_ITEMS": 2, "BLOCKED": 2}[run_payload["status"]]
