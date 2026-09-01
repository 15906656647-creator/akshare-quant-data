"""Append-only Parquet store for Stage 18.5 feature assets."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd

from .raw_store import file_sha256


class Stage18FeatureStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def write(self, *, run_id: str, frame: pd.DataFrame, metadata: dict[str, Any]) -> dict[str, Any]:
        target = self.root / f"run_id={run_id}"
        if target.exists():
            raise FileExistsError(f"Stage 18.5 feature run already exists: {target}")
        target.mkdir(parents=True, exist_ok=False)
        data_path = target / "fundamental_features.parquet"
        metadata_path = target / "metadata.json"
        data_tmp = target / ".data.tmp"
        metadata_tmp = target / ".metadata.tmp"
        try:
            frame.to_parquet(data_tmp, index=False)
            data_hash = file_sha256(data_tmp)
            payload = {
                **metadata,
                "row_count": int(len(frame)),
                "columns": list(frame.columns),
                "data_size_bytes": data_tmp.stat().st_size,
                "data_sha256": data_hash,
            }
            metadata_tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            os.replace(data_tmp, data_path)
            os.replace(metadata_tmp, metadata_path)
        except Exception:
            for item in (data_tmp, metadata_tmp):
                if item.exists():
                    item.unlink()
            raise
        return {
            "data_path": data_path,
            "metadata_path": metadata_path,
            "data_sha256": data_hash,
            "metadata_sha256": file_sha256(metadata_path),
            "row_count": int(len(frame)),
        }
