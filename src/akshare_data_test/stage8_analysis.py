"""Stage 8 annual summaries and publication gating."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .limit_event_detection import formal_events


SUMMARY_COLUMNS = [
    "symbol", "period_start", "period_end", "limit_up_count",
    "limit_down_count", "avg_next_open_return_after_limit_up",
    "avg_next_close_return_after_limit_up",
    "avg_forward_3d_return_after_limit_up",
    "avg_forward_5d_return_after_limit_up",
    "avg_forward_10d_return_after_limit_up",
    "next_day_gap_up_ratio", "continued_limit_ratio",
    "formal_event_count", "publication_status",
]
FORMAL_SUMMARY_COLUMNS = [
    "limit_up_count", "limit_down_count",
    "avg_next_open_return_after_limit_up",
    "avg_next_close_return_after_limit_up",
    "avg_forward_3d_return_after_limit_up",
    "avg_forward_5d_return_after_limit_up",
    "avg_forward_10d_return_after_limit_up",
    "next_day_gap_up_ratio", "continued_limit_ratio", "formal_event_count",
]


@dataclass(frozen=True)
class PublicationDecision:
    """Single source of truth for run/publication state and CLI exit code."""

    run_status: str
    publication_status: str
    exit_code: int
    blocking_reasons: tuple[str, ...]
    failed_quality_checks: tuple[str, ...]


def apply_publication_status(
    summary: pd.DataFrame, publication_status: str
) -> pd.DataFrame:
    """Apply one fail-closed publication state to every annual result field."""
    result = summary.copy()
    if result.empty:
        return result
    result["publication_status"] = publication_status
    if publication_status != "formal":
        result[FORMAL_SUMMARY_COLUMNS] = None
    return result


def decide_publication(
    observations: pd.DataFrame,
    quality: pd.DataFrame | None,
    *,
    base_blockers: list[str] | None = None,
) -> PublicationDecision:
    """Fail closed on unresolved evidence or any ERROR-level quality failure."""
    blockers = set(base_blockers or [])
    if not observations.empty:
        forbidden = observations["event_type"].isin(
            ["unresolved", "candidate", "proxy", "gap_proxy"]
        )
        if forbidden.any():
            blockers.add(f"unresolved_or_forbidden_events={int(forbidden.sum())}")
        unresolved_evidence = observations["evidence_status"].isin(
            ["unresolved", "provisional", "unverified"]
        )
        if unresolved_evidence.any():
            blockers.add(
                "unresolved_or_provisional_observations="
                + str(int(unresolved_evidence.sum()))
            )
        invalid_formal_state = (
            observations["event_type"].isin(["limit_up", "limit_down"])
            & (
                ~observations["evidence_status"].eq("verified")
                | ~observations["quality_status"].eq("pass")
            )
        )
        if invalid_formal_state.any():
            blockers.add(
                f"invalid_formal_event_state={int(invalid_formal_state.sum())}"
            )
        critical_reasons = {
            "mutual_exclusion_conflict", "missing_rule",
            "missing_security_status", "missing_previous_close",
            "invalid_price_route", "invalid_trade_row",
            "official_limit_unverified", "calculation_error",
        }
        unresolved_reasons = observations["resolution_reason"].isin(
            critical_reasons
        )
        if unresolved_reasons.any():
            blockers.add(
                f"unresolved_resolution_reasons={int(unresolved_reasons.sum())}"
            )
    failed: tuple[str, ...] = ()
    if quality is not None and not quality.empty:
        failed_rows = quality.loc[
            quality["severity"].eq("ERROR") & quality["status"].eq("FAIL")
        ]
        failed = tuple(sorted(failed_rows["check_name"].astype(str).unique()))
        blockers.update("quality_error:" + name for name in failed)
    if blockers:
        return PublicationDecision(
            run_status="BLOCKED",
            publication_status="blocked",
            exit_code=2,
            blocking_reasons=tuple(sorted(blockers)),
            failed_quality_checks=failed,
        )
    return PublicationDecision(
        run_status="PASS",
        publication_status="formal",
        exit_code=0,
        blocking_reasons=(),
        failed_quality_checks=(),
    )


def summarize_annual_events(
    observations: pd.DataFrame, *, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> tuple[pd.DataFrame, str, list[str]]:
    """Summarize only formal events; absence under incomplete coverage is not zero."""
    period = observations.loc[
        pd.to_datetime(observations["trade_date"]).between(start_date, end_date)
    ].copy()
    blockers: list[str] = []
    if period.empty:
        blockers.append("no_price_observations")
    unresolved = period["event_type"].isin(
        ["unresolved", "candidate", "proxy", "gap_proxy"]
    ).sum()
    unresolved += period["evidence_status"].isin(
        ["unresolved", "provisional", "unverified"]
    ).sum()
    if unresolved:
        blockers.append(f"unresolved_or_provisional_observations={int(unresolved)}")
    official = formal_events(period)
    symbols = sorted(period["symbol"].astype(str).unique())
    rows: list[dict[str, object]] = []
    for symbol in symbols:
        events = official.loc[official["symbol"].eq(symbol)]
        if blockers:
            up_count = down_count = None
        else:
            up_count = int(events["event_type"].eq("limit_up").sum())
            down_count = int(events["event_type"].eq("limit_down").sum())
        up_events = events.loc[events["event_type"].eq("limit_up")]
        def event_mean(field: str) -> float | None:
            return up_events[field].mean() if field in up_events.columns else None

        rows.append(
            {
                "symbol": symbol,
                "period_start": start_date,
                "period_end": end_date,
                "limit_up_count": up_count,
                "limit_down_count": down_count,
                "avg_next_open_return_after_limit_up": event_mean(
                    "next_open_return"
                ),
                "avg_next_close_return_after_limit_up": event_mean(
                    "next_close_return"
                ),
                "avg_forward_3d_return_after_limit_up": event_mean(
                    "forward_3d_return"
                ),
                "avg_forward_5d_return_after_limit_up": event_mean(
                    "forward_5d_return"
                ),
                "avg_forward_10d_return_after_limit_up": event_mean(
                    "forward_10d_return"
                ),
                "next_day_gap_up_ratio": (
                    up_events["next_open_return"].gt(0).mean()
                    if up_events["next_open_return"].notna().any()
                    else None
                ),
                "continued_limit_ratio": (
                    up_events["is_continued_limit"].mean()
                    if up_events["is_continued_limit"].notna().any()
                    else None
                ),
                "formal_event_count": None if blockers else len(events),
                "publication_status": "blocked" if blockers else "formal",
            }
        )
    publication_status = "blocked" if blockers else "formal"
    return (
        apply_publication_status(
            pd.DataFrame(rows, columns=SUMMARY_COLUMNS), publication_status
        ),
        publication_status,
        blockers,
    )
