CREATE SCHEMA IF NOT EXISTS reference;
CREATE SCHEMA IF NOT EXISTS analysis;
CREATE SCHEMA IF NOT EXISTS quality;
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS reference.limit_rule (
    exchange VARCHAR NOT NULL,
    board VARCHAR NOT NULL,
    is_st BOOLEAN NOT NULL,
    effective_start DATE NOT NULL,
    effective_end DATE,
    limit_up_ratio DECIMAL(12, 8),
    limit_down_ratio DECIMAL(12, 8),
    no_limit_flag BOOLEAN NOT NULL,
    tick_size DECIMAL(18, 8) NOT NULL,
    price_precision INTEGER NOT NULL,
    rounding_rule VARCHAR NOT NULL,
    rule_version VARCHAR NOT NULL,
    source_reference VARCHAR NOT NULL,
    source_name VARCHAR NOT NULL,
    verified_at DATE,
    evidence_status VARCHAR NOT NULL,
    PRIMARY KEY (exchange, board, is_st, effective_start, rule_version)
);

CREATE TABLE IF NOT EXISTS reference.security_status_history (
    symbol VARCHAR NOT NULL,
    effective_start DATE NOT NULL,
    effective_end DATE,
    exchange VARCHAR NOT NULL,
    board VARCHAR NOT NULL,
    is_st BOOLEAN,
    listing_status VARCHAR NOT NULL,
    listing_date DATE,
    delisting_date DATE,
    no_limit_reason VARCHAR,
    source_reference VARCHAR NOT NULL,
    status_version VARCHAR NOT NULL,
    evidence_status VARCHAR NOT NULL,
    PRIMARY KEY (symbol, effective_start, status_version)
);

CREATE TABLE IF NOT EXISTS analysis.fact_limit_event (
    symbol VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    event_type VARCHAR NOT NULL,
    previous_close DECIMAL(18, 6),
    open DECIMAL(18, 6),
    high DECIMAL(18, 6),
    low DECIMAL(18, 6),
    close DECIMAL(18, 6),
    official_limit_up_price DECIMAL(18, 6),
    official_limit_down_price DECIMAL(18, 6),
    official_limit_source_name VARCHAR,
    official_limit_source_reference VARCHAR,
    official_limit_source_version VARCHAR,
    official_limit_evidence_status VARCHAR,
    official_limit_verified_at TIMESTAMPTZ,
    official_limit_fetched_at TIMESTAMPTZ,
    official_limit_symbol VARCHAR,
    official_limit_trade_date DATE,
    official_limit_rejection_reason VARCHAR,
    theoretical_limit_up_price DECIMAL(18, 6),
    theoretical_limit_down_price DECIMAL(18, 6),
    unrounded_limit_up_price DECIMAL(24, 10),
    unrounded_limit_down_price DECIMAL(24, 10),
    matched_limit_price DECIMAL(18, 6),
    tick_size DECIMAL(18, 8),
    limit_ratio DECIMAL(12, 8),
    rule_version VARCHAR,
    security_status_version VARCHAR,
    detection_method VARCHAR NOT NULL,
    evidence_status VARCHAR NOT NULL,
    quality_status VARCHAR NOT NULL,
    resolution_reason VARCHAR,
    next_trade_date DATE,
    next_open DECIMAL(18, 6),
    next_close DECIMAL(18, 6),
    next_open_return DOUBLE,
    next_close_return DOUBLE,
    forward_3d_return DOUBLE,
    forward_5d_return DOUBLE,
    forward_10d_return DOUBLE,
    forward_sample_status VARCHAR NOT NULL,
    is_continued_limit BOOLEAN,
    is_valid_trade_row BOOLEAN NOT NULL,
    run_id VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, symbol, trade_date)
);

CREATE OR REPLACE VIEW analysis.v_formal_limit_event AS
SELECT *
FROM analysis.fact_limit_event
WHERE event_type IN ('limit_up', 'limit_down')
  AND evidence_status = 'verified'
  AND quality_status = 'pass';

CREATE TABLE IF NOT EXISTS analysis.limit_event_annual_summary (
    symbol VARCHAR NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    limit_up_count INTEGER,
    limit_down_count INTEGER,
    avg_next_open_return_after_limit_up DOUBLE,
    avg_next_close_return_after_limit_up DOUBLE,
    avg_forward_3d_return_after_limit_up DOUBLE,
    avg_forward_5d_return_after_limit_up DOUBLE,
    avg_forward_10d_return_after_limit_up DOUBLE,
    next_day_gap_up_ratio DOUBLE,
    continued_limit_ratio DOUBLE,
    formal_event_count INTEGER,
    publication_status VARCHAR NOT NULL,
    run_id VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, symbol, period_start, period_end)
);

-- Migrate databases created before blocked summaries made this field nullable.
ALTER TABLE analysis.limit_event_annual_summary
    ALTER COLUMN formal_event_count DROP NOT NULL;

ALTER TABLE analysis.limit_event_annual_summary
    ADD COLUMN IF NOT EXISTS avg_next_close_return_after_limit_up DOUBLE;
ALTER TABLE analysis.limit_event_annual_summary
    ADD COLUMN IF NOT EXISTS avg_forward_3d_return_after_limit_up DOUBLE;
ALTER TABLE analysis.limit_event_annual_summary
    ADD COLUMN IF NOT EXISTS avg_forward_5d_return_after_limit_up DOUBLE;
ALTER TABLE analysis.limit_event_annual_summary
    ADD COLUMN IF NOT EXISTS avg_forward_10d_return_after_limit_up DOUBLE;

CREATE TABLE IF NOT EXISTS quality.stage8_quality_result (
    run_id VARCHAR NOT NULL,
    check_name VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    severity VARCHAR NOT NULL,
    observed_value VARCHAR,
    expected_value VARCHAR,
    numerator BIGINT,
    denominator BIGINT,
    message VARCHAR,
    checked_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, check_name)
);

CREATE TABLE IF NOT EXISTS audit.stage8_run (
    run_id VARCHAR PRIMARY KEY,
    as_of_date DATE NOT NULL,
    period_start DATE NOT NULL,
    price_adjust_type VARCHAR NOT NULL,
    source_database VARCHAR NOT NULL,
    output_database VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    formal_event_count BIGINT,
    provisional_count BIGINT NOT NULL,
    unresolved_count BIGINT NOT NULL,
    blockers_json VARCHAR NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    input_database VARCHAR,
    input_table VARCHAR,
    input_price_route VARCHAR,
    window_start DATE,
    window_end DATE,
    publication_status VARCHAR,
    output_type VARCHAR,
    candidate_count BIGINT,
    quality_passed BIGINT,
    quality_failed BIGINT,
    code_version VARCHAR,
    config_hash VARCHAR,
    manifest_json VARCHAR
);

CREATE OR REPLACE VIEW analysis.v_latest_limit_event AS
SELECT event.*
FROM analysis.fact_limit_event AS event
JOIN (
    SELECT run_id
    FROM audit.stage8_run
    WHERE status = 'PASS'
    ORDER BY created_at DESC, run_id DESC
    LIMIT 1
) AS latest USING (run_id);

CREATE OR REPLACE VIEW analysis.v_latest_formal_limit_event AS
SELECT *
FROM analysis.v_latest_limit_event
WHERE event_type IN ('limit_up', 'limit_down')
  AND evidence_status = 'verified'
  AND quality_status = 'pass';
