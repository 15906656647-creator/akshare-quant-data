from pathlib import Path

import pandas as pd

from akshare_data_test.stage16_report import (
    COMPLETE, NOT_APPLICABLE, PARTIAL, UNPUBLISHABLE,
    _availability_matrix, _crypto_coverage, _stock_coverage,
    build_stage16_report, load_stage16_config, validate_stage16_inputs,
)


ROOT = Path(__file__).resolve().parents[1]


def test_stage16_config_locks_scope_and_excludes_hk():
    config = load_stage16_config(ROOT / "config/stage16.yml")
    assert config.raw["scope"]["expected_stock_count"] == 16
    assert config.raw["scope"]["exclude_hong_kong"] is True
    assert config.raw["scope"]["crypto_pair"] == "ETHUSDT"


def test_stage16_real_inputs_validate_offline():
    result = validate_stage16_inputs(
        root=ROOT,
        config_path=ROOT / "config/stage16.yml",
        as_of_date=pd.Timestamp("2026-07-27"),
    )
    assert result["status"] == "READY"
    assert result["symbol_count"] == 16
    assert result["hong_kong_symbol_count"] == 0
    assert result["network_attempts"] == 0


def test_stage16_dry_run_writes_nothing(tmp_path: Path):
    result, code = build_stage16_report(
        root=ROOT,
        as_of_date=pd.Timestamp("2026-07-27"),
        config_path=ROOT / "config/stage16.yml",
        reports_dir=ROOT / "reports/stage16",
        run_id="11111111-1111-4111-8111-111111111111",
        dry_run=True,
    )
    assert code == 0
    assert result["status"] == "READY"
    assert result["dry_run"] is True
    assert not (ROOT / "reports/stage16/11111111-1111-4111-8111-111111111111").exists()


def test_stage16_real_coverage_has_required_scope_and_statuses():
    config = load_stage16_config(ROOT / "config/stage16.yml")
    cutoff = pd.Timestamp("2026-07-27")
    stocks = _stock_coverage(ROOT, config, cutoff)
    crypto = _crypto_coverage(ROOT, config, cutoff)
    matrix = _availability_matrix(stocks, crypto)

    assert len(stocks) == 16
    assert set(stocks.exchange) == {"SH", "SZ"}
    assert not stocks.symbol.str.contains("HK", case=False, regex=False).any()
    assert stocks.qfq_rows.sum() == 11602
    assert stocks.raw_rows.sum() == 11602
    assert stocks.latest_report_period.max() == pd.Timestamp("2026-03-31")
    assert set(stocks.moving_average_status) == {COMPLETE}
    assert stocks.moving_average_note.str.contains("预热规则", regex=False).all()
    assert set(stocks.valuation_status) == {PARTIAL}
    assert set(stocks.limit_event_status) == {UNPUBLISHABLE}
    assert set(stocks.suspected_behavior_status) == {"证据不足"}
    assert {
        "abnormal_volume_evidence", "turnover_change_evidence",
        "fund_flow_persistence_evidence", "price_volume_divergence_evidence",
        "limit_event_evidence", "confidence_score", "evidence_summary",
    } <= set(stocks.columns)
    assert int(stocks.loc[stocks.symbol.eq("600438"), "qfq_rows"].iloc[0]) == 716
    assert int(stocks.loc[stocks.symbol.eq("601500"), "qfq_rows"].iloc[0]) == 722
    assert crypto.iloc[0].symbol == "ETHUSDT"
    assert crypto.iloc[0].source == "okx_public_api"
    assert int(crypto.iloc[0].raw_rows) == 960
    assert NOT_APPLICABLE in set(matrix.status)


def test_stage16_report_language_is_non_deterministic_about_behavior():
    source = (ROOT / "src/akshare_data_test/stage16_report.py").read_text(encoding="utf-8")
    assert "疑似主力行为特征" in source
    assert "不构成投资建议" in source
    assert "港股：明确排除" in source
