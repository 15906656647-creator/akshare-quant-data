"""Stage 19 条件封板与 Stage 20 受限入口的机器校验。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


class GovernanceContractError(ValueError):
    """合同缺少必要约束或包含自相矛盾状态。"""


def load_governance_contract(path: Path) -> dict[str, Any]:
    """读取并校验 Stage 19 到 Stage 20 的受限下游合同。"""
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_governance_contract(payload)
    return payload


def validate_governance_contract(contract: Mapping[str, Any]) -> None:
    """拒绝会放宽 Stage 19 BLOCKED 状态的合同。"""
    required = {
        "source_stage",
        "target_stage",
        "management_status",
        "framework_status",
        "formal_event_release_status",
        "official_event_availability",
        "authorization_mode",
        "authorization_scope",
        "restricted_entry_authorized",
        "full_entry_authorized",
        "stage20_started",
        "allowed_capabilities",
        "blocked_capabilities",
        "event_data_policy",
        "required_status_propagation",
        "unresolved_blockers",
    }
    missing = sorted(required - contract.keys())
    if missing:
        raise GovernanceContractError(f"合同缺少字段: {', '.join(missing)}")

    expected = {
        "source_stage": 19,
        "target_stage": 20,
        "management_status": "CONDITIONALLY_CLOSED",
        "framework_status": "PASS",
        "formal_event_release_status": "BLOCKED",
        "official_event_availability": "BLOCKED",
        "authorization_mode": "RESTRICTED",
        "authorization_scope": "NON_EVENT_ONLY",
        "restricted_entry_authorized": True,
        "full_entry_authorized": False,
        "stage20_started": False,
    }
    conflicts = [key for key, value in expected.items() if contract.get(key) != value]
    if conflicts:
        raise GovernanceContractError(f"合同状态冲突: {', '.join(conflicts)}")

    allowed = set(contract["allowed_capabilities"])
    blocked = set(contract["blocked_capabilities"])
    if not allowed or not blocked or allowed & blocked:
        raise GovernanceContractError("允许与禁止能力必须为非空且互斥的集合")

    policy = contract["event_data_policy"]
    if (
        policy.get("official_event_query_allowed") is not False
        or policy.get("official_event_statistics_allowed") is not False
        or policy.get("candidate_access") != "INTERNAL_ONLY_PROHIBITED_USER_FACING"
        or policy.get("frontend_event_inference_allowed") is not False
        or policy.get("blocked_value", "missing") is not None
    ):
        raise GovernanceContractError("事件数据策略未保持 BLOCKED/NULL/candidate 隔离")

    propagation = contract["required_status_propagation"]
    propagation_flags = (
        "consume_formal_event_release_status",
        "preserve_null",
        "preserve_blocked_or_unavailable",
        "zero_fill_prohibited",
        "candidate_display_prohibited",
        "explicit_chinese_blocker_message_required",
    )
    if not all(propagation.get(flag) is True for flag in propagation_flags):
        raise GovernanceContractError("下游状态传播约束不完整")
    if not contract["unresolved_blockers"]:
        raise GovernanceContractError("条件封板不得清空未解决阻塞项")


def stage20_entry_authorized(contract_path: Path | None, requested_mode: str) -> bool:
    """返回指定 Stage 20 入口是否被正式合同授权。"""
    if requested_mode not in {"RESTRICTED", "FULL"}:
        raise ValueError("requested_mode 只能是 RESTRICTED 或 FULL")
    if contract_path is None or not contract_path.is_file():
        return False

    contract = load_governance_contract(contract_path)
    if requested_mode == "RESTRICTED":
        return bool(contract["restricted_entry_authorized"])
    return bool(
        contract["full_entry_authorized"]
        and contract["formal_event_release_status"] == "PASS"
        and contract["official_event_availability"] == "AVAILABLE"
    )
