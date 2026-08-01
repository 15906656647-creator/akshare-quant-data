CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS clean;
CREATE SCHEMA IF NOT EXISTS feature;
CREATE SCHEMA IF NOT EXISTS analysis;
CREATE SCHEMA IF NOT EXISTS quality;
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS raw.financial_statement (
    run_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL, statement_type VARCHAR NOT NULL,
    report_period DATE NOT NULL, announcement_date DATE, update_time TIMESTAMPTZ,
    source_name VARCHAR NOT NULL, source_reference VARCHAR NOT NULL,
    source_run_id VARCHAR NOT NULL, source_column VARCHAR NOT NULL,
    source_item_code VARCHAR NOT NULL, source_item_name VARCHAR NOT NULL,
    source_value DOUBLE, source_unit VARCHAR, cumulative_flag BOOLEAN NOT NULL,
    version VARCHAR NOT NULL, version_key VARCHAR NOT NULL,
    PRIMARY KEY (run_id, symbol, statement_type, report_period, source_column, version_key)
);

CREATE TABLE IF NOT EXISTS clean.financial_fact (
    run_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL, statement_type VARCHAR NOT NULL,
    report_period DATE NOT NULL, announcement_date DATE, update_time TIMESTAMPTZ,
    item_code VARCHAR NOT NULL, source_field VARCHAR NOT NULL,
    selected_source VARCHAR NOT NULL, conflict_flag BOOLEAN NOT NULL,
    conflict_value_mismatch BOOLEAN NOT NULL, item_value DOUBLE,
    cumulative_value DOUBLE,
    single_quarter_value DOUBLE, period_type VARCHAR NOT NULL,
    conversion_status VARCHAR NOT NULL, unit VARCHAR NOT NULL,
    cumulative_flag BOOLEAN NOT NULL, source_name VARCHAR NOT NULL,
    source_reference VARCHAR NOT NULL, source_run_id VARCHAR NOT NULL,
    version VARCHAR NOT NULL, version_key VARCHAR NOT NULL,
    PRIMARY KEY (run_id, symbol, statement_type, report_period, item_code, version_key)
);

CREATE TABLE IF NOT EXISTS feature.fundamental_indicator (
    run_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL, report_period DATE NOT NULL,
    indicator_code VARCHAR NOT NULL, indicator_value DOUBLE,
    calculation_status VARCHAR NOT NULL, calculation_version VARCHAR NOT NULL,
    source_period_start DATE, source_period_end DATE, created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, symbol, report_period, indicator_code)
);

CREATE TABLE IF NOT EXISTS analysis.fundamental_summary (
    run_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL, as_of_date DATE NOT NULL,
    revenue_growth DOUBLE, profit_growth DOUBLE, profitability_score DOUBLE,
    financial_health_score DOUBLE, valuation_status VARCHAR NOT NULL,
    summary_explanation VARCHAR NOT NULL, model_version VARCHAR NOT NULL,
    config_version VARCHAR NOT NULL, publication_status VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, symbol, as_of_date)
);

CREATE TABLE IF NOT EXISTS analysis.valuation_snapshot (
    run_id VARCHAR NOT NULL, snapshot_time TIMESTAMPTZ NOT NULL,
    symbol VARCHAR NOT NULL, pe DOUBLE, pb DOUBLE, market_cap DOUBLE,
    source VARCHAR NOT NULL, valuation_type VARCHAR NOT NULL,
    pe_status VARCHAR NOT NULL, pb_status VARCHAR NOT NULL,
    valuation_status VARCHAR NOT NULL,
    source_run_id VARCHAR NOT NULL, created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, snapshot_time, symbol, source_run_id)
);

CREATE TABLE IF NOT EXISTS quality.stage10_quality_result (
    run_id VARCHAR NOT NULL, check_name VARCHAR NOT NULL, severity VARCHAR NOT NULL,
    status VARCHAR NOT NULL, observed_value VARCHAR, expected_value VARCHAR,
    numerator BIGINT, denominator BIGINT, message VARCHAR,
    checked_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (run_id, check_name)
);

CREATE TABLE IF NOT EXISTS audit.stage10_run (
    run_id VARCHAR PRIMARY KEY, run_status VARCHAR NOT NULL,
    publication_status VARCHAR NOT NULL, started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ, input_database VARCHAR NOT NULL,
    output_database VARCHAR NOT NULL, as_of_date DATE NOT NULL,
    symbol_count INTEGER NOT NULL, raw_row_count BIGINT NOT NULL,
    fact_row_count BIGINT NOT NULL, indicator_row_count BIGINT NOT NULL,
    summary_row_count BIGINT NOT NULL, valuation_row_count BIGINT NOT NULL,
    quality_passed INTEGER NOT NULL, quality_failed INTEGER NOT NULL,
    blocking_reasons_json VARCHAR NOT NULL, config_hash VARCHAR NOT NULL,
    calculation_version VARCHAR NOT NULL, model_version VARCHAR NOT NULL,
    output_type VARCHAR NOT NULL, manifest_json VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE OR REPLACE VIEW clean.v_latest_financial_fact AS
SELECT fact.* FROM clean.financial_fact AS fact
JOIN (SELECT run_id FROM audit.stage10_run WHERE run_status='PASS'
      ORDER BY created_at DESC, run_id DESC LIMIT 1) latest USING (run_id);

CREATE OR REPLACE VIEW feature.v_latest_fundamental_indicator AS
SELECT indicator.* FROM feature.fundamental_indicator AS indicator
JOIN (SELECT run_id FROM audit.stage10_run WHERE run_status='PASS'
      ORDER BY created_at DESC, run_id DESC LIMIT 1) latest USING (run_id);

CREATE OR REPLACE VIEW analysis.v_latest_fundamental_summary AS
SELECT summary.* FROM analysis.fundamental_summary AS summary
JOIN (SELECT run_id FROM audit.stage10_run WHERE run_status='PASS'
      ORDER BY created_at DESC, run_id DESC LIMIT 1) latest USING (run_id);

CREATE OR REPLACE VIEW analysis.v_latest_valuation_snapshot AS
SELECT valuation.* FROM analysis.valuation_snapshot AS valuation
JOIN (SELECT run_id FROM audit.stage10_run WHERE run_status='PASS'
      ORDER BY created_at DESC, run_id DESC LIMIT 1) latest USING (run_id);
