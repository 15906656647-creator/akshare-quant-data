"""Offline, raw-price-only Stage 8 event detection."""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

import pandas as pd

from .limit_rules import (
    LimitRule,
    RuleResolutionError,
    SecurityStatus,
    SecurityStatusResolutionError,
    calculate_limit_price,
    price_matches,
    resolve_limit_rule,
    resolve_security_status,
)


def validate_unadjusted_prices(frame: pd.DataFrame) -> None:
    """Fail closed unless every row is explicitly marked raw/unadjusted."""
    if "adjust_type" not in frame.columns:
        raise ValueError("Stage 8 input is missing required adjust_type")
    values = set(frame["adjust_type"].dropna().astype(str).str.lower())
    if frame["adjust_type"].isna().any() or values != {"raw"}:
        raise ValueError(
            "Stage 8 formal event detection requires adjust_type='raw'; "
            f"observed={sorted(values)}"
        )


def _decimal(value: object) -> Decimal | None:
    if pd.isna(value):
        return None
    return Decimal(str(value))


def _return(base: object, future: object) -> float | None:
    left, right = _decimal(base), _decimal(future)
    if left is None or right is None or left == 0:
        return None
    return float(right / left - Decimal("1"))


def _is_valid_trade_row(bar: pd.Series) -> bool:
    """Return whether a row belongs to the effective trading sequence."""
    if pd.isna(bar.get("trade_date")):
        return False
    prices = [_decimal(bar.get(name)) for name in ("open", "high", "low", "close")]
    if any(value is None or value <= 0 for value in prices):
        return False
    volume = _decimal(bar.get("volume_share"))
    if volume is None or volume <= 0:
        return False
    for field in ("is_suspended", "suspended", "non_trading"):
        value = bar.get(field)
        if value is not None and not pd.isna(value) and bool(value):
            return False
    return True


def _has_nonempty_text(value: object) -> bool:
    """Reject Python/pandas missing sentinels and whitespace-only source text."""
    if value is None or not isinstance(value, str):
        return False
    normalized = value.strip()
    if not normalized:
        return False
    return normalized.casefold() not in {"nan", "none", "null", "nat"}


def _verified_official_limits(
    bar: pd.Series,
    rule: LimitRule,
    *,
    symbol: str,
    trade_date: pd.Timestamp,
) -> tuple[Decimal, Decimal] | None:
    """Accept official prices only with complete, date-matched source evidence."""
    up = _decimal(bar.get("limit_up_price"))
    down = _decimal(bar.get("limit_down_price"))
    if up is None or down is None or up <= down or up <= 0 or down <= 0:
        return None
    required_text = (
        "official_limit_source_name",
        "official_limit_source_reference",
        "official_limit_source_version",
    )
    if any(not _has_nonempty_text(bar.get(field)) for field in required_text):
        return None
    if not _has_nonempty_text(bar.get("official_limit_evidence_status")):
        return None
    if bar.get("official_limit_evidence_status").strip() != "verified":
        return None
    verified_at = pd.to_datetime(
        bar.get("official_limit_verified_at"), errors="coerce"
    )
    official_date = pd.to_datetime(
        bar.get("official_limit_trade_date"), errors="coerce"
    )
    if pd.isna(verified_at) or pd.isna(official_date):
        return None
    if str(bar.get("official_limit_symbol") or "").zfill(6) != symbol:
        return None
    if official_date.normalize() != trade_date.normalize():
        return None
    quantum = Decimal("1").scaleb(-rule.price_precision)
    for value in (up, down):
        if value.quantize(quantum) != value:
            return None
        ticks = value / rule.tick_size
        if ticks != ticks.to_integral_value():
            return None
    return up, down


def detect_limit_events(
    daily: pd.DataFrame,
    rules: Iterable[LimitRule],
    statuses: Iterable[SecurityStatus],
    *,
    run_id: str,
    created_at: pd.Timestamp,
) -> pd.DataFrame:
    """Create one auditable observation per raw daily bar."""
    validate_unadjusted_prices(daily)
    rules, statuses = list(rules), list(statuses)
    rows: list[dict[str, object]] = []
    ordered = daily.copy()
    ordered["trade_date"] = pd.to_datetime(ordered["trade_date"]).dt.normalize()
    ordered = ordered.sort_values(
        ["symbol", "trade_date"], kind="mergesort"
    ).reset_index(drop=True)
    for _, group in ordered.groupby("symbol", sort=False):
        group = group.reset_index(drop=True)
        valid_positions = [
            position
            for position, bar in group.iterrows()
            if _is_valid_trade_row(bar)
        ]
        valid_rank = {
            position: rank for rank, position in enumerate(valid_positions)
        }
        for position, bar in group.iterrows():
            trade_date = bar["trade_date"].date()
            is_valid = position in valid_rank
            rank = valid_rank.get(position)
            previous_position = (
                valid_positions[rank - 1]
                if is_valid and rank is not None and rank > 0
                else None
            )
            result: dict[str, object] = {
                "symbol": str(bar["symbol"]).zfill(6),
                "trade_date": bar["trade_date"],
                "event_type": "none",
                "previous_close": (
                    group.iloc[previous_position]["close"]
                    if previous_position is not None
                    else None
                ),
                "open": bar.get("open"),
                "high": bar.get("high"),
                "low": bar.get("low"),
                "close": bar.get("close"),
                "official_limit_up_price": bar.get("limit_up_price"),
                "official_limit_down_price": bar.get("limit_down_price"),
                "official_limit_source_name": bar.get("official_limit_source_name"),
                "official_limit_source_reference": bar.get(
                    "official_limit_source_reference"
                ),
                "official_limit_source_version": bar.get(
                    "official_limit_source_version"
                ),
                "official_limit_evidence_status": bar.get(
                    "official_limit_evidence_status"
                ),
                "official_limit_verified_at": bar.get(
                    "official_limit_verified_at"
                ),
                "official_limit_fetched_at": bar.get(
                    "official_limit_fetched_at"
                ),
                "official_limit_symbol": bar.get("official_limit_symbol"),
                "official_limit_trade_date": bar.get(
                    "official_limit_trade_date"
                ),
                "official_limit_rejection_reason": None,
                "theoretical_limit_up_price": None,
                "theoretical_limit_down_price": None,
                "unrounded_limit_up_price": None,
                "unrounded_limit_down_price": None,
                "matched_limit_price": None,
                "tick_size": None,
                "limit_ratio": None,
                "rule_version": None,
                "security_status_version": None,
                "detection_method": "unresolved",
                "evidence_status": "unresolved",
                "quality_status": "excluded",
                "resolution_reason": None,
                "next_trade_date": None,
                "next_open": None,
                "next_close": None,
                "next_open_return": None,
                "next_close_return": None,
                "forward_3d_return": None,
                "forward_5d_return": None,
                "forward_10d_return": None,
                "forward_sample_status": "insufficient",
                "is_continued_limit": None,
                "is_valid_trade_row": is_valid,
                "run_id": run_id,
                "created_at": created_at,
            }
            if is_valid and rank is not None and rank + 1 < len(valid_positions):
                following = group.iloc[valid_positions[rank + 1]]
                result.update(
                    next_trade_date=following["trade_date"],
                    next_open=following.get("open"),
                    next_close=following.get("close"),
                    next_open_return=_return(bar.get("close"), following.get("open")),
                    next_close_return=_return(bar.get("close"), following.get("close")),
                )
            for horizon in (3, 5, 10):
                if is_valid and rank is not None and rank + horizon < len(valid_positions):
                    result[f"forward_{horizon}d_return"] = _return(
                        bar.get("close"),
                        group.iloc[valid_positions[rank + horizon]].get("close"),
                    )
            result["forward_sample_status"] = (
                "complete"
                if is_valid and rank is not None and rank + 10 < len(valid_positions)
                else ("tail_incomplete" if is_valid else "invalid_trade_row")
            )
            if not is_valid:
                result.update(
                    event_type="unresolved",
                    evidence_status="unresolved",
                    quality_status="failed",
                    resolution_reason="invalid_trade_row",
                )
                rows.append(result)
                continue
            try:
                status = resolve_security_status(
                    statuses, result["symbol"], trade_date
                )
                result["security_status_version"] = status.status_version
                if status.listing_status != "listed":
                    result["resolution_reason"] = (
                        f"listing_status={status.listing_status}"
                    )
                    rows.append(result)
                    continue
                rule = resolve_limit_rule(rules, status, trade_date)
                result.update(
                    tick_size=float(rule.tick_size),
                    rule_version=rule.rule_version,
                )
                if rule.no_limit_flag:
                    result.update(
                        detection_method="no_limit_rule",
                        evidence_status=rule.evidence_status,
                        quality_status="excluded",
                        resolution_reason=status.no_limit_reason
                        or "applicable rule has no_limit_flag",
                    )
                    rows.append(result)
                    continue
                previous = _decimal(result["previous_close"])
                close = _decimal(result["close"])
                required_prices = [bar.get(name) for name in ("open", "high", "low", "close")]
                if previous is None:
                    result.update(
                        event_type="unresolved",
                        quality_status="failed",
                        resolution_reason="missing_previous_close",
                    )
                    rows.append(result)
                    continue
                if close is None or any(pd.isna(value) for value in required_prices):
                    result.update(
                        event_type="unresolved",
                        quality_status="failed",
                        resolution_reason="calculation_error",
                    )
                    rows.append(result)
                    continue
                if "volume_share" in bar and (
                    pd.isna(bar.get("volume_share")) or float(bar.get("volume_share")) <= 0
                ):
                    result["resolution_reason"] = "suspended_or_no_valid_trade"
                    rows.append(result)
                    continue
                official = _verified_official_limits(
                    bar,
                    rule,
                    symbol=result["symbol"],
                    trade_date=bar["trade_date"],
                )
                up_ratio, down_ratio = rule.limit_up_ratio, rule.limit_down_ratio
                if official is not None:
                    up_price, down_price = official
                    result["detection_method"] = "verified_official_limit_price"
                else:
                    if _decimal(bar.get("limit_up_price")) is not None or _decimal(
                        bar.get("limit_down_price")
                    ) is not None:
                        result["official_limit_rejection_reason"] = (
                            "official_limit_unverified"
                        )
                    if up_ratio is None or down_ratio is None:
                        raise RuleResolutionError("Applicable rule has no limit ratios")
                    raw_up, up_price = calculate_limit_price(
                        previous, up_ratio, rule, direction="up"
                    )
                    raw_down, down_price = calculate_limit_price(
                        previous, down_ratio, rule, direction="down"
                    )
                    result.update(
                        unrounded_limit_up_price=float(raw_up),
                        unrounded_limit_down_price=float(raw_down),
                        theoretical_limit_up_price=float(up_price),
                        theoretical_limit_down_price=float(down_price),
                        detection_method="theoretical_decimal",
                    )
                up_match = price_matches(close, up_price, rule.tick_size)
                down_match = price_matches(close, down_price, rule.tick_size)
                if up_match and down_match:
                    result.update(
                        event_type="unresolved",
                        evidence_status="unresolved",
                        quality_status="failed",
                        resolution_reason="mutual_exclusion_conflict",
                    )
                elif up_match:
                    result.update(
                        event_type="limit_up",
                        matched_limit_price=float(up_price),
                        limit_ratio=float(up_ratio) if up_ratio is not None else None,
                    )
                elif down_match:
                    result.update(
                        event_type="limit_down",
                        matched_limit_price=float(down_price),
                        limit_ratio=float(down_ratio) if down_ratio is not None else None,
                    )
                if result["event_type"] in {"limit_up", "limit_down"}:
                    result["evidence_status"] = (
                        "verified"
                        if rule.evidence_status == "verified"
                        and status.evidence_status == "verified"
                        else "provisional"
                    )
                    result["quality_status"] = (
                        "pass"
                        if result["evidence_status"] == "verified"
                        else "excluded"
                    )
                    result["resolution_reason"] = "resolved"
                elif result["event_type"] == "none":
                    result.update(
                        evidence_status="not_applicable",
                        quality_status="not_event",
                        resolution_reason="normal_no_event",
                    )
            except (RuleResolutionError, SecurityStatusResolutionError) as exc:
                result.update(
                    event_type="unresolved",
                    quality_status="failed",
                    resolution_reason=(
                        "missing_security_status"
                        if isinstance(exc, SecurityStatusResolutionError)
                        else "missing_rule"
                    ),
                )
            rows.append(result)
    output = pd.DataFrame(rows)
    event_lookup = {
        (row.symbol, pd.Timestamp(row.trade_date)): row.event_type
        for row in output.itertuples(index=False)
    }
    for index, row in output.iterrows():
        next_date = row["next_trade_date"]
        if row["event_type"] in {"limit_up", "limit_down"} and pd.notna(next_date):
            output.at[index, "is_continued_limit"] = (
                event_lookup.get((row["symbol"], pd.Timestamp(next_date)))
                == row["event_type"]
            )
    return output


def formal_events(observations: pd.DataFrame) -> pd.DataFrame:
    """Exclude proxies, unresolved rows, and unverified evidence."""
    if observations.empty:
        return observations.copy()
    return observations.loc[
        observations["event_type"].isin(["limit_up", "limit_down"])
        & observations["evidence_status"].eq("verified")
        & observations["quality_status"].eq("pass")
    ].copy()
