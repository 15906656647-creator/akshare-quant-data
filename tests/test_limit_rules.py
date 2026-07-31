from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from akshare_data_test.limit_rules import (
    LimitRule,
    RuleResolutionError,
    SecurityStatus,
    SecurityStatusResolutionError,
    calculate_limit_price,
    price_matches,
    resolve_limit_rule,
    resolve_security_status,
    validate_rule_intervals,
    validate_status_intervals,
)


def rule(**overrides) -> LimitRule:
    values = {
        "exchange": "SZ",
        "board": "main",
        "is_st": False,
        "effective_start": date(2020, 1, 1),
        "effective_end": None,
        "limit_up_ratio": Decimal("0.10"),
        "limit_down_ratio": Decimal("0.10"),
        "no_limit_flag": False,
        "tick_size": Decimal("0.01"),
        "price_precision": 2,
        "rounding_rule": "half_up",
        "rule_version": "test-rule-v1",
        "source_reference": "fixture://verified-rule",
        "source_name": "test fixture",
        "verified_at": date(2026, 7, 27),
        "evidence_status": "verified",
    }
    values.update(overrides)
    return LimitRule(**values)


def status(**overrides) -> SecurityStatus:
    values = {
        "symbol": "000001",
        "effective_start": date(2020, 1, 1),
        "effective_end": None,
        "exchange": "SZ",
        "board": "main",
        "is_st": False,
        "listing_status": "listed",
        "listing_date": date(1991, 1, 1),
        "delisting_date": None,
        "no_limit_reason": None,
        "source_reference": "fixture://verified-status",
        "status_version": "test-status-v1",
        "evidence_status": "verified",
    }
    values.update(overrides)
    return SecurityStatus(**values)


def test_rule_date_boundaries_are_inclusive():
    item = rule(effective_end=date(2021, 12, 31))
    assert item.applies(date(2020, 1, 1))
    assert item.applies(date(2021, 12, 31))
    assert not item.applies(date(2022, 1, 1))


def test_rule_interval_overlap_is_rejected():
    with pytest.raises(ValueError, match="Overlapping"):
        validate_rule_intervals([
            rule(effective_end=date(2021, 1, 10)),
            rule(effective_start=date(2021, 1, 10), rule_version="v2"),
        ])


def test_adjacent_non_overlapping_rules_are_valid():
    validate_rule_intervals([
        rule(effective_end=date(2021, 1, 9)),
        rule(effective_start=date(2021, 1, 10), rule_version="v2"),
    ])


def test_missing_rule_is_not_defaulted():
    with pytest.raises(RuleResolutionError, match="found 0"):
        resolve_limit_rule([rule(board="growth")], status(), date(2021, 1, 1))


def test_missing_status_is_not_defaulted():
    with pytest.raises(SecurityStatusResolutionError, match="found 0"):
        resolve_security_status([], "000001", date(2021, 1, 1))


def test_status_overlap_is_rejected():
    with pytest.raises(ValueError, match="Overlapping"):
        validate_status_intervals([
            status(effective_end=date(2022, 1, 1)),
            status(effective_start=date(2022, 1, 1), status_version="v2"),
        ])


def test_st_status_change_selects_corresponding_rule():
    statuses = [
        status(effective_end=date(2021, 12, 31)),
        status(effective_start=date(2022, 1, 1), is_st=True, status_version="st-v2"),
    ]
    selected = resolve_security_status(statuses, "000001", date(2022, 2, 1))
    assert resolve_limit_rule(
        [rule(), rule(is_st=True, rule_version="st-rule")],
        selected,
        date(2022, 2, 1),
    ).rule_version == "st-rule"


def test_board_change_selects_corresponding_rule():
    changed = status(board="growth", status_version="growth-v1")
    selected = resolve_limit_rule(
        [rule(), rule(board="growth", rule_version="growth-rule")],
        changed,
        date(2021, 1, 1),
    )
    assert selected.rule_version == "growth-rule"


def test_decimal_half_up_rounding():
    unrounded, rounded = calculate_limit_price(
        Decimal("10.05"), Decimal("0.10"), rule(), direction="up"
    )
    assert unrounded == Decimal("11.0550")
    assert rounded == Decimal("11.06")


def test_decimal_half_even_rounding():
    _, rounded = calculate_limit_price(
        Decimal("10.05"),
        Decimal("0.10"),
        rule(rounding_rule="half_even"),
        direction="up",
    )
    assert rounded == Decimal("11.06")


def test_tick_half_tolerance_boundary_is_inclusive():
    assert price_matches(Decimal("11.005"), Decimal("11.00"), Decimal("0.01"))
    assert not price_matches(Decimal("11.0051"), Decimal("11.00"), Decimal("0.01"))


def test_no_limit_rule_can_have_null_ratios():
    validate_rule_intervals([
        rule(
            no_limit_flag=True,
            limit_up_ratio=None,
            limit_down_ratio=None,
        )
    ])


@pytest.mark.parametrize("ratio", ["0", "-0.1", "1", "1.1"])
def test_invalid_limit_ratios_are_rejected(ratio):
    with pytest.raises(ValueError, match="between 0 and 1"):
        rule(limit_up_ratio=Decimal(ratio))


def test_reversed_effective_interval_is_rejected():
    with pytest.raises(ValueError, match="effective_end"):
        rule(
            effective_start=date(2022, 1, 2),
            effective_end=date(2022, 1, 1),
        )


def test_tick_precision_mismatch_is_rejected():
    with pytest.raises(ValueError, match="inconsistent"):
        rule(tick_size=Decimal("0.005"), price_precision=2)


def test_verified_rule_requires_source_audit_fields():
    with pytest.raises(ValueError, match="verified rules require"):
        rule(source_name="")
    with pytest.raises(ValueError, match="verified rules require"):
        rule(verified_at=None)


def test_string_boolean_is_rejected():
    with pytest.raises(ValueError, match="YAML booleans"):
        rule(is_st="false")


def test_invalid_listing_status_is_rejected():
    with pytest.raises(ValueError, match="listing_status"):
        status(listing_status="anything")
