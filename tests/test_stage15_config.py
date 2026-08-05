from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from akshare_data_test.stage15_config import load_stage15_config


ROOT = Path(__file__).resolve().parents[1]


def _real_payload() -> dict[str, object]:
    return yaml.safe_load((ROOT / "config/stage15.yml").read_text(encoding="utf-8"))


def _write(tmp_path: Path, payload: dict[str, object]) -> Path:
    path = tmp_path / "stage15.yml"
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def test_real_config_loads(tmp_path: Path):
    config, digest = load_stage15_config(ROOT / "config/stage15.yml")
    assert config["stage"] == 15
    assert config["universe"]["expected_symbol_count"] == 16
    assert len(digest) == 64
    assert config["outputs"]["reports_dir"] == "reports/stage15"
    assert config["outputs"]["database_dir"] == "database/stage15"


def test_config_hash_is_reproducible(tmp_path: Path):
    first = load_stage15_config(ROOT / "config/stage15.yml")[1]
    second = load_stage15_config(ROOT / "config/stage15.yml")[1]
    assert first == second


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (lambda p: p.update({"stage": 14}), "stage15.stage must be 15"),
        (
            lambda p: p["universe"].update({"expected_symbol_count": 15}),
            "expected_symbol_count must be 16",
        ),
        (
            lambda p: p["outputs"].update({"reports_dir": "reports/stage14"}),
            "must be reports/stage15",
        ),
        (
            lambda p: p["inputs"].update({"stage5_database": "../secret.duckdb"}),
            "safe relative path",
        ),
        (
            lambda p: p["inputs"].update({"stage5_database": "C:/tmp/x.duckdb"}),
            "safe relative path",
        ),
        (
            lambda p: p["inputs"].update({"stage5_database": "data/raw/x.parquet"}),
            "protected directory",
        ),
        (
            lambda p: p["daily_checks"].update({"latest_trade_date_tolerance_days": 31}),
            "must not exceed 30",
        ),
        (
            lambda p: p["daily_checks"].update({"row_count_decline_ratio": 1.5}),
            "must not exceed 1.0",
        ),
        (
            lambda p: p["cross_validation"].update({"symbols": ["600000"]}),
            "outside the frozen universe",
        ),
        (
            lambda p: p["cross_validation"].update({"symbols": ["002067"]}),
            "must contain 2 or 3 symbols",
        ),
        (
            lambda p: p["performance"].update(
                {"max_elapsed_seconds": {"stock_zh_a_hist": 0.0}}
            ),
            "must be positive",
        ),
        (
            lambda p: p["quality"].update({"require_offline": False}),
            "quality safeguards must be enabled",
        ),
        (
            lambda p: p["stage8"].update({"block_whole_run": True}),
            "block_whole_run must be false",
        ),
    ],
)
def test_invalid_config_is_rejected(tmp_path: Path, mutate, fragment):
    payload = _real_payload()
    mutate(payload)
    with pytest.raises(ValueError, match=fragment):
        load_stage15_config(_write(tmp_path, payload))


def test_cross_validation_check_items_must_be_known(tmp_path: Path):
    payload = _real_payload()
    payload["cross_validation"]["check_items"].append("unknown_item")
    with pytest.raises(ValueError, match="unknown items"):
        load_stage15_config(_write(tmp_path, payload))


def test_missing_required_keys_rejected(tmp_path: Path):
    payload = _real_payload()
    del payload["risk"]
    with pytest.raises(ValueError, match="missing required keys"):
        load_stage15_config(_write(tmp_path, payload))
