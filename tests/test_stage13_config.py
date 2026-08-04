from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from akshare_data_test.stage13_config import load_stage13_config


ROOT = Path(__file__).resolve().parents[1]


def _mutated(tmp_path: Path, mutate) -> Path:
    raw = yaml.safe_load((ROOT / "config/stage13.yml").read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "stage13.yml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_stage13_config_loads_closed_contract():
    config = load_stage13_config(ROOT / "config/stage13.yml")
    assert config.raw["stage"] == 13
    assert config.raw["moving_averages"]["price"] == [3, 5, 7, 10, 13, 20, 21]


@pytest.mark.parametrize("mutate", [
    lambda raw: raw.update({"unknown": 1}),
    lambda raw: raw["presentation"].pop("image_dpi"),
    lambda raw: raw["presentation"].update({"image_dpi": True}),
    lambda raw: raw["presentation"].update({"image_dpi": 10}),
    lambda raw: raw["presentation"].update({"float_precision": 16}),
    lambda raw: raw["presentation"].update({"image_format": "svg"}),
    lambda raw: raw["presentation"].update({"overwrite": "false"}),
    lambda raw: raw["presentation"].update({"price_lookback_days": float("nan")}),
    lambda raw: raw["outputs"].update({"reports_dir": ".git/stage13"}),
    lambda raw: raw["moving_averages"].update({"price": [3, 5, 7, 10, 13, 20, 20]}),
    lambda raw: raw["moving_averages"].update({"volume": [20, 5]}),
])
def test_invalid_stage13_config_is_rejected(tmp_path, mutate):
    with pytest.raises((ValueError, TypeError)):
        load_stage13_config(_mutated(tmp_path, mutate))
