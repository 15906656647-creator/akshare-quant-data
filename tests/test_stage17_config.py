from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from akshare_data_test.config import ConfigError
from akshare_data_test.stage17_config import (
    EXPECTED_A_SHARES, EXPECTED_H_SHARES, load_stage17_config,
)


ROOT = Path(__file__).resolve().parents[1]


def test_stage17_config_freezes_exact_scope_and_counts():
    config = load_stage17_config(ROOT / "config/stage17.yml")
    assert tuple(target.symbol for target in config.equities[:16]) == EXPECTED_A_SHARES
    assert tuple(target.symbol for target in config.equities[16:]) == EXPECTED_H_SHARES
    assert config.daily_expected_count == 69
    assert config.crypto_intervals == ("1m", "3m", "5m", "15m", "1h", "1d")
    assert config.as_of_date.isoformat() == "2026-08-24"
    assert config.strict_listing_coverage


def test_stage17_config_fails_closed_on_unknown_key(tmp_path):
    path = tmp_path / "stage17.yml"
    shutil.copy2(ROOT / "config/stage17.yml", path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["surprise"] = True
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown"):
        load_stage17_config(path)


def test_stage17_config_rejects_provider_substitution(tmp_path):
    path = tmp_path / "stage17.yml"
    payload = yaml.safe_load((ROOT / "config/stage17.yml").read_text(encoding="utf-8"))
    payload["crypto"]["provider"] = "binance_public_api"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(ConfigError, match="exact OKX ETH-USDT"):
        load_stage17_config(path)

def test_stage17_config_rejects_equity_source_substitution(tmp_path):
    path = tmp_path / "stage17.yml"
    payload = yaml.safe_load((ROOT / "config/stage17.yml").read_text(encoding="utf-8"))
    payload["equity_daily"]["providers"]["h_share"]["fallback"]["source"] = "external"
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="provider policy differs"):
        load_stage17_config(path)
