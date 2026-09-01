from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from akshare_data_test.stage19_governance import (
    GovernanceContractError,
    load_governance_contract,
    stage20_entry_authorized,
    validate_governance_contract,
)


ROOT = Path(__file__).resolve().parents[1]
DECISION_PATH = ROOT / "reports/stage19/conditional_closure/stage19_conditional_closure.json"
CONTRACT_PATH = ROOT / "reports/stage19/conditional_closure/stage20_restricted_downstream_contract.json"
REAL_RUN = ROOT / "reports/stage19/8d1e4e7b-4a97-4c2e-9e9e-stage19blocked"


@pytest.fixture(scope="module")
def decision():
    return json.loads(DECISION_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def contract():
    return load_governance_contract(CONTRACT_PATH)


def test_machine_documents_parse(decision, contract):
    assert decision["stage"] == 19
    assert contract["source_stage"] == 19
    assert contract["target_stage"] == 20


def test_conditional_closure_is_not_formal_pass(decision):
    assert decision["management_status"] == "CONDITIONALLY_CLOSED"
    assert decision["runtime_status"] != "PASS"


def test_framework_pass_is_separate_from_event_release(decision):
    assert decision["framework_status"] == "PASS"
    assert decision["formal_event_release_status"] == "BLOCKED"


def test_official_event_availability_remains_blocked(decision):
    assert decision["official_event_availability"] == "BLOCKED"


def test_restricted_entry_is_authorized(contract):
    assert contract["restricted_entry_authorized"] is True
    assert stage20_entry_authorized(CONTRACT_PATH, "RESTRICTED") is True


def test_full_entry_is_not_authorized(contract):
    assert contract["full_entry_authorized"] is False
    assert stage20_entry_authorized(CONTRACT_PATH, "FULL") is False


def test_missing_closure_contract_cannot_start_stage20(tmp_path):
    assert stage20_entry_authorized(None, "RESTRICTED") is False
    assert stage20_entry_authorized(tmp_path / "missing.json", "RESTRICTED") is False


def test_authorization_is_restricted_to_non_event_scope(contract):
    assert contract["authorization_mode"] == "RESTRICTED"
    assert contract["authorization_scope"] == "NON_EVENT_ONLY"
    assert contract["stage20_started"] is False


def test_non_event_capabilities_are_allowed(contract):
    allowed = set(contract["allowed_capabilities"])
    required = {
        "stock_code_filter", "market_filter", "date_range_filter", "non_event_metric_filter",
        "a_share_market_data", "hk_share_market_data", "ethusdt_market_data",
        "daily_kline", "weekly_kline", "quality_gated_minute_kline",
        "ma3", "ma5", "ma7", "ma10", "ma13", "ma20", "ma21",
        "volume", "amount", "turnover_rate", "non_event_price_volume_indicators",
        "stage18_pass_fundamentals", "revenue", "net_profit", "roe", "roa",
        "gross_margin", "net_margin", "pe", "pb", "ps", "total_market_cap",
        "float_market_cap", "available_fundamental_features",
        "security_code_comparison", "time_comparison", "metric_comparison",
        "non_event_market_analysis",
    }
    assert allowed == required


def test_all_declared_event_capabilities_are_blocked(contract):
    blocked = set(contract["blocked_capabilities"])
    required = {
        "official_limit_up_count",
        "official_limit_down_count",
        "official_limit_up_event_list",
        "official_limit_down_event_list",
        "consecutive_limit_up_analysis",
        "consecutive_limit_down_analysis",
        "limit_up_next_day_performance",
        "limit_down_next_day_performance",
        "event_forward_3d_return",
        "event_forward_5d_return",
        "event_forward_10d_return",
        "event_mfe_mae_ranking",
        "event_based_ranking",
        "event_based_screening",
        "event_dependent_stock_score",
        "candidate_event_as_official",
        "frontend_inferred_official_limit_event",
    }
    assert blocked == required


def test_candidate_data_is_prohibited_as_official(contract):
    assert contract["formal_inputs"]["stage19_candidate_event"] == "PROHIBITED_AS_OFFICIAL"
    assert contract["event_data_policy"]["candidate_access"] == "INTERNAL_ONLY_PROHIBITED_USER_FACING"
    assert contract["event_data_policy"]["official_event_query_allowed"] is False


def test_real_formal_statistics_remain_null_and_blocked():
    statistics = pd.read_csv(REAL_RUN / "formal_statistics.csv")
    assert len(statistics) == 160
    assert statistics["value"].isna().all()
    assert statistics["availability_status"].eq("BLOCKED").all()
    assert not statistics["value"].eq(0).any()


def test_real_gate_and_official_count_remain_blocked():
    gate = json.loads((REAL_RUN / "stage19_gate.json").read_text(encoding="utf-8"))
    manifest = json.loads((REAL_RUN / "stage19_manifest.json").read_text(encoding="utf-8"))
    assert gate["formal_event_release"]["status"] == "BLOCKED"
    assert manifest["candidate_count"] == 3862
    assert manifest["official_event_count"] == 0


def test_unresolved_blockers_are_retained(decision, contract):
    assert decision["remediation_status"] == "OPEN"
    assert len(decision["unresolved_blockers"]) == 5
    assert contract["unresolved_blockers"] == decision["unresolved_blockers"]


def test_status_propagation_is_explicit(contract):
    propagation = contract["required_status_propagation"]
    assert propagation["preserve_null"] is True
    assert propagation["preserve_blocked_or_unavailable"] is True
    assert propagation["zero_fill_prohibited"] is True
    assert propagation["explicit_chinese_blocker_message_required"] is True
    assert contract["event_data_policy"]["blocked_value"] is None


def test_invalid_contract_cannot_relax_blocked_release(contract):
    invalid = dict(contract)
    invalid["formal_event_release_status"] = "PASS"
    with pytest.raises(GovernanceContractError, match="formal_event_release_status"):
        validate_governance_contract(invalid)


def test_decision_and_contract_authorization_are_consistent(decision, contract):
    assert decision["restricted_entry_authorized"] == contract["restricted_entry_authorized"]
    assert decision["full_entry_authorized"] == contract["full_entry_authorized"]
    assert decision["authorization_scope"] == contract["authorization_scope"]


def test_transition_rules_record_restricted_not_full_entry():
    rules = (ROOT / "docs/stage_transition_rules.md").read_text(encoding="utf-8")
    assert "Stage 19管理状态：`CONDITIONALLY_CLOSED`" in rules
    assert "`RESTRICTED/NON_EVENT_ONLY`" in rules
    assert "Stage 20完整入口：`NOT_AUTHORIZED`" in rules
