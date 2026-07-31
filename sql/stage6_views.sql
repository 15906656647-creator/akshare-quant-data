-- Rebuild after loading the nine Stage 6 feature Parquet datasets.
CREATE OR REPLACE VIEW v_feature_latest_historical AS
SELECT p.*, t.* EXCLUDE (
    feature_run_id, transform_run_id, source_run_id, symbol,
    exchange, trade_date, source_file, close_qfq
), a.* EXCLUDE (
    feature_run_id, transform_run_id, source_run_id, symbol,
    exchange, trade_date
)
FROM feat_price_daily p
JOIN feat_trend_daily t USING (
    feature_run_id, transform_run_id, source_run_id,
    symbol, exchange, trade_date
)
JOIN feat_activity_daily a USING (
    feature_run_id, transform_run_id, source_run_id,
    symbol, exchange, trade_date
)
QUALIFY row_number() OVER (
    PARTITION BY p.feature_run_id, p.symbol
    ORDER BY p.trade_date DESC
) = 1;

CREATE OR REPLACE VIEW v_feature_as_of_20260727 AS
SELECT * FROM v_feature_latest_historical
WHERE trade_date <= DATE '2026-07-27';

CREATE OR REPLACE VIEW v_current_snapshot_features AS
SELECT * FROM feat_current_snapshot;

CREATE OR REPLACE VIEW v_suspected_behavior_evidence AS
SELECT * FROM feat_suspected_behavior_evidence;

CREATE OR REPLACE VIEW v_feature_quality_blockers AS
SELECT * FROM feature_quality_issue WHERE status = 'FAIL';
