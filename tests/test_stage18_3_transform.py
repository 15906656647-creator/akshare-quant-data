from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from akshare_data_test.stage18_3_config import load_stage18_3_config
from akshare_data_test.stage18_3_transform import (
    _apply_field_mapping,
    _finalize_history,
    _history_source_long,
    _mapping_lookup,
    _period_values,
    _pit_status,
    _unit_info,
    deduplicate_hk_variants,
    run_stage18_3_standardization,
)
from akshare_data_test.stage18_audit import Stage18Blocked
from akshare_data_test.storage.stage18_clean_store import Stage18CleanStore


ROOT = Path(__file__).resolve().parents[1]
SOURCE_RUN = "df86486a-9a54-4920-a4db-2553f907af92"


def test_stage183_config_freezes_scope_and_write_boundaries():
    config = load_stage18_3_config(ROOT / "config/stage18_3.yml")
    assert config.source_run_id == SOURCE_RUN
    assert config.expected_dataset_count == 175
    assert config.expected_security_count == 23
    assert config.categories == (
        "financial_abstract", "financial_indicator", "balance_sheet",
        "income_statement", "cash_flow_statement", "valuation_snapshot",
    )
    assert set(config.required_core_fields).issubset(
        {item.canonical_name for item in config.mappings}
    )


def test_financial_abstract_wide_to_long_preserves_source_and_is_not_pit_eligible():
    config = load_stage18_3_config(ROOT / "config/stage18_3.yml")
    unit = {
        "market": "A", "symbol": "000100", "category": "financial_abstract",
        "provider": "Sina", "interface": "stock_financial_abstract",
        "variant": "default", "dataset_id": "unit", "sha256": "abc",
    }
    frame = pd.DataFrame({
        "选项": ["常用指标", "常用指标"],
        "指标": ["营业总收入", "归母净利润"],
        "20250630": [123.0, 12.0], "20251231": [456.0, 45.0],
    })
    long = _history_source_long(unit, frame, {}, config)
    long, _ = _apply_field_mapping(long, _mapping_lookup(config))
    clean = _finalize_history(long, "33333333-3333-4333-8333-333333333333")
    assert len(clean) == 4
    assert set(clean["canonical_name"]) == {"revenue", "parent_net_profit"}
    assert set(clean["period_type"]) == {"SEMIANNUAL", "ANNUAL"}
    assert set(clean["pit_status"]) == {"ANNOUNCEMENT_DATE_UNAVAILABLE"}
    assert not clean["eligible_for_as_of_date_analysis"].any()
    assert set(clean["source_metric_name"]) == {"营业总收入", "归母净利润"}


def test_pit_governance_uses_announcement_and_update_not_report_date():
    announcement = pd.Series([
        pd.NaT, pd.Timestamp("2026-08-01"), pd.Timestamp("2026-07-01"),
        pd.Timestamp("2026-07-01"), pd.Timestamp("2026-07-01"),
    ])
    update = pd.Series([
        pd.NaT, pd.Timestamp("2026-08-02"), pd.NaT,
        pd.Timestamp("2026-08-01"), pd.Timestamp("2026-07-20"),
    ])
    status, eligible = _pit_status(announcement, update, date(2026, 7, 27))
    assert status.tolist() == [
        "ANNOUNCEMENT_DATE_UNAVAILABLE", "FUTURE_AS_OF_DATE",
        "UPDATE_DATE_UNAVAILABLE", "UPDATE_AFTER_AS_OF_DATE", "PIT_ELIGIBLE",
    ]
    assert eligible.tolist() == [False, False, False, False, True]


def test_period_and_unit_governance_preserve_original_scale():
    periods = _period_values(pd.Series(["2026-03-31", "2026-06-30", "2026-09-30", "2026-12-31"]))
    assert periods["fiscal_period"].tolist() == ["Q1", "H1", "Q3", "FY"]
    assert _unit_info(
        market="A", category="financial_abstract", source_field="营业收入(万元)",
        currency="CNY", explicit_unit=None,
    ) == ("CNY_10k", "CNY", 10000.0)
    assert _unit_info(
        market="HK", category="financial_indicator", source_field="ROE(%)",
        currency="HKD", explicit_unit=None,
    ) == ("percent", "percent", 1.0)


def _duplicate_frame(second_value: float) -> pd.DataFrame:
    return pd.DataFrame({
        "symbol": ["02076.HK", "02076.HK"],
        "data_category": ["balance_sheet", "balance_sheet"],
        "report_date": pd.to_datetime(["2025-12-31", "2025-12-31"]),
        "source_field": ["004009999", "004009999"],
        "source_variant": ["annual", "report_period"],
        "normalized_value": [100.0, second_value],
        "source_dataset_id": ["annual-id", "report-id"],
        "source_sha256": ["a", "b"],
        "canonical_name": ["total_assets", "total_assets"],
    })


def test_hk_equivalent_duplicate_prefers_report_period_and_keeps_lineage():
    clean, conflicts = deduplicate_hk_variants(
        _duplicate_frame(100.0), priority=("report_period", "annual"),
        rtol=1e-9, atol=1e-6,
    )
    assert conflicts == [] and len(clean) == 1
    assert clean.iloc[0]["source_variant"] == "report_period"
    assert clean.iloc[0]["dedup_status"] == "equivalent_duplicate"
    assert json.loads(clean.iloc[0]["source_dataset_ids"]) == ["annual-id", "report-id"]


def test_hk_value_conflict_is_not_silently_deduplicated():
    _clean, conflicts = deduplicate_hk_variants(
        _duplicate_frame(101.0), priority=("report_period", "annual"),
        rtol=1e-9, atol=1e-6,
    )
    assert len(conflicts) == 1
    assert conflicts[0]["status"] == "value_conflict"


def test_clean_store_is_append_only_and_hashes_data(tmp_path):
    store = Stage18CleanStore(tmp_path)
    frame = pd.DataFrame({"symbol": ["000100"], "value": [1.0]})
    stored = store.write(
        run_id="44444444-4444-4444-8444-444444444444",
        category="financial_indicator", frame=frame,
        metadata={"status": "PASS"},
    )
    assert stored["data_sha256"]
    with pytest.raises(FileExistsError):
        store.write(
            run_id="44444444-4444-4444-8444-444444444444",
            category="financial_indicator", frame=frame,
            metadata={"status": "PASS"},
        )


def test_wrong_date_or_upstream_blocks_before_clean_writes():
    with pytest.raises(Stage18Blocked, match="as-of date"):
        run_stage18_3_standardization(
            root=ROOT, as_of_date=date(2026, 7, 26), validate_only=True,
        )
    with pytest.raises(Stage18Blocked, match="upstream run id"):
        run_stage18_3_standardization(
            root=ROOT, as_of_date=date(2026, 7, 27),
            upstream_run_id="00000000-0000-4000-8000-000000000000", validate_only=True,
        )
