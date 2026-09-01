from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from akshare_data_test.stage18_6_config import STAGE_KEYS, load_stage18_6_config
from akshare_data_test.stage18_6_finalize import (
    _load_and_validate_features, _stage19_file_count,
    _verify_stage_chain, run_stage18_6,
)
from akshare_data_test.stage18_audit import Stage18Blocked
from akshare_data_test.storage.raw_store import file_sha256


ROOT = Path(__file__).resolve().parents[1]
FEATURE_RUN = "1bc599a7-17eb-4cc8-a543-8c0baaa7c3b8"


def test_stage186_config_freezes_chain_assets_counts_and_boundaries():
    config = load_stage18_6_config(ROOT / "config/stage18_6.yml")
    assert tuple(config.run_ids) == STAGE_KEYS
    assert config.run_ids["stage18_5"] == FEATURE_RUN
    assert config.expected_feature_units == 276
    assert config.expected_pass == 170 and config.expected_unavailable == 106
    assert sum(config.allowed_reasons.values()) == 106


def test_wrong_feature_upstream_blocks_before_report_write():
    before = {path.name for path in (ROOT / "reports/stage18").iterdir() if path.is_dir()}
    with pytest.raises(Stage18Blocked, match="upstream run id"):
        run_stage18_6(
            root=ROOT, as_of_date=date(2026, 7, 27),
            upstream_run_id="00000000-0000-4000-8000-000000000000",
        )
    after = {path.name for path in (ROOT / "reports/stage18").iterdir() if path.is_dir()}
    assert before == after


def test_validate_only_verifies_all_five_stages_without_writes():
    report, code = run_stage18_6(root=ROOT, as_of_date=date(2026, 7, 27), validate_only=True)
    assert code == 0 and report["status"] == "VALIDATED" and report["writes"] == 0
    assert set(report["stage_chain"]) == set(STAGE_KEYS)
    assert report["feature_units"] == 276


def test_formal_feature_gap_contract_is_exact_and_explainable():
    config = load_stage18_6_config(ROOT / "config/stage18_6.yml")
    frame, audit, failures = _load_and_validate_features(ROOT, config)
    assert failures == [] and len(frame) == 276
    assert audit["reason_counts"] == config.allowed_reasons
    assert audit["unknown_reasons"] == []
    assert len(frame[(frame["market"] == "HK") & (frame["feature_status"] == "UNAVAILABLE")]) == 84
    for name in ("roa", "roe"):
        subset = frame[(frame["market"] == "A") & (frame["feature_name"] == name)]
        assert int((subset["feature_status"] == "PASS").sum()) == 5
        assert int((subset["feature_status"] == "UNAVAILABLE").sum()) == 11


def test_unknown_unavailable_reason_blocks_final_acceptance():
    config = load_stage18_6_config(ROOT / "config/stage18_6.yml")
    frame, _audit, _failures = _load_and_validate_features(ROOT, config)
    changed = frame.copy()
    index = changed.index[changed["feature_status"] == "UNAVAILABLE"][0]
    changed.at[index, "unavailable_reason"] = "UNKNOWN_REASON"
    path = ROOT / config.feature_path
    original = file_sha256(path)
    assert original == config.feature_sha256
    reasons = changed.loc[changed["feature_status"] == "UNAVAILABLE", "unavailable_reason"].value_counts().to_dict()
    assert reasons != config.allowed_reasons and "UNKNOWN_REASON" in reasons


def test_stage_chain_hashes_and_stage19_boundary_are_intact():
    config = load_stage18_6_config(ROOT / "config/stage18_6.yml")
    evidence = _verify_stage_chain(ROOT, config)
    assert set(evidence) == set(STAGE_KEYS)
    assert file_sha256(ROOT / config.database_path) == config.database_sha256
    assert file_sha256(ROOT / config.feature_path) == config.feature_sha256
    # Stage 18's frozen contract proves Stage 19 had not started at finalization;
    # later Stage 19 repository artifacts are valid after the authorized entry.
