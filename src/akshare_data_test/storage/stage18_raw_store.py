"""Append-only, atomic storage for Stage 18.1 capability evidence."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from .raw_store import file_sha256, schema_hash


def _safe(value: str) -> str:
    token = str(value)
    if not token or token in {".", ".."} or any(ch in token for ch in '\\/:*?"<>|'):
        raise ValueError(f"Unsafe Stage 18 partition value: {value!r}")
    return token


class Stage18RawStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def dataset_dir(
        self, *, run_id: str, category: str, market: str, symbol: str,
        interface: str, variant: str,
    ) -> Path:
        audit_id = hashlib.sha256(
            f"{interface}|{variant}".encode("utf-8")
        ).hexdigest()[:12]
        return (
            self.root / f"run_id={_safe(run_id)}" / _safe(category)
            / f"market={_safe(market)}" / f"symbol={_safe(symbol)}"
            / f"audit={audit_id}"
        )

    def write(
        self, frame: pd.DataFrame | None, directory: str | Path,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        target = Path(directory)
        data_path = target / "data.parquet"
        metadata_path = target / "metadata.json"
        if data_path.exists() or metadata_path.exists():
            raise FileExistsError(f"Stage 18.1 Raw evidence already exists: {target}")
        target.mkdir(parents=True, exist_ok=True)
        data_tmp = target / "data.parquet.tmp"
        metadata_tmp = target / "metadata.json.tmp"
        if data_tmp.exists() or metadata_tmp.exists():
            raise FileExistsError(f"Stage 18.1 temporary evidence exists: {target}")
        record = dict(metadata)
        try:
            if frame is not None and not frame.empty:
                frame.to_parquet(data_tmp, index=False)
                record.update({
                    "row_count": int(len(frame)),
                    "column_count": int(len(frame.columns)),
                    "schema_hash": schema_hash(frame),
                    "data_size_bytes": int(data_tmp.stat().st_size),
                    "data_sha256": file_sha256(data_tmp),
                })
            else:
                record.update({
                    "row_count": 0,
                    "column_count": 0 if frame is None else int(len(frame.columns)),
                    "schema_hash": "" if frame is None else schema_hash(frame),
                    "data_size_bytes": 0,
                    "data_sha256": "",
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
            **record,
            "data_path": data_path if data_path.exists() else None,
            "metadata_path": metadata_path,
        }
