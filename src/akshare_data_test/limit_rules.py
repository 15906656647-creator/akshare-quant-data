"""Date-effective Stage 8 price-limit rules and security statuses."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP
from typing import Iterable


class RuleResolutionError(ValueError):
    """No unique applicable price-limit rule can be resolved."""


class SecurityStatusResolutionError(ValueError):
    """No unique security status can be resolved."""


@dataclass(frozen=True)
class LimitRule:
    exchange: str
    board: str
    is_st: bool
    effective_start: date
    effective_end: date | None
    limit_up_ratio: Decimal | None
    limit_down_ratio: Decimal | None
    no_limit_flag: bool
    tick_size: Decimal
    price_precision: int
    rounding_rule: str
    rule_version: str
    source_reference: str
    source_name: str
    verified_at: date | None
    evidence_status: str = "unverified"

    def __post_init__(self) -> None:
        if type(self.is_st) is not bool or type(self.no_limit_flag) is not bool:
            raise ValueError("is_st and no_limit_flag must be YAML booleans")
        if not self.exchange or not self.board or not self.rule_version:
            raise ValueError("exchange, board, and rule_version must be non-empty")
        if self.effective_end is not None and self.effective_end < self.effective_start:
            raise ValueError("effective_end cannot be earlier than effective_start")
        if self.tick_size <= 0 or type(self.price_precision) is not int or self.price_precision < 0:
            raise ValueError("tick_size and price_precision are invalid")
        quantum = Decimal("1").scaleb(-self.price_precision)
        if self.tick_size.quantize(quantum) != self.tick_size:
            raise ValueError("tick_size is inconsistent with price_precision")
        if self.rounding_rule not in {"half_up", "half_even"}:
            raise ValueError(f"Unsupported rounding_rule: {self.rounding_rule}")
        if self.no_limit_flag:
            if self.limit_up_ratio is not None or self.limit_down_ratio is not None:
                raise ValueError("no-limit rules must not define limit ratios")
        else:
            for name, ratio in (
                ("limit_up_ratio", self.limit_up_ratio),
                ("limit_down_ratio", self.limit_down_ratio),
            ):
                if ratio is None or not Decimal("0") < ratio < Decimal("1"):
                    raise ValueError(f"{name} must be between 0 and 1")
        if not self.source_reference:
            raise ValueError("source_reference must be non-empty")
        if self.evidence_status == "verified" and (
            not self.source_name or self.verified_at is None
        ):
            raise ValueError(
                "verified rules require source_name, source_reference, and verified_at"
            )

    def applies(self, trade_date: date) -> bool:
        return (
            self.effective_start <= trade_date
            and (self.effective_end is None or trade_date <= self.effective_end)
        )


@dataclass(frozen=True)
class SecurityStatus:
    symbol: str
    effective_start: date
    effective_end: date | None
    exchange: str
    board: str
    is_st: bool | None
    listing_status: str
    listing_date: date | None
    delisting_date: date | None
    no_limit_reason: str | None
    source_reference: str
    status_version: str
    evidence_status: str = "unverified"

    def __post_init__(self) -> None:
        if len(self.symbol) != 6 or not self.symbol.isdigit():
            raise ValueError("security status symbol must be six digits")
        if self.is_st is not None and type(self.is_st) is not bool:
            raise ValueError("security status is_st must be boolean or null")
        if self.effective_end is not None and self.effective_end < self.effective_start:
            raise ValueError("effective_end cannot be earlier than effective_start")
        if self.listing_status not in {
            "listed", "suspended", "delisted", "unknown", "unresolved"
        }:
            raise ValueError(f"Invalid listing_status: {self.listing_status}")
        if not self.source_reference or not self.status_version:
            raise ValueError("security status source_reference/version is required")

    def applies(self, trade_date: date) -> bool:
        return (
            self.effective_start <= trade_date
            and (self.effective_end is None or trade_date <= self.effective_end)
        )


def _overlaps(
    left_start: date,
    left_end: date | None,
    right_start: date,
    right_end: date | None,
) -> bool:
    return (
        left_start <= (right_end or date.max)
        and right_start <= (left_end or date.max)
    )


def validate_rule_intervals(rules: Iterable[LimitRule]) -> None:
    """Reject overlapping intervals for one exchange/board/ST key."""
    grouped: dict[tuple[str, str, bool], list[LimitRule]] = {}
    for rule in rules:
        grouped.setdefault((rule.exchange, rule.board, rule.is_st), []).append(rule)
    for key, group in grouped.items():
        ordered = sorted(group, key=lambda item: item.effective_start)
        for previous, current in zip(ordered, ordered[1:]):
            if _overlaps(
                previous.effective_start,
                previous.effective_end,
                current.effective_start,
                current.effective_end,
            ):
                raise ValueError(f"Overlapping limit-rule intervals for {key}")


def validate_status_intervals(statuses: Iterable[SecurityStatus]) -> None:
    """Reject overlapping intervals for one symbol."""
    grouped: dict[str, list[SecurityStatus]] = {}
    for status in statuses:
        grouped.setdefault(status.symbol, []).append(status)
    for symbol, group in grouped.items():
        ordered = sorted(group, key=lambda item: item.effective_start)
        for previous, current in zip(ordered, ordered[1:]):
            if _overlaps(
                previous.effective_start,
                previous.effective_end,
                current.effective_start,
                current.effective_end,
            ):
                raise ValueError(
                    f"Overlapping security-status intervals for {symbol}"
                )


def resolve_security_status(
    statuses: Iterable[SecurityStatus], symbol: str, trade_date: date
) -> SecurityStatus:
    matches = [
        status
        for status in statuses
        if status.symbol == symbol and status.applies(trade_date)
    ]
    if len(matches) != 1:
        raise SecurityStatusResolutionError(
            f"Expected one security status for {symbol} on {trade_date}, "
            f"found {len(matches)}"
        )
    return matches[0]


def resolve_limit_rule(
    rules: Iterable[LimitRule], status: SecurityStatus, trade_date: date
) -> LimitRule:
    if status.is_st is None:
        raise RuleResolutionError(
            f"Security ST status is unresolved for {status.symbol} on {trade_date}"
        )
    matches = [
        rule
        for rule in rules
        if rule.exchange == status.exchange
        and rule.board == status.board
        and rule.is_st == status.is_st
        and rule.applies(trade_date)
    ]
    if len(matches) != 1:
        raise RuleResolutionError(
            f"Expected one limit rule for {status.exchange}/{status.board}/"
            f"is_st={status.is_st} on {trade_date}, found {len(matches)}"
        )
    return matches[0]


def calculate_limit_price(
    previous_close: Decimal, ratio: Decimal, rule: LimitRule, *, direction: str
) -> tuple[Decimal, Decimal]:
    """Return unrounded and tick-rounded theoretical limit price."""
    if previous_close <= 0:
        raise ValueError("previous_close must be positive")
    multiplier = Decimal("1") + ratio if direction == "up" else Decimal("1") - ratio
    if direction not in {"up", "down"}:
        raise ValueError("direction must be 'up' or 'down'")
    unrounded = previous_close * multiplier
    rounding = ROUND_HALF_UP if rule.rounding_rule == "half_up" else ROUND_HALF_EVEN
    ticks = (unrounded / rule.tick_size).quantize(Decimal("1"), rounding=rounding)
    rounded = ticks * rule.tick_size
    quantum = Decimal("1").scaleb(-rule.price_precision)
    return unrounded, rounded.quantize(quantum)


def price_matches(
    actual: Decimal, limit_price: Decimal, tick_size: Decimal
) -> bool:
    """Match at the configured half-tick tolerance, including its boundary."""
    return abs(actual - limit_price) <= tick_size / Decimal("2")
