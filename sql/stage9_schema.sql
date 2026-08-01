CREATE SCHEMA IF NOT EXISTS feature;
CREATE SCHEMA IF NOT EXISTS analysis;
CREATE SCHEMA IF NOT EXISTS quality;
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS feature.stage9_style_feature (
    symbol VARCHAR NOT NULL, as_of_date DATE NOT NULL, window_size INTEGER NOT NULL,
    price_adjust_type VARCHAR NOT NULL, observation_count INTEGER NOT NULL,
    window_start DATE, window_end DATE, rolling_high DOUBLE, rolling_low DOUBLE,
    box_width DOUBLE, close_position_in_box DOUBLE, distance_to_upper_bound DOUBLE,
    distance_to_lower_bound DOUBLE, upper_touch_count INTEGER, lower_touch_count INTEGER,
    middle_zone_ratio DOUBLE, breakout_up_count INTEGER, breakout_down_count INTEGER,
    linear_slope DOUBLE, normalized_slope DOUBLE, regression_r_squared DOUBLE,
    trend_direction VARCHAR, slope_stability DOUBLE, realized_volatility DOUBLE,
    annualized_volatility DOUBLE, average_amplitude DOUBLE, atr DOUBLE,
    atr_ratio DOUBLE, bollinger_band_width DOUBLE, rolling_max_drawdown DOUBLE,
    average_recovery_days DOUBLE, large_move_frequency DOUBLE, average_amount DOUBLE,
    average_turnover DOUBLE, volume_ma DOUBLE, amount_ma DOUBLE,
    volume_trend_slope DOUBLE, amount_trend_slope DOUBLE,
    volume_contraction_ratio DOUBLE, volume_spike_frequency DOUBLE,
    high_turnover_frequency DOUBLE, price_volume_correlation DOUBLE,
    up_day_volume_ratio DOUBLE, down_day_volume_ratio DOUBLE,
    long_upper_shadow_frequency DOUBLE, long_lower_shadow_frequency DOUBLE,
    large_body_frequency DOUBLE, small_body_frequency DOUBLE,
    high_low_range_frequency DOUBLE, positive_large_move_frequency DOUBLE,
    negative_large_move_frequency DOUBLE, alternating_direction_frequency DOUBLE,
    confirmed_false_breakout_up_count INTEGER,
    confirmed_false_breakout_down_count INTEGER, pending_breakout_count INTEGER,
    breakout_with_volume_count INTEGER, breakout_return_to_box_days DOUBLE,
    failed_breakout_frequency DOUBLE, stage8_publication_status VARCHAR,
    stage8_formal_event_frequency DOUBLE, stage8_candidate_event_frequency DOUBLE,
    stage8_proxy_event_frequency DOUBLE, stage8_gap_proxy_frequency DOUBLE,
    stage8_unresolved_event_frequency DOUBLE, data_quality_status VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL, created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, symbol, as_of_date, window_size)
);

CREATE TABLE IF NOT EXISTS analysis.stage9_style_profile (
    symbol VARCHAR NOT NULL, as_of_date DATE NOT NULL, primary_window INTEGER NOT NULL,
    style_label VARCHAR NOT NULL, confidence DOUBLE NOT NULL,
    secondary_style_label VARCHAR, secondary_confidence DOUBLE,
    evidence_count INTEGER NOT NULL, conflicting_evidence_count INTEGER NOT NULL,
    data_coverage DOUBLE NOT NULL, explanation VARCHAR NOT NULL,
    model_version VARCHAR NOT NULL, config_version VARCHAR NOT NULL,
    publication_status VARCHAR NOT NULL, run_id VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, symbol, as_of_date)
);

CREATE TABLE IF NOT EXISTS quality.stage9_quality_result (
    run_id VARCHAR NOT NULL, check_name VARCHAR NOT NULL, severity VARCHAR NOT NULL,
    status VARCHAR NOT NULL, observed_value VARCHAR, expected_value VARCHAR,
    numerator BIGINT, denominator BIGINT, message VARCHAR, checked_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, check_name)
);

CREATE TABLE IF NOT EXISTS audit.stage9_run (
    run_id VARCHAR PRIMARY KEY, run_status VARCHAR NOT NULL,
    publication_status VARCHAR NOT NULL, started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ, input_database VARCHAR NOT NULL,
    input_table VARCHAR, output_database VARCHAR NOT NULL, as_of_date DATE NOT NULL,
    window_start DATE, window_end DATE, symbol_count INTEGER NOT NULL,
    feature_row_count INTEGER NOT NULL, profile_row_count INTEGER NOT NULL,
    quality_passed INTEGER NOT NULL, quality_failed INTEGER NOT NULL,
    blocking_reasons_json VARCHAR NOT NULL, config_hash VARCHAR NOT NULL,
    code_version VARCHAR NOT NULL, output_type VARCHAR NOT NULL,
    stage8_publication_status VARCHAR, manifest_json VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE OR REPLACE VIEW feature.v_latest_stage9_style_feature AS
SELECT feature.* FROM feature.stage9_style_feature AS feature
JOIN (
    SELECT run_id FROM audit.stage9_run WHERE run_status = 'PASS'
    ORDER BY created_at DESC, run_id DESC LIMIT 1
) latest USING (run_id);

CREATE OR REPLACE VIEW analysis.v_latest_stage9_style_profile AS
SELECT profile.* FROM analysis.stage9_style_profile AS profile
JOIN (
    SELECT run_id FROM audit.stage9_run WHERE run_status = 'PASS'
    ORDER BY created_at DESC, run_id DESC LIMIT 1
) latest USING (run_id);

