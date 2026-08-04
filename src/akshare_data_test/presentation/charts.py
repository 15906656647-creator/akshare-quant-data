"""Deterministic, headless Stage 13 chart rendering."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable
import warnings

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


class ChartRenderer:
    def __init__(self, *, dpi: int, as_of_date: pd.Timestamp, run_id: str):
        self.dpi = dpi
        self.as_of_date = pd.Timestamp(as_of_date).date().isoformat()
        self.run_id = run_id

    def _save(self, fig: plt.Figure, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            fig.tight_layout()
            fig.savefig(
                path, dpi=self.dpi, format="png",
                metadata={"Software": "akshare-data-test", "Creation Time": self.as_of_date},
            )
        plt.close(fig)

    def _footer(self, ax: plt.Axes, *, status: str, source: str, coverage: str, rows: int, basis: str) -> None:
        text = (
            f"status={status} | source={source} | cutoff={self.as_of_date} | "
            f"coverage={coverage} | rows={rows} | basis={basis} | "
            f"generated={self.as_of_date}T00:00:00Z | run_id={self.run_id}"
        )
        ax.text(0, -0.23, text, transform=ax.transAxes, fontsize=6, va="top", wrap=True)

    @staticmethod
    def _coverage(frame: pd.DataFrame, date_column: str) -> str:
        if frame.empty:
            return "none"
        return f"{pd.Timestamp(frame[date_column].min()).date()}..{pd.Timestamp(frame[date_column].max()).date()}"

    def price_ma(self, frame: pd.DataFrame, path: Path, symbol: str) -> None:
        fig, ax = plt.subplots(figsize=(11, 5.5))
        styles = ["-", "--", "-.", ":", "--", "-.", ":"]
        ax.plot(frame.trade_date, frame.close_qfq, color="black", lw=1.4, label="QFQ close")
        for window, style in zip((3, 5, 7, 10, 13, 20, 21), styles):
            ax.plot(frame.trade_date, frame[f"ma_{window}"], linestyle=style, lw=0.9, label=f"MA{window}")
        ax.set(title=f"{symbol} QFQ close and moving averages", ylabel="CNY/share", xlabel="trade date")
        ax.grid(alpha=.2); ax.legend(ncol=4, fontsize=7)
        self._footer(ax, status="AVAILABLE", source="Stage 6 feat_trend_daily", coverage=self._coverage(frame, "trade_date"), rows=len(frame), basis="qfq")
        self._save(fig, path)

    def volume_ma(self, frame: pd.DataFrame, path: Path, symbol: str) -> None:
        fig, ax = plt.subplots(figsize=(11, 5.5))
        ax.bar(frame.trade_date, frame.volume_share, color="#7d8da1", width=1.0, label="volume")
        ax.plot(frame.trade_date, frame.volume_ma_5, "--", color="#d55e00", label="volume MA5")
        ax.plot(frame.trade_date, frame.volume_ma_20, "-.", color="#0072b2", label="volume MA20")
        ax.set(title=f"{symbol} volume and moving averages", ylabel="shares", xlabel="trade date")
        ax.grid(alpha=.2); ax.legend(fontsize=8)
        self._footer(ax, status="AVAILABLE", source="Stage 6 feat_price_daily", coverage=self._coverage(frame, "trade_date"), rows=len(frame), basis="standardized shares")
        self._save(fig, path)

    def activity(self, row: pd.Series, path: Path, symbol: str, *, status: str) -> None:
        names = ["liquidity", "turnover", "volatility", "volume spike", "large move", "event proxy"]
        columns = ["liquidity_component", "turnover_component", "volatility_component", "volume_spike_component", "large_move_component", "event_component"]
        values = [float(row.get(c)) if pd.notna(row.get(c)) else np.nan for c in columns]
        fig, ax = plt.subplots(figsize=(9, 5.5))
        bars = ax.barh(names, np.nan_to_num(values, nan=0.0), color="#4c78a8")
        for bar, value in zip(bars, values):
            ax.text(bar.get_width() + .01, bar.get_y() + bar.get_height()/2, "missing" if np.isnan(value) else f"{value:.3f}", va="center", fontsize=8)
        ax.set(xlim=(0, 1.08), xlabel="component score [0,1]", title=f"{symbol} activity | score={row.activity_score:.3f} | rank={int(row.activity_rank)}/{int(row.rank_denominator)} | pct={row.activity_percentile:.3f}")
        self._footer(ax, status=status, source="Stage 7 analysis_stock_activity", coverage=str(pd.Timestamp(row.as_of_date).date()), rows=1, basis=f"completeness={row.component_completeness:.3f}; reasons={row.reason_codes}")
        self._save(fig, path)

    def limit_events(self, frame: pd.DataFrame, path: Path, symbol: str, *, status: str = "AVAILABLE") -> None:
        fig, ax = plt.subplots(figsize=(11, 5.5))
        if frame.empty:
            ax.text(.5, .5, "No confirmed Stage 6 limit events in the visible window", ha="center", va="center", transform=ax.transAxes)
            coverage = "none"
            valid = frame
        else:
            prices = pd.to_numeric(frame.event_price, errors="coerce")
            valid = frame.loc[np.isfinite(prices) & prices.gt(0)].copy()
            mapping = {"up": 1, "limit_up": 1, "down": -1, "limit_down": -1}
            directions = valid.limit_direction.map(mapping).fillna(0)
            ax.scatter(
                valid.trade_date, valid.event_price,
                c=np.where(directions >= 0, "#d55e00", "#0072b2"), s=40,
            )
            if valid.empty:
                ax.text(.5, .5, "Confirmed events lack a valid authoritative event price", ha="center", va="center", transform=ax.transAxes)
            coverage = self._coverage(frame, "trade_date")
        ax.set(title=f"{symbol} confirmed formal limit events", xlabel="trade date", ylabel="event price (CNY/share)")
        ax.grid(alpha=.2)
        self._footer(
            ax, status=status, source="Stage 6 feat_limit_event.raw_close",
            coverage=coverage, rows=len(frame),
            basis=f"confirmed rows only; plotted_valid_prices={len(valid)}; no threshold recomputation",
        )
        self._save(fig, path)

    def next_open_return(self, frame: pd.DataFrame, path: Path, symbol: str, *, missing: int) -> None:
        fig, ax = plt.subplots(figsize=(11, 5.5))
        values = frame.next_open_return.dropna() if "next_open_return" in frame else pd.Series(dtype=float)
        if values.empty:
            ax.text(.5, .5, "No complete next-trading-day return sample", ha="center", va="center", transform=ax.transAxes)
        else:
            ax.hist(values, bins=min(10, max(1, len(values))), color="#4c78a8", edgecolor="white")
            ax.axvline(values.mean(), color="#d55e00", ls="--", label=f"mean={values.mean():.4f}")
            ax.legend(fontsize=8)
        ax.set(title=f"{symbol} next-open return after confirmed limit events", xlabel="next open / event close - 1", ylabel="event count")
        self._footer(ax, status="AVAILABLE", source="Stage 6 events + Stage 5 qfq", coverage=self.as_of_date, rows=len(values), basis=f"immediate next trading day; missing={missing}")
        self._save(fig, path)

    def range_chart(self, frame: pd.DataFrame, path: Path, symbol: str, *, high: float, low: float, label: str, confidence: float) -> None:
        fig, ax = plt.subplots(figsize=(11, 5.5))
        display_label = label if str(label).isascii() else "insufficient_evidence"
        display_confidence = f"{confidence:.3f}" if np.isfinite(confidence) else "unavailable"
        ax.plot(frame.trade_date, frame.close, "-o", ms=2.5, color="#0072b2", label="QFQ close")
        ax.axhline(high, color="#d55e00", ls="--", label="40-day high")
        ax.axhline(low, color="#009e73", ls="-.", label="40-day low")
        ax.axhline((high + low) / 2, color="#666666", ls=":", label="mid")
        ax.set(title=f"{symbol} 40-session range | {display_label} | confidence={display_confidence}", ylabel="CNY/share", xlabel="trade date")
        ax.grid(alpha=.2); ax.legend(fontsize=8)
        self._footer(ax, status="PARTIAL", source="Stage 5 qfq + Stage 6 style", coverage=self._coverage(frame, "trade_date"), rows=len(frame), basis="authoritative range metrics; formal breakout events unavailable")
        self._save(fig, path)

    def financial(self, frame: pd.DataFrame, path: Path, symbol: str) -> None:
        pivot = frame.pivot(index="report_period", columns="line_item_name_source", values="line_item_value").sort_index()
        fig, ax = plt.subplots(figsize=(11, 5.5))
        ax.plot(pivot.index, pivot.get("TOTAL_OPERATE_INCOME") / 1e8, "-o", label="cumulative operating revenue")
        ax.plot(pivot.index, pivot.get("PARENT_NETPROFIT") / 1e8, "--s", label="cumulative parent net profit")
        ax.set(title=f"{symbol} reported cumulative financial trend", ylabel="CNY 100 million", xlabel="report period")
        ax.axhline(0, color="black", lw=.6); ax.grid(alpha=.2); ax.legend(fontsize=8)
        self._footer(ax, status="AVAILABLE", source="Stage 5 point-in-time financial statement", coverage=self._coverage(frame, "announcement_date"), rows=len(frame), basis="reported cumulative values; announcement_date visible")
        self._save(fig, path)

    def fund_flow(self, frame: pd.DataFrame, path: Path, symbol: str) -> None:
        fig, left = plt.subplots(figsize=(11, 5.5)); right = left.twinx()
        left.plot(frame.trade_date, frame.price_close, color="#0072b2", label="QFQ close")
        colors = np.where(frame.main_net_inflow_cny >= 0, "#009e73", "#d55e00")
        right.bar(frame.trade_date, frame.main_net_inflow_cny / 1e8, color=colors, alpha=.45, label="upstream-labelled main net inflow")
        left.set(title=f"{symbol} price and upstream-labelled main fund flow", ylabel="CNY/share", xlabel="trade date")
        right.set_ylabel("CNY 100 million")
        lines, labels = left.get_legend_handles_labels(); lines2, labels2 = right.get_legend_handles_labels()
        left.legend(lines + lines2, labels + labels2, fontsize=8)
        self._footer(left, status="AVAILABLE", source="Stage 5 as-of-safe fund flow", coverage=self._coverage(frame, "trade_date"), rows=len(frame), basis="upstream category; not verified trader identity")
        self._save(fig, path)
