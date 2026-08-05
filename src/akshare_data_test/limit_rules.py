"""Date-effective Stage 8 price-limit rules and security statuses."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN, ROUND_HALF_UP
import re
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
    symbol: str | None = None
    security_type: str | None = None
    source_published_at: date | None = None
    source_hash: str | None = None
    data_version: str | None = None
    record_id: str | None = None
    raw_file: str | None = None
    source_document_id: str | None = None
    reviewer: str | None = None
    notes: str | None = None
    retrieved_at: str | None = None
    review_status: str | None = None

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
        if self.symbol is not None and (
            len(self.symbol) != 6 or not self.symbol.isdigit()
        ):
            raise ValueError("rule symbol must be six digits when provided")
        if self.security_type is not None and (
            not isinstance(self.security_type, str)
            or not re.fullmatch(r"[A-Z0-9_]+", self.security_type)
        ):
            raise ValueError(
                "rule security_type must be an uppercase token such as A_SHARE"
            )
        if self.source_hash is not None and (
            not re.fullmatch(r"[0-9a-f]{64}", self.source_hash)
        ):
            raise ValueError("source_hash must be a 64-character lowercase SHA-256")
        if self.data_version is not None and not str(self.data_version).strip():
            raise ValueError("data_version must be non-empty when provided")
        for name, value in (
            ("record_id", self.record_id),
            ("raw_file", self.raw_file),
            ("source_document_id", self.source_document_id),
            ("reviewer", self.reviewer),
            ("retrieved_at", self.retrieved_at),
        ):
            if value is not None and not str(value).strip():
                raise ValueError(f"{name} must be non-empty when provided")
        if self.review_status is not None and self.review_status not in {
            "approved", "rejected", "pending"
        }:
            raise ValueError("review_status must be approved/rejected/pending")

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
    special_treatment_type: str | None = None
    source_name: str | None = None
    source_published_at: date | None = None
    source_hash: str | None = None
    data_version: str | None = None
    record_id: str | None = None
    status_type: str | None = None
    status_value: str | None = None
    announcement_date: date | None = None
    raw_file: str | None = None
    source_document_id: str | None = None
    reviewer: str | None = None
    notes: str | None = None
    retrieved_at: str | None = None
    review_status: str | None = None

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
        if self.special_treatment_type is not None and self.special_treatment_type not in {
            "none", "ST", "*ST", "other"
        }:
            raise ValueError(
                "special_treatment_type must be one of none/ST/*ST/other"
            )
        if self.source_hash is not None and (
            not re.fullmatch(r"[0-9a-f]{64}", self.source_hash)
        ):
            raise ValueError("source_hash must be a 64-character lowercase SHA-256")
        if self.data_version is not None and not str(self.data_version).strip():
            raise ValueError("data_version must be non-empty when provided")
        if self.status_type is not None and self.status_type not in {
            "ST", "LISTING"
        }:
            raise ValueError("status_type must be ST or LISTING")
        if self.status_value is not None:
            allowed_status_values = {
                "ST": {"NON_ST", "ST", "*ST", "OTHER"},
                "LISTING": {"LISTED", "SUSPENDED", "DELISTED"},
            }
            if (
                self.status_type is None
                or self.status_value not in allowed_status_values[self.status_type]
            ):
                raise ValueError("status_value is invalid for status_type")
        for name, value in (
            ("record_id", self.record_id),
            ("raw_file", self.raw_file),
            ("source_document_id", self.source_document_id),
            ("reviewer", self.reviewer),
            ("retrieved_at", self.retrieved_at),
        ):
            if value is not None and not str(value).strip():
                raise ValueError(f"{name} must be non-empty when provided")
        if self.review_status is not None and self.review_status not in {
            "approved", "rejected", "pending"
        }:
            raise ValueError("review_status must be approved/rejected/pending")

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
    grouped: dict[tuple[str, str, bool, str, str], list[LimitRule]] = {}
    for rule in rules:
        grouped.setdefault(
            (
                rule.exchange,
                rule.board,
                rule.is_st,
                rule.symbol or "",
                rule.security_type or "",
            ),
            [],
        ).append(rule)
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
    """Reject overlapping intervals for one symbol and status type."""
    grouped: dict[tuple[str, str], list[SecurityStatus]] = {}
    for status in statuses:
        grouped.setdefault(
            (status.symbol, status.status_type or ""), []
        ).append(status)
    for (symbol, status_type), group in grouped.items():
        ordered = sorted(group, key=lambda item: item.effective_start)
        for previous, current in zip(ordered, ordered[1:]):
            if _overlaps(
                previous.effective_start,
                previous.effective_end,
                current.effective_start,
                current.effective_end,
            ):
                raise ValueError(
                    f"Overlapping security-status intervals for {symbol} "
                    f"(status_type={status_type or 'combined'})"
                )


def _unique_text(*values: str | None) -> str:
    seen: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.append(text)
    return " ; ".join(seen)


def _merge_security_statuses(
    st: SecurityStatus,
    listing: SecurityStatus,
    symbol: str,
    trade_date: date,
) -> SecurityStatus:
    """Merge one ST row and one LISTING row into the combined runtime view."""
    if st.exchange != listing.exchange:
        raise SecurityStatusResolutionError(
            f"ST/LISTING exchanges differ for {symbol} on {trade_date}"
        )
    board_values = [
        value for value in (st.board, listing.board) if value is not None
    ]
    if not board_values or any(value != board_values[0] for value in board_values):
        raise SecurityStatusResolutionError(
            f"ST/LISTING boards differ for {symbol} on {trade_date}"
        )
    is_st = st.is_st if st.is_st is not None else listing.is_st
    listing_status = (
        listing.listing_status
        if listing.listing_status != "unresolved"
        else st.listing_status
    )
    versions = _unique_text(st.status_version, listing.status_version)
    if st.effective_end is None or listing.effective_end is None:
        effective_end: date | None = None
    else:
        effective_end = min(st.effective_end, listing.effective_end)
    return SecurityStatus(
        symbol=symbol,
        effective_start=max(st.effective_start, listing.effective_start),
        effective_end=effective_end,
        exchange=st.exchange,
        board=board_values[0],
        is_st=is_st,
        listing_status=listing_status,
        listing_date=listing.listing_date or st.listing_date,
        delisting_date=listing.delisting_date or st.delisting_date,
        no_limit_reason=listing.no_limit_reason or st.no_limit_reason,
        source_reference=_unique_text(st.source_reference, listing.source_reference),
        status_version=versions,
        evidence_status=(
            "verified"
            if st.evidence_status == "verified"
            and listing.evidence_status == "verified"
            else "unverified"
        ),
        special_treatment_type=(
            st.special_treatment_type or listing.special_treatment_type
        ),
        source_name=_unique_text(st.source_name, listing.source_name),
        source_published_at=max(
            value
            for value in (st.source_published_at, listing.source_published_at)
            if value is not None
        )
        if st.source_published_at is not None or listing.source_published_at is not None
        else None,
        source_hash=_unique_text(st.source_hash, listing.source_hash),
        data_version=st.data_version or listing.data_version,
        record_id=_unique_text(st.record_id, listing.record_id).replace(" ; ", "|"),
        status_type=None,
        status_value=None,
        announcement_date=max(
            value
            for value in (st.announcement_date, listing.announcement_date)
            if value is not None
        )
        if st.announcement_date is not None or listing.announcement_date is not None
        else None,
        raw_file=_unique_text(st.raw_file, listing.raw_file),
        source_document_id=_unique_text(
            st.source_document_id, listing.source_document_id
        ),
        reviewer=_unique_text(st.reviewer, listing.reviewer),
        notes=_unique_text(st.notes, listing.notes),
        retrieved_at=_unique_text(st.retrieved_at, listing.retrieved_at),
        review_status=(
            "approved"
            if st.review_status == "approved" and listing.review_status == "approved"
            else st.review_status or listing.review_status
        ),
    )


def resolve_security_status(
    statuses: Iterable[SecurityStatus], symbol: str, trade_date: date
) -> SecurityStatus:
    """Resolve the unique ST and listing status pair for one symbol/date."""
    matches = [
        status
        for status in statuses
        if status.symbol == symbol and status.applies(trade_date)
    ]
    if not matches:
        raise SecurityStatusResolutionError(
            f"Expected one security status for {symbol} on {trade_date}, "
            "found 0"
        )
    st_matches = [status for status in matches if status.status_type in (None, "ST")]
    listing_matches = [
        status for status in matches if status.status_type in (None, "LISTING")
    ]
    if len(st_matches) != 1 or len(listing_matches) != 1:
        raise SecurityStatusResolutionError(
            f"Expected one security status for {symbol} on {trade_date}, "
            f"found st={len(st_matches)} listing={len(listing_matches)}"
        )
    st, listing = st_matches[0], listing_matches[0]
    if st is listing:
        return st
    return _merge_security_statuses(st, listing, symbol, trade_date)


def resolve_limit_rule(
    rules: Iterable[LimitRule], status: SecurityStatus, trade_date: date
) -> LimitRule:
    if status.is_st is None:
        raise RuleResolutionError(
            f"Security ST status is unresolved for {status.symbol} on {trade_date}"
        )
    candidate = [
        rule
        for rule in rules
        if rule.exchange == status.exchange
        and rule.board == status.board
        and rule.is_st == status.is_st
        and (rule.symbol is None or rule.symbol == status.symbol)
        and rule.applies(trade_date)
    ]
    symbol_matches = [rule for rule in candidate if rule.symbol == status.symbol]
    if len(symbol_matches) == 1:
        return symbol_matches[0]
    if len(symbol_matches) > 1:
        raise RuleResolutionError(
            f"Multiple symbol-specific limit rules for {status.symbol} on "
            f"{trade_date}, found {len(symbol_matches)}"
        )
    board_matches = [rule for rule in candidate if rule.symbol is None]
    if len(board_matches) == 1:
        return board_matches[0]
    raise RuleResolutionError(
        f"Expected one limit rule for {status.exchange}/{status.board}/"
        f"is_st={status.is_st} on {trade_date}, found {len(candidate)}"
    )


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
