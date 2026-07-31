"""Append-only, atomic Parquet storage for Stage 3 Raw data."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd


def schema_hash(frame: pd.DataFrame | None) -> str:
    if frame is None:
        return ""
    payload = [
        {"name": str(column), "dtype": str(frame[column].dtype)}
        for column in frame.columns
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class RawStore:
    """Writes immutable files beneath a run_id partition."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def history_path(self, run_id: str, adjust: str, symbol: str) -> Path:
        label = "raw" if adjust == "" else adjust
        return (
            self.root
            / "stock_zh_a_hist"
            / f"run_id={run_id}"
            / f"adjust={label}"
            / f"symbol={symbol}"
            / "data.parquet"
        )

    def spot_path(self, run_id: str, snapshot_date: str, name: str) -> Path:
        return (
            self.root
            / "stock_zh_a_spot_em"
            / f"run_id={run_id}"
            / f"snapshot_date={snapshot_date}"
            / name
        )

    def financial_path(
        self, interface_name: str, run_id: str, symbol: str
    ) -> Path:
        """Return the immutable Stage 4 Raw path for one interface/symbol."""
        return (
            self.root
            / interface_name
            / f"run_id={run_id}"
            / f"symbol={symbol}"
            / "data.parquet"
        )

    def write_parquet(self, frame: pd.DataFrame, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(f"Raw path already exists: {destination}")
        temporary = destination.with_name(destination.name + ".tmp")
        if temporary.exists():
            raise FileExistsError(f"Temporary Raw path already exists: {temporary}")
        try:
            frame.to_parquet(temporary, index=False)
            os.replace(temporary, destination)
        except Exception:
            if temporary.exists():
                temporary.unlink()
            raise
        return destination


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: str | Path, project_root: str | Path) -> dict[str, Any]:
    item = Path(path)
    return {
        "path": item.resolve().relative_to(Path(project_root).resolve()).as_posix(),
        "size": item.stat().st_size,
        "sha256": file_sha256(item),
    }
