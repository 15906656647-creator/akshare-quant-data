CREATE OR REPLACE VIEW v_stock_daily_qfq AS
SELECT * FROM fact_stock_daily WHERE adjust_type = 'qfq';
CREATE OR REPLACE VIEW v_stock_daily_raw AS
SELECT * FROM fact_stock_daily WHERE adjust_type = 'raw';
CREATE OR REPLACE VIEW v_latest_stock_spot AS
SELECT * EXCLUDE (rn) FROM (
    SELECT *, row_number() OVER (
        PARTITION BY symbol, snapshot_scope ORDER BY snapshot_at DESC
    ) AS rn FROM fact_stock_spot
) WHERE rn = 1;
CREATE OR REPLACE VIEW v_financial_all AS
SELECT transform_run_id, source_run_id, symbol, report_period, announcement_date,
       potential_lookahead, announcement_date_status, 'abstract' AS financial_kind,
       metric_code AS item_code, metric_value AS item_value
FROM fact_financial_abstract
UNION ALL
SELECT transform_run_id, source_run_id, symbol, report_period, announcement_date,
       potential_lookahead, announcement_date_status, 'indicator',
       metric_code, metric_value
FROM fact_financial_indicator
UNION ALL
SELECT transform_run_id, source_run_id, symbol, report_period, announcement_date,
       potential_lookahead, announcement_date_status, statement_type,
       line_item_code, line_item_value
FROM fact_financial_statement;
CREATE OR REPLACE VIEW v_financial_point_in_time_safe AS
SELECT * FROM v_financial_all
WHERE announcement_date IS NOT NULL AND potential_lookahead = FALSE;
CREATE OR REPLACE VIEW v_financial_announcement_unknown AS
SELECT * FROM v_financial_all WHERE announcement_date_status = 'unavailable';
CREATE OR REPLACE VIEW v_financial_potential_lookahead AS
SELECT * FROM v_financial_all WHERE potential_lookahead = TRUE;
CREATE OR REPLACE VIEW v_stock_fund_flow_as_of_safe AS
SELECT f.*
FROM fact_stock_fund_flow f
JOIN etl_run e USING (transform_run_id)
WHERE f.trade_date <= e.as_of_date;
