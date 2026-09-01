"""Stage 19 A-share limit-event validation, enrichment, and release gating."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Iterable
import json

import pandas as pd

from .limit_event_detection import detect_limit_events
from .limit_rules import LimitRule, SecurityStatus


GATE_IDS = tuple(f"G{i}" for i in range(1, 10))


def coverage_matrix(
    statuses: Iterable[SecurityStatus], symbols: Iterable[str],
    start: date, end: date,
) -> pd.DataFrame:
    """Return per-symbol, per-status-type coverage without collapsing UNKNOWN."""
    rows = []
    all_statuses = list(statuses)
    required_days = pd.date_range(start, end, freq="D")
    for symbol in symbols:
        relevant = [s for s in all_statuses if s.symbol == symbol]
        for status_type in ("ST", "LISTING"):
            typed = [s for s in relevant if s.status_type in (None, status_type)]
            covered, unknown, conflicts = 0, 0, 0
            for ts in required_days:
                day = ts.date()
                matches = [s for s in typed if s.applies(day)]
                if len(matches) == 1:
                    covered += 1
                    item = matches[0]
                    if (status_type == "ST" and item.is_st is None) or item.evidence_status != "verified":
                        unknown += 1
                elif len(matches) > 1:
                    conflicts += 1
            rows.append({
                "symbol": symbol, "status_type": status_type,
                "required_days": len(required_days), "covered_days": covered,
                "gap_days": len(required_days) - covered,
                "unknown_days": unknown, "overlap_or_conflict_days": conflicts,
                "missing_source_records": sum(not bool(s.source_reference) for s in typed),
                "pending_manual_review_records": sum(s.review_status != "approved" for s in typed),
            })
    return pd.DataFrame(rows)


def rule_audit(rules: Iterable[LimitRule], start: date, end: date) -> dict[str, object]:
    records = list(rules)
    return {
        "record_count": len(records),
        "verified_count": sum(r.evidence_status == "verified" for r in records),
        "dual_reviewed_count": sum(r.review_status == "approved" for r in records),
        "waiver_count": sum(r.review_status == "approved_with_waiver" for r in records),
        "missing_source_count": sum(not bool(r.source_reference) for r in records),
        "coverage_start": start.isoformat(), "coverage_end": end.isoformat(),
    }


def enrich_candidates(observations: pd.DataFrame) -> pd.DataFrame:
    """Add trading-day-only next-day, forward excursion, and streak fields."""
    if observations.empty:
        return observations.copy()
    out = observations.sort_values(["symbol", "trade_date"], kind="mergesort").copy()
    additions = {
        "next_open_return_vs_event_close": None,
        "next_open_return_vs_pre_event_close": None,
        "next_high_return": None, "next_low_return": None,
        "next_day_gap_up": None,
        "consecutive_limit_up_count": 0,
        "consecutive_limit_down_count": 0,
    }
    for h in (3, 5, 10):
        additions[f"mfe_{h}d"] = None
        additions[f"mae_{h}d"] = None
    for name, value in additions.items():
        out[name] = value
    for _, index in out.groupby("symbol", sort=False).groups.items():
        idx = list(index)
        up_streak = down_streak = 0
        for rank, row_index in enumerate(idx):
            row = out.loc[row_index]
            event = row["event_type"]
            up_streak = up_streak + 1 if event == "limit_up" else 0
            down_streak = down_streak + 1 if event == "limit_down" else 0
            out.at[row_index, "consecutive_limit_up_count"] = up_streak
            out.at[row_index, "consecutive_limit_down_count"] = down_streak
            base = row.get("close")
            previous = row.get("previous_close")
            if rank + 1 < len(idx) and pd.notna(base):
                nxt = out.loc[idx[rank + 1]]
                out.at[row_index, "next_open_return_vs_event_close"] = nxt["open"] / base - 1
                out.at[row_index, "next_high_return"] = nxt["high"] / base - 1
                out.at[row_index, "next_low_return"] = nxt["low"] / base - 1
                out.at[row_index, "next_day_gap_up"] = bool(nxt["open"] > base)
                if pd.notna(previous) and previous != 0:
                    out.at[row_index, "next_open_return_vs_pre_event_close"] = nxt["open"] / previous - 1
            for horizon in (3, 5, 10):
                if rank + horizon < len(idx) and pd.notna(base) and base != 0:
                    window = out.loc[idx[rank + 1:rank + horizon + 1]]
                    out.at[row_index, f"mfe_{horizon}d"] = window["high"].max() / base - 1
                    out.at[row_index, f"mae_{horizon}d"] = window["low"].min() / base - 1
    out["next_day_continued_limit"] = out["is_continued_limit"]
    return out


def build_candidates(
    daily: pd.DataFrame, rules: Iterable[LimitRule], statuses: Iterable[SecurityStatus],
    *, run_id: str, created_at: pd.Timestamp,
) -> pd.DataFrame:
    return enrich_candidates(detect_limit_events(
        daily, rules, statuses, run_id=run_id, created_at=created_at
    ))


def release_gate(
    *, coverage: pd.DataFrame, rule_result: dict[str, object],
    status_result: dict[str, object], stage8_rebuild_pass: bool,
    s15_14_pass: bool,
) -> dict[str, object]:
    no_gaps = not coverage.empty and int(coverage["gap_days"].sum()) == 0
    no_conflicts = not coverage.empty and int(coverage["overlap_or_conflict_days"].sum()) == 0
    no_unknown = not coverage.empty and int(coverage["unknown_days"].sum()) == 0
    checks = {
        "G1": (status_result.get("status") == "READY" and no_gaps and no_unknown,
               "authoritative security status coverage is incomplete or UNKNOWN"),
        "G2": (status_result.get("status") == "READY", "security status source audit is incomplete"),
        "G3": (rule_result.get("status") == "READY", "limit rule source audit is incomplete"),
        "G4": (status_result.get("review_status") == "approved" and rule_result.get("review_status") == "approved",
               "required dual manual review is incomplete"),
        "G5": (no_gaps, "unexplained security status gaps remain"),
        "G6": (no_conflicts, "security status overlaps remain"),
        "G7": (no_conflicts and no_unknown, "unresolved status conflict or UNKNOWN remains"),
        "G8": (stage8_rebuild_pass, "Stage 8 formal rebuild has not passed"),
        "G9": (s15_14_pass, "S15-14 revalidation has not passed"),
    }
    rendered = {key: {"status": "PASS" if passed else "BLOCKED", "reason": "" if passed else reason}
                for key, (passed, reason) in checks.items()}
    blockers = [f"{key}:{value['reason']}" for key, value in rendered.items() if value["status"] != "PASS"]
    return {"stage": 19, "formal_event_release": {"status": "PASS" if not blockers else "BLOCKED",
            "checks": rendered, "blocked_reasons": blockers}}


def blocked_statistics(symbols: Iterable[str], start: date, end: date,
                       run_id: str, blockers: list[str]) -> pd.DataFrame:
    metrics = ("limit_up_count", "limit_down_count", "max_limit_up_streak",
               "max_limit_down_streak", "avg_next_open_return", "avg_next_close_return",
               "continued_limit_ratio", "forward_3d_return", "forward_5d_return",
               "forward_10d_return")
    reason = "; ".join(blockers)
    return pd.DataFrame([{"run_id": run_id, "symbol": symbol, "period_start": start,
        "period_end": end, "metric_name": metric, "value": None,
        "availability_status": "BLOCKED", "reason": reason}
        for symbol in symbols for metric in metrics])


def eligible_official_events(candidates: pd.DataFrame, gate: dict[str, object]) -> pd.DataFrame:
    """Return only fully traceable events when the complete release gate passes."""
    if gate["formal_event_release"]["status"] != "PASS" or candidates.empty:
        return candidates.iloc[0:0].copy()
    method = "detection_method" if "detection_method" in candidates else "calculation_method"
    reason = "resolution_reason" if "resolution_reason" in candidates else "blocked_reason"
    required = {"event_type", "evidence_status", "quality_status", "rule_version",
                "security_status_version", method}
    missing = required - set(candidates.columns)
    if missing:
        raise ValueError("Candidate frame lacks official-release fields: " + ",".join(sorted(missing)))
    mask = (
        candidates["event_type"].isin(["limit_up", "limit_down"])
        & candidates["evidence_status"].eq("verified")
        & candidates["quality_status"].eq("pass")
        & candidates["rule_version"].notna()
        & candidates["security_status_version"].notna()
        & candidates[method].notna()
        & ~candidates[method].eq("unresolved")
    )
    if reason in candidates:
        mask &= candidates[reason].isin(["resolved", None]) | candidates[reason].isna()
    return candidates.loc[mask].copy()


def formal_statistics(official: pd.DataFrame, symbols: Iterable[str], start: date,
                      end: date, run_id: str) -> pd.DataFrame:
    """Build formal metrics; counts may be zero, unavailable returns remain NULL."""
    rows: list[dict[str, object]] = []

    def append(symbol: str, metric: str, value: object, *, reason: str | None = None) -> None:
        rows.append({"run_id": run_id, "symbol": symbol, "period_start": start,
            "period_end": end, "metric_name": metric, "value": value,
            "availability_status": "AVAILABLE" if value is not None and not pd.isna(value) else "UNAVAILABLE",
            "reason": reason if value is None or pd.isna(value) else None})

    for symbol in symbols:
        events = official.loc[official["symbol"].astype(str).eq(str(symbol))].copy()
        up = events.loc[events["event_type"].eq("limit_up")]
        down = events.loc[events["event_type"].eq("limit_down")]
        append(str(symbol), "limit_up_count", int(len(up)))
        append(str(symbol), "limit_down_count", int(len(down)))
        append(str(symbol), "max_limit_up_streak",
               int(up["consecutive_limit_up_count"].max()) if not up.empty else 0)
        append(str(symbol), "max_limit_down_streak",
               int(down["consecutive_limit_down_count"].max()) if not down.empty else 0)
        for metric, field, no_data_reason in (
            ("avg_next_open_return", "next_open_return_vs_event_close", "INSUFFICIENT_NEXT_DAY_DATA"),
            ("avg_next_close_return", "next_close_return", "INSUFFICIENT_NEXT_DAY_DATA"),
            ("continued_limit_ratio", "next_day_continued_limit", "INSUFFICIENT_NEXT_DAY_DATA"),
            ("forward_3d_return", "forward_3d_return", "INSUFFICIENT_FORWARD_3D_WINDOW"),
            ("forward_5d_return", "forward_5d_return", "INSUFFICIENT_FORWARD_5D_WINDOW"),
            ("forward_10d_return", "forward_10d_return", "INSUFFICIENT_FORWARD_10D_WINDOW"),
        ):
            available = events[field].dropna() if field in events else pd.Series(dtype=float)
            append(str(symbol), metric, float(available.astype(float).mean()) if not available.empty else None,
                   reason=no_data_reason if not events.empty else "NO_ELIGIBLE_EVENTS")
    return pd.DataFrame(rows)
