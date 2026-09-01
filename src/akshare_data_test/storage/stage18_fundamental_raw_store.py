"""Append-only storage for Stage 18.2 formal fundamental Raw datasets."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from .raw_store import file_sha256, schema_hash


def _safe(value: str) -> str:
    token = str(value)
    if not token or token in {".", ".."} or any(ch in token for ch in '\\/:*?"<>|'):
        raise ValueError(f"Unsafe Stage 18.2 partition value: {value!r}")
    return token


class Stage18FundamentalRawStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def dataset_dir(
        self, *, category: str, run_id: str, market: str, symbol: str, variant: str,
    ) -> Path:
        return (
            self.root / _safe(category) / f"run_id={_safe(run_id)}"
            / f"market={_safe(market)}" / f"symbol={_safe(symbol)}"
            / f"variant={_safe(variant)}"
        )

    def write(
        self, frame: pd.DataFrame | None, directory: str | Path,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        target = Path(directory)
        data_path = target / "data.parquet"
        metadata_path = target / "metadata.json"
        if data_path.exists() or metadata_path.exists():
            raise FileExistsError(f"Stage 18.2 Raw already exists: {target}")
        target.mkdir(parents=True, exist_ok=True)
        data_tmp = target / "data.parquet.tmp"
        metadata_tmp = target / "metadata.json.tmp"
        if data_tmp.exists() or metadata_tmp.exists():
            raise FileExistsError(f"Stage 18.2 temporary Raw exists: {target}")
        record = dict(metadata)
        try:
            if frame is not None and not frame.empty:
                frame.to_parquet(data_tmp, index=False)
                record.update({
                    "row_count": int(len(frame)), "columns": [str(x) for x in frame.columns],
                    "column_count": int(len(frame.columns)), "schema_hash": schema_hash(frame),
                    "data_size_bytes": int(data_tmp.stat().st_size),
                    "data_sha256": file_sha256(data_tmp),
                })
            else:
                record.update({
                    "row_count": 0, "columns": [], "column_count": 0,
                    "schema_hash": "", "data_size_bytes": 0, "data_sha256": "",
                })
            metadata_tmp.write_text(
                json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            if data_tmp.exists():
                os.replace(data_tmp, data_path)
            os.replace(metadata_tmp, metadata_path)
        except Exception:
            for item in (data_tmp, metadata_tmp):
                if item.exists():
                    item.unlink()
            raise
        return {
            **record, "data_path": data_path if data_path.exists() else None,
            "metadata_path": metadata_path,
        }
