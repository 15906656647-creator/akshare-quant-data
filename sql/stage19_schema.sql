CREATE SCHEMA IF NOT EXISTS reference;
CREATE SCHEMA IF NOT EXISTS analysis;
CREATE SCHEMA IF NOT EXISTS quality;
CREATE SCHEMA IF NOT EXISTS governance;
CREATE SCHEMA IF NOT EXISTS audit;

-- Reuse and extend the Stage 8 reference model. UNKNOWN is represented by
-- is_st=NULL plus verification_status=UNKNOWN/UNAVAILABLE; it is never false.
CREATE TABLE IF NOT EXISTS reference.security_status_history (
    symbol VARCHAR NOT NULL, exchange VARCHAR NOT NULL, board VARCHAR NOT NULL,
    effective_start DATE NOT NULL, effective_end DATE, is_st BOOLEAN,
    special_treatment_type VARCHAR, listing_status VARCHAR NOT NULL,
    source_name VARCHAR, source_reference VARCHAR, source_date DATE,
    fetched_at TIMESTAMPTZ, evidence_level VARCHAR,
    verification_status VARCHAR NOT NULL, manual_review_status VARCHAR,
    notes VARCHAR, status_version VARCHAR NOT NULL,
    PRIMARY KEY (symbol, effective_start, status_version)
);

CREATE TABLE IF NOT EXISTS reference.limit_rule_history (
    exchange VARCHAR NOT NULL, board VARCHAR NOT NULL,
    special_treatment VARCHAR NOT NULL, effective_start DATE NOT NULL,
    effective_end DATE, limit_up_ratio DECIMAL(12,8),
    limit_down_ratio DECIMAL(12,8), no_limit_flag BOOLEAN NOT NULL,
    tick_size DECIMAL(18,8) NOT NULL, price_precision INTEGER NOT NULL,
    rounding_rule VARCHAR NOT NULL, rule_version VARCHAR NOT NULL,
    source_name VARCHAR, source_reference VARCHAR,
    verification_status VARCHAR NOT NULL, manual_review_status VARCHAR,
    PRIMARY KEY (exchange, board, special_treatment, effective_start, rule_version)
);

CREATE TABLE IF NOT EXISTS analysis.limit_event_candidate (
    run_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL, trade_date DATE NOT NULL,
    event_type VARCHAR NOT NULL, previous_close DOUBLE, open DOUBLE, high DOUBLE,
    low DOUBLE, close DOUBLE, theoretical_limit_up_price DOUBLE,
    theoretical_limit_down_price DOUBLE, matched_limit_price DOUBLE,
    calculation_method VARCHAR NOT NULL, rule_version VARCHAR,
    security_status_version VARCHAR, evidence_status VARCHAR NOT NULL,
    quality_status VARCHAR NOT NULL, blocked_reason VARCHAR,
    next_trade_date DATE, next_open_return_vs_event_close DOUBLE,
    next_open_return_vs_pre_event_close DOUBLE, next_high_return DOUBLE,
    next_low_return DOUBLE, next_close_return DOUBLE,
    next_day_continued_limit BOOLEAN, next_day_gap_up BOOLEAN,
    forward_3d_return DOUBLE, forward_5d_return DOUBLE,
    forward_10d_return DOUBLE, mfe_3d DOUBLE, mfe_5d DOUBLE, mfe_10d DOUBLE,
    mae_3d DOUBLE, mae_5d DOUBLE, mae_10d DOUBLE,
    forward_sample_status VARCHAR NOT NULL,
    consecutive_limit_up_count INTEGER, consecutive_limit_down_count INTEGER,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, symbol, trade_date)
);

CREATE TABLE IF NOT EXISTS analysis.limit_event (
    run_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL, trade_date DATE NOT NULL,
    event_type VARCHAR NOT NULL, rule_version VARCHAR NOT NULL,
    security_status_version VARCHAR NOT NULL,
    calculation_method VARCHAR NOT NULL, evidence_status VARCHAR NOT NULL,
    release_status VARCHAR NOT NULL, created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, symbol, trade_date)
);

CREATE TABLE IF NOT EXISTS quality.stage19_quality_result (
    run_id VARCHAR NOT NULL, check_id VARCHAR NOT NULL, status VARCHAR NOT NULL,
    observed_value VARCHAR, expected_value VARCHAR, message VARCHAR,
    checked_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, check_id)
);

CREATE TABLE IF NOT EXISTS governance.stage19_release_gate (
    run_id VARCHAR NOT NULL, gate_id VARCHAR NOT NULL, status VARCHAR NOT NULL,
    reason VARCHAR, checked_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, gate_id)
);

CREATE TABLE IF NOT EXISTS analysis.limit_event_statistics (
    run_id VARCHAR NOT NULL, symbol VARCHAR NOT NULL, period_start DATE NOT NULL,
    period_end DATE NOT NULL, metric_name VARCHAR NOT NULL, value DOUBLE,
    availability_status VARCHAR NOT NULL, reason VARCHAR,
    PRIMARY KEY (run_id, symbol, period_start, period_end, metric_name)
);

CREATE TABLE IF NOT EXISTS audit.stage19_run (
    run_id VARCHAR PRIMARY KEY, as_of_date DATE NOT NULL,
    period_start DATE NOT NULL, period_end DATE NOT NULL,
    stage18_entry_status VARCHAR NOT NULL, status VARCHAR NOT NULL,
    formal_event_release_status VARCHAR NOT NULL,
    candidate_count BIGINT NOT NULL, official_event_count BIGINT,
    blockers_json VARCHAR NOT NULL, created_at TIMESTAMPTZ NOT NULL
);

CREATE OR REPLACE VIEW analysis.v_stage19_formal_limit_event AS
SELECT * FROM analysis.limit_event WHERE release_status = 'PASS';
