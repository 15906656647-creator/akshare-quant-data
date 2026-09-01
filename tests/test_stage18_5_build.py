from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from akshare_data_test.stage18_5_build import (
    FEATURE_DEFINITIONS, _load_pit_inputs, _validation_reports,
    build_features, run_stage18_5,
)
from akshare_data_test.stage18_5_config import FEATURE_NAMES, load_stage18_5_config
from akshare_data_test.stage18_audit import Stage18Blocked
from akshare_data_test.storage.raw_store import file_sha256
from akshare_data_test.storage.stage18_feature_store import Stage18FeatureStore


ROOT = Path(__file__).resolve().parents[1]
SOURCE_RUN = "b2d7bf6c-b7c7-4760-b16d-33640111cb11"


def test_stage185_config_freezes_read_only_pit_scope():
    config = load_stage18_5_config(ROOT / "config/stage18_5.yml")
    assert config.source_run_id == SOURCE_RUN
    assert config.database_sha256 == "ef095fbee26da64da43e19ea7da45f4d8924c9f3977f3c735f29926d70e0812b"
    assert config.feature_names == FEATURE_NAMES
    assert len(config.feature_names) == 12


def test_wrong_upstream_blocks_before_feature_write():
    before = sorted((ROOT / "data/features/stage18").rglob("*")) if (ROOT / "data/features/stage18").exists() else []
    with pytest.raises(Stage18Blocked, match="upstream run id"):
        run_stage18_5(
            root=ROOT, as_of_date=date(2026, 7, 27),
            upstream_run_id="00000000-0000-4000-8000-000000000000",
        )
    after = sorted((ROOT / "data/features/stage18").rglob("*")) if (ROOT / "data/features/stage18").exists() else []
    assert before == after


def test_validate_only_is_read_only_and_verifies_database_hash():
    config = load_stage18_5_config(ROOT / "config/stage18_5.yml")
    database = ROOT / config.database_path
    before = file_sha256(database)
    report, code = run_stage18_5(root=ROOT, as_of_date=date(2026, 7, 27), validate_only=True)
    assert code == 0 and report["status"] == "VALIDATED"
    assert report["feature_writes"] == 0 and report["pit_input_rows"] > 0
    assert file_sha256(database) == before


@pytest.fixture(scope="module")
def formal_feature_frame():
    config = load_stage18_5_config(ROOT / "config/stage18_5.yml")
    core, securities = _load_pit_inputs(ROOT / config.database_path, config.as_of_date)
    frame = build_features(
        core, securities, run_id="77777777-7777-4777-8777-777777777777",
        as_of_date=config.as_of_date,
    )
    return config, core, securities, frame


def test_feature_matrix_has_23_by_12_terminal_units_and_excludes_valuation(formal_feature_frame):
    _config, _core, securities, frame = formal_feature_frame
    assert len(securities) == 23 and len(frame) == 23 * 12
    assert frame["symbol"].nunique() == 23
    assert set(frame["feature_name"]) == set(FEATURE_NAMES)
    assert set(frame["feature_status"]) <= {"PASS", "UNAVAILABLE"}
    assert not frame["source_tables"].str.contains("valuation", regex=False).any()
    assert frame.loc[frame["market"] == "HK", "feature_status"].eq("UNAVAILABLE").all()
    assert frame.loc[frame["feature_status"] == "PASS", "lineage_json"].ne("[]").all()


def test_growth_uses_same_fiscal_period_prior_year(formal_feature_frame):
    _config, _core, _securities, frame = formal_feature_frame
    growth = frame[(frame["feature_name"].isin(["revenue_yoy", "net_profit_yoy"])) & (frame["feature_status"] == "PASS")]
    assert not growth.empty
    for lineage_json in growth["lineage_json"]:
        rows = json.loads(lineage_json)
        assert len(rows) == 2
        assert len({row["fiscal_period"] for row in rows}) == 1
        years = sorted(pd.Timestamp(row["report_date"]).year for row in rows)
        assert years[1] - years[0] == 1


def test_pit_quality_detects_future_lineage(formal_feature_frame):
    config, _core, _securities, frame = formal_feature_frame
    definitions = pd.DataFrame(FEATURE_DEFINITIONS)
    _coverage, pit, period, quality, failures = _validation_reports(frame, definitions, config)
    assert failures == []
    assert (pit["status"] == "PASS").all()
    assert (period["period_match_status"] == "PASS").all()
    assert (quality["quality_status"] == "PASS").all()
    changed = frame.copy()
    index = changed.index[changed["feature_status"] == "PASS"][0]
    lineage = json.loads(changed.at[index, "lineage_json"])
    lineage[0]["announcement_date"] = "2026-08-01T00:00:00"
    changed.at[index, "lineage_json"] = json.dumps(lineage)
    _coverage, pit, _period, _quality, failures = _validation_reports(changed, definitions, config)
    assert "pit_validation" in failures
    assert pit.loc[pit["check_name"] == "future_data_usage", "status"].iloc[0] == "FAIL"


def test_feature_store_is_append_only_and_hash_recomputable(tmp_path):
    store = Stage18FeatureStore(tmp_path)
    frame = pd.DataFrame({"symbol": ["000001"], "feature_name": ["revenue"], "feature_status": ["PASS"]})
    run_id = "66666666-6666-4666-8666-666666666666"
    stored = store.write(run_id=run_id, frame=frame, metadata={"status": "PASS"})
    assert file_sha256(stored["data_path"]) == stored["data_sha256"]
    with pytest.raises(FileExistsError):
        store.write(run_id=run_id, frame=frame, metadata={"status": "PASS"})
    assert not list(tmp_path.rglob("*.tmp"))
