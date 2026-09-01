"""Append-only Stage 17 dataset storage with per-file audit metadata."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from .raw_store import file_sha256, schema_hash


def _safe_partition(value: str) -> str:
    token = str(value)
    if not token or any(ch in token for ch in "\\/:*?\"<>|") or token in {".", ".."}:
        raise ValueError(f"Unsafe Stage 17 partition value: {value!r}")
    return token


class Stage17RawStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def dataset_dir(
        self, *, dataset: str, run_id: str, market: str, symbol: str,
        adjust: str | None = None, interval: str | None = None,
        source: str | None = None,
    ) -> Path:
        path = (
            self.root / _safe_partition(dataset) / f"run_id={_safe_partition(run_id)}"
            / f"market={_safe_partition(market)}" / f"symbol={_safe_partition(symbol)}"
        )
        if adjust is not None:
            path /= f"adjust={_safe_partition(adjust)}"
        if interval is not None:
            path /= f"interval={_safe_partition(interval)}"
        if source is not None:
            path /= f"source={_safe_partition(source)}"
        return path
    def write_dataset(
        self, frame: pd.DataFrame, directory: str | Path, metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if frame.empty:
            raise ValueError("Empty Stage 17 frames cannot be written as successful Raw data")
        target = Path(directory)
        data_path = target / "data.parquet"
        metadata_path = target / "metadata.json"
        if data_path.exists() or metadata_path.exists():
            raise FileExistsError(f"Stage 17 Raw dataset already exists: {target}")
        target.mkdir(parents=True, exist_ok=True)
        data_tmp = data_path.with_suffix(".parquet.tmp")
        meta_tmp = metadata_path.with_suffix(".json.tmp")
        if data_tmp.exists() or meta_tmp.exists():
            raise FileExistsError(f"Stage 17 temporary dataset already exists: {target}")
        try:
            frame.to_parquet(data_tmp, index=False)
            record = {
                **metadata,
                "row_count": int(len(frame)),
                "column_count": int(len(frame.columns)),
                "schema_hash": schema_hash(frame),
                "data_size_bytes": data_tmp.stat().st_size,
                "data_sha256": file_sha256(data_tmp),
            }
            meta_tmp.write_text(
                json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            os.replace(data_tmp, data_path)
            os.replace(meta_tmp, metadata_path)
        except Exception:
            for item in (data_tmp, meta_tmp):
                if item.exists():
                    item.unlink()
            raise
        return {
            **record,
            "data_path": data_path,
            "metadata_path": metadata_path,
        }
