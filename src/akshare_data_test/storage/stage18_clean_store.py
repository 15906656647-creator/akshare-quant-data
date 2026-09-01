"""Append-only atomic storage for Stage 18.3 canonical Clean datasets."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from .raw_store import file_sha256, schema_hash


class Stage18CleanStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def category_dir(self, run_id: str, category: str) -> Path:
        if not run_id or any(char in run_id for char in '\\/:*?"<>|'):
            raise ValueError(f"Unsafe Stage 18.3 run id: {run_id!r}")
        if not category or any(char in category for char in '\\/:*?"<>|'):
            raise ValueError(f"Unsafe Stage 18.3 category: {category!r}")
        return self.root / f"run_id={run_id}" / category

    def write(
        self,
        *,
        run_id: str,
        category: str,
        frame: pd.DataFrame,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if frame.empty:
            raise ValueError(f"Stage 18.3 Clean category is empty: {category}")
        target = self.category_dir(run_id, category)
        data_path = target / "data.parquet"
        metadata_path = target / "metadata.json"
        if data_path.exists() or metadata_path.exists():
            raise FileExistsError(f"Stage 18.3 Clean already exists: {target}")
        target.mkdir(parents=True, exist_ok=True)
        data_tmp = target / "data.parquet.tmp"
        metadata_tmp = target / "metadata.json.tmp"
        if data_tmp.exists() or metadata_tmp.exists():
            raise FileExistsError(f"Stage 18.3 temporary Clean exists: {target}")
        record = dict(metadata)
        try:
            frame.to_parquet(data_tmp, index=False)
            record.update({
                "row_count": int(len(frame)),
                "columns": [str(column) for column in frame.columns],
                "column_count": int(len(frame.columns)),
                "schema_hash": schema_hash(frame),
                "data_size_bytes": int(data_tmp.stat().st_size),
                "data_sha256": file_sha256(data_tmp),
            })
            metadata_tmp.write_text(
                json.dumps(record, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            os.replace(data_tmp, data_path)
            os.replace(metadata_tmp, metadata_path)
        except Exception:
            for item in (data_tmp, metadata_tmp):
                if item.exists():
                    item.unlink()
            raise
        return {**record, "data_path": data_path, "metadata_path": metadata_path}
