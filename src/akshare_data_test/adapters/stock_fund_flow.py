"""Network boundary for the allowed Stage 4 individual fund-flow call."""
from __future__ import annotations

from typing import Any

from .stock_finance import FinancialCall, OutputCapture, StockFinanceAdapter


class StockFundFlowAdapter(StockFinanceAdapter):
    """Dedicated adapter for the individual fund-flow interface."""

    def __init__(
        self, ak_module: Any | None = None, *, retry_delay_seconds: float = 1.0
    ) -> None:
        super().__init__(
            ak_module=ak_module, retry_delay_seconds=retry_delay_seconds
        )

    def fetch_individual_fund_flow(
        self,
        symbol_plain: str,
        market_lower: str,
        *,
        output_capture: OutputCapture | None = None,
    ) -> FinancialCall:
        return self._call(
            "stock_individual_fund_flow",
            {"stock": symbol_plain, "market": market_lower},
            output_capture,
        )
