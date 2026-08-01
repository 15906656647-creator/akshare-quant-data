from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = [
    ROOT / "src/akshare_data_test/style_features.py",
    ROOT / "src/akshare_data_test/style_classification.py",
    ROOT / "src/akshare_data_test/stage9_build.py",
    ROOT / "src/akshare_data_test/storage/style_repository.py",
    ROOT / "src/akshare_data_test/quality/style_checks.py",
]


def test_stage9_runtime_has_no_network_clients_or_future_date_defaults():
    text = "\n".join(path.read_text(encoding="utf-8") for path in RUNTIME)
    prohibited = [r"\bimport\s+akshare", r"\bimport\s+requests", r"\bimport\s+httpx", r"urllib\.request", r"datetime\.now\("]
    assert not any(re.search(pattern, text) for pattern in prohibited)


def test_config_owns_windows_thresholds_and_stage8_null_policy():
    config = yaml.safe_load((ROOT / "config/stage9.yml").read_text(encoding="utf-8"))
    assert config["windows"] == [20, 40, 60]
    assert config["primary_window"] == 40
    assert config["price_adjust_type"] == "qfq"
    assert config["stage8"]["blocked_formal_value"] is None
    assert 1 <= config["breakout"]["confirmation_days"] <= 3
    assert config["schema_version"] == "1.1.0"
    assert config["model_version"] == "stage9_style_rules_v2"
    classification = config["classification"]
    assert {"weights", "scales", "confidence", "numeric_epsilon"}.issubset(
        classification
    )
    assert all(
        abs(sum(style.values()) - 1.0) < 1e-12
        for style in classification["weights"].values()
    )


def test_no_deterministic_actor_or_investment_language_in_runtime():
    output_modules = RUNTIME[:3]
    text = "\n".join(path.read_text(encoding="utf-8") for path in output_modules)
    for forbidden in ("主力正在洗盘", "庄家操纵", "确定存在主力行为", "必然上涨", "买入信号"):
        assert forbidden not in text
    assert "疑似主力行为特征" in text


def test_stage9_cli_help_is_available():
    result = subprocess.run([sys.executable, "run_pipeline.py", "analyze-style", "--help"], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0
    assert "--validate-only" in result.stdout and "--stage8-database" in result.stdout
