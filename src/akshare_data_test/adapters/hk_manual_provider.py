"""Offline manual/external Hong Kong daily-data adapter for Stage 17."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = ("symbol", "date", "open", "high", "low", "close", "volume")
OPTIONAL_COLUMNS = ("amount", "turnover")
ADJUSTMENTS = ("raw", "qfq", "hfq")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ManualDailyCall:
    dataframe: pd.DataFrame | None
    status: str
    source_path: Path | None = None
    metadata_path: Path | None = None
    source_sha256: str = ""
    metadata: dict[str, Any] | None = None
    error_type: str = ""
    error_message: str = ""


class HkManualProvider:
    """Read explicit CSV/Parquet files without network access or value repair."""

    provider_name = "manual_external"

    def __init__(self, input_dir: str | Path) -> None:
        self.input_dir = Path(input_dir).resolve()

    def _source_path(self, *, symbol: str, adjust: str) -> Path | None:
        stem = f"{symbol}.{adjust}"
        matches = [
            path for path in (self.input_dir / f"{stem}.csv", self.input_dir / f"{stem}.parquet")
            if path.is_file()
        ]
        if len(matches) > 1:
            raise ValueError(f"Multiple manual source files found for {symbol}/{adjust}")
        return matches[0] if matches else None

    def fetch_daily(self, symbol: str, adjust: str) -> ManualDailyCall:
        if symbol != "09669.HK":
            raise ValueError("Stage 17.6.5 manual provider is restricted to 09669.HK")
        if adjust not in ADJUSTMENTS:
            raise ValueError("adjust must be raw, qfq, or hfq")
        source_path = self._source_path(symbol=symbol, adjust=adjust)
        metadata_path = self.input_dir / f"{symbol}.{adjust}.metadata.json"
        if source_path is None:
            return ManualDailyCall(
                None, "unavailable", error_type="source_file_missing",
                error_message=f"No CSV or Parquet source file for {symbol}/{adjust}",
            )
        if not metadata_path.is_file():
            return ManualDailyCall(
                None, "failed", source_path=source_path,
                source_sha256=file_sha256(source_path),
                error_type="source_metadata_missing",
                error_message=f"Missing metadata file: {metadata_path.name}",
            )
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return ManualDailyCall(
                None, "failed", source_path=source_path, metadata_path=metadata_path,
                source_sha256=file_sha256(source_path), error_type="invalid_source_metadata",
                error_message=str(exc),
            )
        if not isinstance(metadata, dict):
            return ManualDailyCall(
                None, "failed", source_path=source_path, metadata_path=metadata_path,
                source_sha256=file_sha256(source_path), error_type="invalid_source_metadata",
                error_message="metadata.json must contain a JSON object",
            )
        digest = file_sha256(source_path)
        required_metadata = {
            "symbol": symbol,
            "provider": self.provider_name,
            "adjust_type": adjust,
        }
        for field, expected in required_metadata.items():
            if metadata.get(field) != expected:
                return ManualDailyCall(
                    None, "failed", source_path=source_path, metadata_path=metadata_path,
                    source_sha256=digest, metadata=metadata,
                    error_type="source_metadata_identity_mismatch",
                    error_message=f"metadata.{field} must equal {expected}",
                )
        for field in ("source", "acquired_at", "provider_adjust_semantics", "field_definition"):
            if not isinstance(metadata.get(field), str) or not metadata[field].strip():
                return ManualDailyCall(
                    None, "failed", source_path=source_path, metadata_path=metadata_path,
                    source_sha256=digest, metadata=metadata,
                    error_type="source_metadata_incomplete",
                    error_message=f"metadata.{field} must be a non-empty string",
                )
        if metadata.get("sha256") != digest:
            return ManualDailyCall(
                None, "failed", source_path=source_path, metadata_path=metadata_path,
                source_sha256=digest, metadata=metadata, error_type="source_hash_mismatch",
                error_message="metadata.sha256 does not match the source file",
            )
        basis = metadata.get("adjustment_basis")
        if adjust == "raw":
            if basis != "unadjusted_provider_native":
                return ManualDailyCall(
                    None, "failed", source_path=source_path, metadata_path=metadata_path,
                    source_sha256=digest, metadata=metadata,
                    error_type="adjustment_semantics_invalid",
                    error_message="raw requires adjustment_basis=unadjusted_provider_native",
                )
        elif basis not in {"provider_native", "calculated_from_corporate_actions"}:
            return ManualDailyCall(
                None, "failed", source_path=source_path, metadata_path=metadata_path,
                source_sha256=digest, metadata=metadata,
                error_type="adjustment_semantics_invalid",
                error_message=(
                    "qfq/hfq require provider_native or calculated_from_corporate_actions"
                ),
            )
        if basis == "calculated_from_corporate_actions":
            evidence = metadata.get("adjustment_evidence")
            if not isinstance(evidence, dict):
                return ManualDailyCall(
                    None, "failed", source_path=source_path, metadata_path=metadata_path,
                    source_sha256=digest, metadata=metadata,
                    error_type="adjustment_evidence_missing",
                    error_message="calculated data require adjustment_evidence",
                )
            for field in ("raw_sha256", "corporate_actions_sha256", "factors_sha256"):
                value = evidence.get(field)
                if not isinstance(value, str) or len(value) != 64:
                    return ManualDailyCall(
                        None, "failed", source_path=source_path, metadata_path=metadata_path,
                        source_sha256=digest, metadata=metadata,
                        error_type="adjustment_evidence_incomplete",
                        error_message=f"adjustment_evidence.{field} must be SHA-256",
                    )
        try:
            frame = (
                pd.read_csv(source_path, dtype={"symbol": "string"})
                if source_path.suffix.casefold() == ".csv"
                else pd.read_parquet(source_path)
            )
        except Exception as exc:
            return ManualDailyCall(
                None, "failed", source_path=source_path, metadata_path=metadata_path,
                source_sha256=digest, metadata=metadata, error_type="source_read_error",
                error_message=str(exc),
            )
        missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
        if missing:
            return ManualDailyCall(
                None, "failed", source_path=source_path, metadata_path=metadata_path,
                source_sha256=digest, metadata=metadata, error_type="unexpected_schema",
                error_message=f"Missing required columns: {','.join(missing)}",
            )
        symbols = frame["symbol"].astype("string")
        if frame.empty or symbols.isna().any() or set(symbols.tolist()) != {symbol}:
            return ManualDailyCall(
                frame, "failed", source_path=source_path, metadata_path=metadata_path,
                source_sha256=digest, metadata=metadata, error_type="symbol_identity_error",
                error_message=f"All rows must have symbol={symbol}",
            )
        columns = list(REQUIRED_COLUMNS) + [
            column for column in OPTIONAL_COLUMNS if column in frame.columns
        ]
        return ManualDailyCall(
            frame[columns].copy(), "success", source_path=source_path,
            metadata_path=metadata_path, source_sha256=digest, metadata=metadata,
        )
