CREATE SCHEMA IF NOT EXISTS analysis;
CREATE SCHEMA IF NOT EXISTS quality;
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS analysis.stage12_active_stock (
    run_id VARCHAR NOT NULL, instrument VARCHAR NOT NULL, as_of_date DATE NOT NULL,
    lookback_start DATE, valid_days INTEGER NOT NULL, average_volume DOUBLE,
    average_amount DOUBLE, average_turnover DOUBLE, zero_volume_ratio DOUBLE,
    volume_percentile DOUBLE, amount_percentile DOUBLE, turnover_percentile DOUBLE,
    activity_score DOUBLE, activity_rank DOUBLE, is_active BOOLEAN NOT NULL,
    reason_codes_json VARCHAR NOT NULL, created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, instrument, as_of_date)
);

CREATE TABLE IF NOT EXISTS analysis.stage12_volume_breakout (
    run_id VARCHAR NOT NULL, instrument VARCHAR NOT NULL, as_of_date DATE NOT NULL,
    observation_date DATE NOT NULL, baseline_start DATE, baseline_end DATE,
    baseline_observations INTEGER NOT NULL, current_volume DOUBLE NOT NULL,
    historical_mean_volume DOUBLE, historical_median_volume DOUBLE,
    historical_std_volume DOUBLE, volume_ratio_to_mean DOUBLE,
    volume_ratio_to_median DOUBLE, volume_zscore DOUBLE, price_return DOUBLE,
    amount_change DOUBLE, breakout_rule VARCHAR NOT NULL,
    is_volume_breakout BOOLEAN NOT NULL, reason_codes_json VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, instrument, as_of_date)
);

CREATE TABLE IF NOT EXISTS analysis.stage12_range_bound (
    run_id VARCHAR NOT NULL, instrument VARCHAR NOT NULL, as_of_date DATE NOT NULL,
    window_start DATE, window_end DATE, observations INTEGER NOT NULL,
    window_high DOUBLE, window_low DOUBLE, window_mid DOUBLE, range_width DOUBLE,
    range_width_pct DOUBLE, trend_slope DOUBLE, trend_slope_pct DOUBLE,
    trend_r2 DOUBLE, close_position DOUBLE, outside_ratio DOUBLE,
    is_range_bound BOOLEAN NOT NULL, reason_codes_json VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, instrument, as_of_date)
);

CREATE TABLE IF NOT EXISTS analysis.stage12_fundamental_price_volume (
    run_id VARCHAR NOT NULL, instrument VARCHAR NOT NULL, as_of_date DATE NOT NULL,
    fundamental_as_of_date DATE, fundamental_score DOUBLE, valuation_score DOUBLE,
    profitability_score DOUBLE, growth_score DOUBLE, quality_score DOUBLE,
    activity_score DOUBLE, volume_breakout_score DOUBLE, range_bound_score DOUBLE,
    price_momentum_score DOUBLE, composite_score DOUBLE, signal_label VARCHAR NOT NULL,
    reason_codes_json VARCHAR NOT NULL, data_completeness DOUBLE NOT NULL,
    fundamental_data_completeness DOUBLE NOT NULL, created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, instrument, as_of_date)
);

CREATE TABLE IF NOT EXISTS quality.stage12_quality_result (
    run_id VARCHAR NOT NULL, check_name VARCHAR NOT NULL, severity VARCHAR NOT NULL,
    status VARCHAR NOT NULL, observed_value VARCHAR, expected_value VARCHAR,
    message VARCHAR, checked_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, check_name)
);

CREATE TABLE IF NOT EXISTS audit.stage12_run (
    run_id VARCHAR PRIMARY KEY, run_status VARCHAR NOT NULL, stage INTEGER NOT NULL,
    as_of_date DATE NOT NULL, started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL, input_sha256 VARCHAR NOT NULL,
    config_sha256 VARCHAR NOT NULL, canonical_sha256 VARCHAR NOT NULL,
    blocking_reasons_json VARCHAR NOT NULL, warnings_json VARCHAR NOT NULL,
    manifest_json VARCHAR NOT NULL, created_at TIMESTAMPTZ NOT NULL
);

CREATE OR REPLACE VIEW analysis.v_latest_stage12_fundamental_price_volume AS
SELECT result.* FROM analysis.stage12_fundamental_price_volume result
JOIN (SELECT run_id FROM audit.stage12_run WHERE run_status='READY'
      ORDER BY created_at DESC, run_id DESC LIMIT 1) latest USING (run_id);
