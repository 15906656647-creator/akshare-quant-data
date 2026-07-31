CREATE SCHEMA IF NOT EXISTS feature;
CREATE SCHEMA IF NOT EXISTS analysis;
CREATE SCHEMA IF NOT EXISTS quality;

CREATE TABLE IF NOT EXISTS feature.feature_stock_daily (
    symbol VARCHAR NOT NULL,
    exchange VARCHAR,
    trade_date DATE NOT NULL,
    adjust_type VARCHAR NOT NULL,
    close DOUBLE,
    prev_close DOUBLE,
    return_1d DOUBLE,
    ma_3 DOUBLE,
    ma_5 DOUBLE,
    ma_7 DOUBLE,
    ma_10 DOUBLE,
    ma_13 DOUBLE,
    ma_20 DOUBLE,
    ma_21 DOUBLE,
    volume_ma_5 DOUBLE,
    volume_ma_20 DOUBLE,
    volume_ratio_20 DOUBLE,
    intraday_range DOUBLE,
    gap_return DOUBLE,
    volatility_20 DOUBLE,
    is_volume_spike BOOLEAN,
    is_large_move BOOLEAN,
    source_fetched_at TIMESTAMPTZ,
    calculated_at TIMESTAMPTZ NOT NULL,
    run_id VARCHAR NOT NULL,
    PRIMARY KEY (symbol, trade_date, adjust_type)
);

CREATE TABLE IF NOT EXISTS analysis.analysis_stock_activity (
    symbol VARCHAR NOT NULL,
    as_of_date DATE NOT NULL,
    lookback_days INTEGER NOT NULL,
    observation_count INTEGER NOT NULL,
    avg_amount_120d DOUBLE,
    avg_turnover_120d DOUBLE,
    avg_amplitude_120d DOUBLE,
    avg_volatility_20_120d DOUBLE,
    volume_spike_frequency DOUBLE,
    large_move_frequency DOUBLE,
    gap_frequency DOUBLE,
    amount_percentile DOUBLE,
    turnover_percentile DOUBLE,
    volatility_percentile DOUBLE,
    volume_spike_percentile DOUBLE,
    large_move_percentile DOUBLE,
    event_frequency_percentile DOUBLE,
    liquidity_component DOUBLE,
    turnover_component DOUBLE,
    volatility_component DOUBLE,
    volume_spike_component DOUBLE,
    large_move_component DOUBLE,
    event_component DOUBLE,
    activity_score DOUBLE,
    score_status VARCHAR NOT NULL,
    score_version VARCHAR NOT NULL,
    event_component_source VARCHAR NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL,
    run_id VARCHAR NOT NULL,
    PRIMARY KEY (symbol, as_of_date)
);

CREATE TABLE IF NOT EXISTS quality.data_quality_result (
    run_id VARCHAR NOT NULL,
    check_name VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    severity VARCHAR NOT NULL,
    observed_value VARCHAR,
    expected_value VARCHAR,
    details VARCHAR,
    calculated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, check_name)
);
