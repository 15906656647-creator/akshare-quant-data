CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS clean;
CREATE SCHEMA IF NOT EXISTS feature;
CREATE SCHEMA IF NOT EXISTS analysis;
CREATE SCHEMA IF NOT EXISTS quality;
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS raw.crypto_market_data (
    requested_instrument VARCHAR NOT NULL, raw_instrument VARCHAR NOT NULL,
    normalized_instrument VARCHAR NOT NULL, data_provider VARCHAR NOT NULL,
    raw_exchange VARCHAR NOT NULL, normalized_exchange VARCHAR NOT NULL,
    instrument_type VARCHAR NOT NULL, bar_interval VARCHAR NOT NULL,
    confirmed BOOLEAN NOT NULL,
    symbol VARCHAR NOT NULL, exchange VARCHAR NOT NULL, market VARCHAR NOT NULL,
    asset_type VARCHAR NOT NULL, trading_calendar VARCHAR NOT NULL,
    interval VARCHAR NOT NULL, trade_time TIMESTAMPTZ NOT NULL,
    local_trade_time TIMESTAMPTZ NOT NULL, utc_trade_date DATE NOT NULL,
    local_trade_date DATE NOT NULL, open DOUBLE, high DOUBLE, low DOUBLE,
    close DOUBLE, volume DOUBLE, quote_volume DOUBLE, source VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL,
    PRIMARY KEY (run_id, symbol, exchange, interval, trade_time),
    CHECK (requested_instrument='ETH-USDT'),
    CHECK (raw_instrument='ETH-USDT'),
    CHECK (normalized_instrument='ETHUSDT'),
    CHECK (data_provider='okx_public_api'),
    CHECK (raw_exchange='OKX' AND normalized_exchange='OKX'),
    CHECK (instrument_type='spot' AND market='spot'),
    CHECK (bar_interval='1h' AND interval='1h'),
    CHECK (confirmed=TRUE)
);

CREATE TABLE IF NOT EXISTS clean.crypto_price_fact AS SELECT * FROM raw.crypto_market_data WHERE FALSE;
CREATE UNIQUE INDEX IF NOT EXISTS uq_crypto_price_fact
ON clean.crypto_price_fact(run_id, symbol, exchange, interval, trade_time);

CREATE TABLE IF NOT EXISTS feature.crypto_indicator (
    symbol VARCHAR NOT NULL, exchange VARCHAR NOT NULL, interval VARCHAR NOT NULL,
    trade_time TIMESTAMPTZ NOT NULL, return_1bar DOUBLE,
    realized_volatility DOUBLE, annualized_volatility DOUBLE, true_range DOUBLE,
    atr DOUBLE, atr_ratio DOUBLE, bollinger_middle DOUBLE, bollinger_upper DOUBLE,
    bollinger_lower DOUBLE, bollinger_band_width DOUBLE, trend_slope DOUBLE,
    trend_r_squared DOUBLE, box_high DOUBLE, box_low DOUBLE, box_width DOUBLE,
    false_breakout_up BOOLEAN NOT NULL, false_breakout_down BOOLEAN NOT NULL,
    indicator_status VARCHAR NOT NULL, run_id VARCHAR NOT NULL,
    PRIMARY KEY (run_id, symbol, exchange, interval, trade_time)
);

CREATE TABLE IF NOT EXISTS analysis.crypto_profile (
    symbol VARCHAR NOT NULL, exchange VARCHAR NOT NULL, asset_type VARCHAR NOT NULL,
    as_of_date DATE NOT NULL, interval VARCHAR NOT NULL,
    annualized_volatility DOUBLE, atr_ratio DOUBLE, bollinger_band_width DOUBLE,
    trend_slope DOUBLE, trend_r_squared DOUBLE, box_width DOUBLE,
    false_breakout_count BIGINT NOT NULL, profile_status VARCHAR NOT NULL,
    explanation VARCHAR NOT NULL, model_version VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL, PRIMARY KEY (run_id, symbol, exchange, interval)
);

CREATE TABLE IF NOT EXISTS quality.stage11_quality_result (
    run_id VARCHAR NOT NULL, check_name VARCHAR NOT NULL, severity VARCHAR NOT NULL,
    status VARCHAR NOT NULL, observed_value VARCHAR, expected_value VARCHAR,
    message VARCHAR, checked_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, check_name)
);

CREATE TABLE IF NOT EXISTS audit.stage11_run (
    run_id VARCHAR PRIMARY KEY, run_status VARCHAR NOT NULL,
    publication_status VARCHAR NOT NULL, started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ, as_of_date DATE NOT NULL, symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL, interval VARCHAR NOT NULL, source VARCHAR NOT NULL,
    requested_instrument VARCHAR NOT NULL, raw_instrument VARCHAR NOT NULL,
    normalized_instrument VARCHAR NOT NULL, data_provider VARCHAR NOT NULL,
    raw_exchange VARCHAR NOT NULL, normalized_exchange VARCHAR NOT NULL,
    instrument_type VARCHAR NOT NULL, bar_interval VARCHAR NOT NULL,
    row_count BIGINT NOT NULL, indicator_row_count BIGINT NOT NULL,
    profile_row_count BIGINT NOT NULL, quality_passed BIGINT NOT NULL,
    quality_failed BIGINT NOT NULL, config_hash VARCHAR NOT NULL,
    output_type VARCHAR NOT NULL, blocking_reasons_json VARCHAR NOT NULL,
    manifest_json VARCHAR NOT NULL
);

CREATE OR REPLACE VIEW clean.v_latest_crypto_price_fact AS
SELECT fact.* FROM clean.crypto_price_fact fact JOIN (
    SELECT run_id FROM audit.stage11_run WHERE run_status='PASS'
    ORDER BY completed_at DESC, run_id DESC LIMIT 1
) latest USING (run_id);
