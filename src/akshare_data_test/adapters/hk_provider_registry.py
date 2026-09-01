"""Quality-gated Hong Kong provider registry for Stage 17.7."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Callable

from .hk_market import HkMarketAdapter
from .hk_tencent_adapter import HkTencentAdapter
from .hk_tencent_direct import HkTencentDirectAdapter


@dataclass(frozen=True)
class HkProviderAttempt:
    provider: str
    interface: str
    call: Any
    quality: dict[str, Any] | None
    coverage_status: str
    rejection_reason: str


@dataclass(frozen=True)
class HkProviderSelection:
    attempts: tuple[HkProviderAttempt, ...]
    selected: HkProviderAttempt | None
    selection_reason: str


class HkProviderRegistry:
    """Select a provider only after response, quality and coverage gates pass."""

    def __init__(
        self, *, routes: dict[str, dict[str, tuple[str, ...]]],
        eastmoney: HkMarketAdapter, tencent: HkTencentAdapter,
        tencent_compat: HkTencentDirectAdapter,
    ) -> None:
        self.routes = routes
        self.eastmoney = eastmoney
        self.tencent = tencent
        self.tencent_compat = tencent_compat

    @property
    def akshare_version(self) -> str:
        return self.eastmoney.akshare_version

    def fetch_profile(self, **kwargs: Any) -> Any:
        return self.eastmoney.fetch_profile(**kwargs)

    def fetch_minutes(self, **kwargs: Any) -> Any:
        return self.eastmoney.fetch_minutes(**kwargs)

    @staticmethod
    def _interface(provider: str) -> str:
        return {
            "tencent": "stock_zh_ah_daily",
            "tencent_compat": "tencent_hkfqkline_direct_https",
            "eastmoney": "stock_hk_hist",
            "sina": "stock_hk_daily",
        }[provider]

    def _fetch(
        self, *, provider: str, symbol: str, listing_date: date,
        as_of_date: date, adjust: str,
    ) -> Any:
        source_adjust = "" if adjust == "raw" else adjust
        if provider == "tencent":
            return self.tencent.fetch_history(
                symbol=symbol, listing_date=listing_date,
                as_of_date=as_of_date, adjust=adjust,
            )
        if provider == "tencent_compat":
            return self.tencent_compat.fetch_history(
                symbol=symbol, listing_date=listing_date,
                as_of_date=as_of_date, adjust=adjust,
            )
        if provider == "eastmoney":
            return self.eastmoney.fetch_history(
                symbol=symbol, start_date=listing_date.strftime("%Y%m%d"),
                end_date=as_of_date.strftime("%Y%m%d"), adjust=source_adjust,
            )
        if provider == "sina":
            return self.eastmoney.fetch_history_fallback(
                symbol=symbol, start_date=listing_date.strftime("%Y%m%d"),
                end_date=as_of_date.strftime("%Y%m%d"), adjust=source_adjust,
            )
        raise ValueError(f"Unknown HK provider: {provider}")

    def select_history(
        self, *, symbol: str, listing_date: date | None, as_of_date: date,
        adjust: str, quality_validator: Callable[[Any], dict[str, Any]],
        coverage_validator: Callable[[date | None, str | None], str],
    ) -> HkProviderSelection:
        if listing_date is None:
            return HkProviderSelection((), None, "listing_date_unavailable")
        providers = self.routes[symbol][adjust]
        attempts: list[HkProviderAttempt] = []
        for provider in providers:
            call = self._fetch(
                provider=provider, symbol=symbol, listing_date=listing_date,
                as_of_date=as_of_date, adjust=adjust,
            )
            quality = (
                quality_validator(call.dataframe)
                if call.status == "success" and call.dataframe is not None else None
            )
            coverage = coverage_validator(
                listing_date, quality.get("min_date") if quality else None,
            )
            if call.status != "success":
                rejection = call.error_type or call.status
            elif quality is None or quality.get("status") != "PASS":
                rejection = str((quality or {}).get("errors", ["quality_not_run"])[0])
            elif coverage != "complete_to_verified_listing_date":
                rejection = coverage
            else:
                rejection = ""
            attempt = HkProviderAttempt(
                provider, self._interface(provider), call, quality, coverage, rejection,
            )
            attempts.append(attempt)
            if not rejection:
                return HkProviderSelection(
                    tuple(attempts), attempt,
                    f"{provider}_passed_identity_quality_coverage_adjust_semantics",
                )
        return HkProviderSelection(tuple(attempts), None, "no_provider_passed_all_gates")
