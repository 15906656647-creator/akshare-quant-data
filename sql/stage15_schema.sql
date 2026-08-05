CREATE SCHEMA IF NOT EXISTS quality;
CREATE SCHEMA IF NOT EXISTS audit;

CREATE TABLE IF NOT EXISTS quality.check_result (
    run_id VARCHAR NOT NULL,
    check_name VARCHAR NOT NULL,
    category VARCHAR NOT NULL,
    severity VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    observed_value VARCHAR,
    expected_value VARCHAR,
    interface_name VARCHAR,
    message VARCHAR,
    checked_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, check_name)
);

CREATE TABLE IF NOT EXISTS quality.risk_log (
    risk_id VARCHAR PRIMARY KEY,
    run_id VARCHAR NOT NULL,
    detected_at TIMESTAMPTZ NOT NULL,
    category VARCHAR NOT NULL,
    interface_name VARCHAR,
    symbol VARCHAR,
    severity VARCHAR NOT NULL,
    description VARCHAR NOT NULL,
    impact VARCHAR,
    mitigation VARCHAR,
    status VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS quality.cross_validation (
    run_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL,
    check_item VARCHAR NOT NULL,
    observed_value VARCHAR,
    source_table VARCHAR,
    as_of_date DATE NOT NULL,
    verification_status VARCHAR NOT NULL,
    note VARCHAR,
    PRIMARY KEY (run_id, symbol, check_item)
);

CREATE TABLE IF NOT EXISTS audit.stage15_run (
    run_id VARCHAR PRIMARY KEY,
    as_of_date DATE NOT NULL,
    status VARCHAR NOT NULL,
    config_hash VARCHAR NOT NULL,
    quality_passed BIGINT,
    quality_failed BIGINT,
    quality_warned BIGINT,
    risk_row_count BIGINT,
    cross_validation_row_count BIGINT,
    stage8_blocker_codes VARCHAR,
    created_at TIMESTAMPTZ NOT NULL,
    input_database VARCHAR,
    output_database VARCHAR
);
