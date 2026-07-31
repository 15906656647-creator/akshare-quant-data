CREATE TABLE IF NOT EXISTS dim_security (
    symbol VARCHAR PRIMARY KEY, exchange VARCHAR NOT NULL, symbol_em VARCHAR NOT NULL,
    market_lower VARCHAR NOT NULL, asset_type VARCHAR NOT NULL, currency VARCHAR NOT NULL,
    is_active BOOLEAN NOT NULL
);
CREATE TABLE IF NOT EXISTS etl_run (
    transform_run_id VARCHAR PRIMARY KEY, market_source_run_id VARCHAR NOT NULL,
    fundamental_source_run_id VARCHAR NOT NULL, as_of_date DATE NOT NULL,
    started_at TIMESTAMPTZ NOT NULL, finished_at TIMESTAMPTZ,
    code_version VARCHAR, git_commit VARCHAR, python_version VARCHAR,
    pandas_version VARCHAR, pyarrow_version VARCHAR, duckdb_version VARCHAR,
    status VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS source_file_manifest (
    source_run_id VARCHAR NOT NULL, source_file VARCHAR NOT NULL, byte_size BIGINT NOT NULL,
    sha256 VARCHAR NOT NULL, row_count BIGINT NOT NULL,
    PRIMARY KEY (source_run_id, source_file)
);
CREATE TABLE IF NOT EXISTS data_lineage (
    transform_run_id VARCHAR NOT NULL, dataset_id VARCHAR NOT NULL,
    clean_file VARCHAR NOT NULL, source_file VARCHAR NOT NULL,
    source_run_id VARCHAR NOT NULL,
    PRIMARY KEY (transform_run_id, dataset_id, clean_file, source_file)
);
CREATE TABLE IF NOT EXISTS data_quality_issue (
    transform_run_id VARCHAR NOT NULL, dataset_id VARCHAR NOT NULL,
    check_name VARCHAR NOT NULL, severity VARCHAR NOT NULL, status VARCHAR NOT NULL,
    issue_count BIGINT NOT NULL, message VARCHAR,
    issue_code VARCHAR, symbol VARCHAR, field_name VARCHAR,
    business_key_json VARCHAR, source_file VARCHAR, source_row_number BIGINT,
    issue_scope VARCHAR, issue_key VARCHAR NOT NULL, record_hash VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS field_mapping_registry (
    transform_run_id VARCHAR NOT NULL, source_dataset VARCHAR NOT NULL,
    source_field VARCHAR NOT NULL, canonical_field VARCHAR, data_type VARCHAR,
    source_unit VARCHAR, target_unit VARCHAR, scale_factor DOUBLE,
    nullable BOOLEAN, required BOOLEAN, mapping_status VARCHAR NOT NULL,
    mapping_evidence VARCHAR, notes VARCHAR,
    mapping_key VARCHAR NOT NULL, record_hash VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS fact_stock_daily (
    transform_run_id VARCHAR NOT NULL, source_run_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL, exchange VARCHAR NOT NULL, trade_date DATE NOT NULL,
    adjust_type VARCHAR NOT NULL, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE,
    volume_lot DOUBLE, volume_share DOUBLE, amount_cny DOUBLE, amplitude DOUBLE,
    pct_change DOUBLE, price_change DOUBLE, turnover_rate DOUBLE,
    source_file VARCHAR NOT NULL, source_row_number BIGINT NOT NULL, ingested_at TIMESTAMPTZ,
    PRIMARY KEY (symbol, trade_date, adjust_type, source_run_id)
);
CREATE TABLE IF NOT EXISTS fact_stock_spot (
    transform_run_id VARCHAR NOT NULL, source_run_id VARCHAR NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL, snapshot_scope VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL, exchange VARCHAR, name VARCHAR, latest_price DOUBLE,
    pct_change DOUBLE, price_change DOUBLE, volume_lot DOUBLE, volume_share DOUBLE,
    amount_cny DOUBLE, amplitude DOUBLE, turnover_rate DOUBLE, volume_ratio DOUBLE,
    pe_dynamic DOUBLE, pb DOUBLE, market_cap_cny DOUBLE, float_market_cap_cny DOUBLE,
    source_payload_json VARCHAR, source_file VARCHAR NOT NULL,
    PRIMARY KEY (symbol, snapshot_at, snapshot_scope, source_run_id)
);
CREATE TABLE IF NOT EXISTS fact_financial_abstract (
    transform_run_id VARCHAR NOT NULL, source_run_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL, exchange VARCHAR NOT NULL, report_period DATE NOT NULL,
    announcement_date DATE, metric_code VARCHAR NOT NULL, metric_name_source VARCHAR NOT NULL,
    metric_category_source VARCHAR,
    metric_value DOUBLE, metric_value_raw VARCHAR, unit_source VARCHAR,
    unit_canonical VARCHAR, potential_lookahead BOOLEAN,
    announcement_date_status VARCHAR NOT NULL, source_interface VARCHAR NOT NULL,
    source_field VARCHAR NOT NULL, source_file VARCHAR NOT NULL, source_row_number BIGINT NOT NULL,
    PRIMARY KEY (symbol, report_period, metric_code, source_run_id)
);
CREATE TABLE IF NOT EXISTS fact_financial_indicator (
    transform_run_id VARCHAR NOT NULL, source_run_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL, exchange VARCHAR NOT NULL, report_period DATE NOT NULL,
    announcement_date DATE, metric_code VARCHAR NOT NULL, metric_name_source VARCHAR NOT NULL,
    metric_value DOUBLE, metric_value_raw VARCHAR, unit_source VARCHAR,
    unit_canonical VARCHAR, potential_lookahead BOOLEAN,
    announcement_date_status VARCHAR NOT NULL, source_interface VARCHAR NOT NULL,
    source_field VARCHAR NOT NULL, source_file VARCHAR NOT NULL, source_row_number BIGINT NOT NULL,
    PRIMARY KEY (symbol, report_period, metric_code, source_run_id)
);
CREATE TABLE IF NOT EXISTS fact_financial_statement (
    transform_run_id VARCHAR NOT NULL, source_run_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL, exchange VARCHAR NOT NULL, statement_type VARCHAR NOT NULL,
    report_period DATE NOT NULL, announcement_date DATE, line_item_code VARCHAR NOT NULL,
    line_item_name_source VARCHAR NOT NULL, line_item_value DOUBLE,
    line_item_value_raw VARCHAR, unit_source VARCHAR, unit_canonical VARCHAR,
    potential_lookahead BOOLEAN, announcement_date_status VARCHAR NOT NULL,
    source_column VARCHAR NOT NULL, source_file VARCHAR NOT NULL, source_row_number BIGINT NOT NULL,
    PRIMARY KEY (symbol, statement_type, report_period, line_item_code, source_run_id)
);
CREATE TABLE IF NOT EXISTS fact_stock_fund_flow (
    transform_run_id VARCHAR NOT NULL, source_run_id VARCHAR NOT NULL,
    symbol VARCHAR NOT NULL, exchange VARCHAR NOT NULL, trade_date DATE NOT NULL,
    close DOUBLE, pct_change DOUBLE, main_net_inflow_cny DOUBLE,
    main_net_inflow_ratio DOUBLE, super_large_net_inflow_cny DOUBLE,
    super_large_net_inflow_ratio DOUBLE, large_net_inflow_cny DOUBLE,
    large_net_inflow_ratio DOUBLE, medium_net_inflow_cny DOUBLE,
    medium_net_inflow_ratio DOUBLE, small_net_inflow_cny DOUBLE,
    small_net_inflow_ratio DOUBLE, source_file VARCHAR NOT NULL,
    PRIMARY KEY (symbol, trade_date, source_run_id)
);
