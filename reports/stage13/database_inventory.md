# Stage 13 database inventory

All databases were opened read-only; counts include only rows visible by `2026-07-27`.

| database | schema | table | rows | date column | type | filter mode | parse failures | date min | date max | target coverage | status |
|---|---|---|---:|---|---|---|---:|---|---|---:|---|
| database/akshare_data_test_stage5_repaired.duckdb | main | data_lineage | 130 | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | data_quality_issue | 47 | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | dim_security | 16 | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | 0 | - | - | 1.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | etl_run | 1 | as_of_date | DATE | DATE | 0 | 2026-07-27 | 2026-07-27 | 0.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | fact_financial_abstract | 0 | announcement_date | DATE | DATE | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | fact_financial_indicator | 0 | announcement_date | DATE | DATE | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | fact_financial_statement | 863226 | announcement_date | DATE | DATE | 0 | 1996-10-24 | 2026-04-30 | 1.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | fact_stock_daily | 23204 | trade_date | DATE | DATE | 0 | 2023-07-27 | 2026-07-27 | 1.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | fact_stock_fund_flow | 1904 | trade_date | DATE | DATE | 0 | 2026-01-13 | 2026-07-27 | 1.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | fact_stock_spot | 0 | snapshot_at | TIMESTAMP WITH TIME ZONE | TIMESTAMPTZ | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | field_mapping_registry | 1024 | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | source_file_manifest | 130 | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | v_financial_all | 863226 | announcement_date | DATE | DATE | 0 | 1996-10-24 | 2026-04-30 | 1.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | v_financial_announcement_unknown | 0 | announcement_date | DATE | DATE | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | v_financial_point_in_time_safe | 863226 | announcement_date | DATE | DATE | 0 | 1996-10-24 | 2026-04-30 | 1.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | v_financial_potential_lookahead | 0 | announcement_date | DATE | DATE | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | v_latest_stock_spot | 0 | snapshot_at | TIMESTAMP WITH TIME ZONE | TIMESTAMPTZ | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | v_stock_daily_qfq | 11602 | trade_date | DATE | DATE | 0 | 2023-07-27 | 2026-07-27 | 1.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | v_stock_daily_raw | 11602 | trade_date | DATE | DATE | 0 | 2023-07-27 | 2026-07-27 | 1.000 | AVAILABLE |
| database/akshare_data_test_stage5_repaired.duckdb | main | v_stock_fund_flow_as_of_safe | 1904 | trade_date | DATE | DATE | 0 | 2026-01-13 | 2026-07-27 | 1.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | feat_activity_daily | 11602 | trade_date | TIMESTAMP | TIMESTAMP | 0 | 2023-07-27 00:00:00 | 2026-07-27 00:00:00 | 1.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | feat_current_snapshot | 0 | snapshot_at | TIMESTAMP WITH TIME ZONE | TIMESTAMPTZ | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | feat_financial_period | 14364 | announcement_date | TIMESTAMP | TIMESTAMP | 0 | 1996-10-24 00:00:00 | 2026-04-30 00:00:00 | 1.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | feat_fund_flow_daily | 1904 | trade_date | TIMESTAMP | TIMESTAMP | 0 | 2026-01-13 00:00:00 | 2026-07-27 00:00:00 | 1.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | feat_limit_event | 11602 | trade_date | TIMESTAMP | TIMESTAMP | 0 | 2023-07-27 00:00:00 | 2026-07-27 00:00:00 | 1.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | feat_price_daily | 11602 | trade_date | TIMESTAMP | TIMESTAMP | 0 | 2023-07-27 00:00:00 | 2026-07-27 00:00:00 | 1.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | feat_style_daily | 11602 | trade_date | TIMESTAMP | TIMESTAMP | 0 | 2023-07-27 00:00:00 | 2026-07-27 00:00:00 | 1.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | feat_suspected_behavior_evidence | 16 | as_of_date | TIMESTAMP_S | TIMESTAMP | 0 | 2026-07-27 00:00:00 | 2026-07-27 00:00:00 | 1.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | feat_trend_daily | 11602 | trade_date | TIMESTAMP | TIMESTAMP | 0 | 2023-07-27 00:00:00 | 2026-07-27 00:00:00 | 1.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | feature_definition_registry | 109 | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | feature_file_manifest | 9 | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | feature_lineage | 9 | created_at | VARCHAR | NOT_APPLICABLE | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | feature_quality_issue | 9 | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | feature_run | 1 | as_of_date | DATE | DATE | 0 | 2026-07-27 | 2026-07-27 | 0.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | v_current_snapshot_features | 0 | snapshot_at | TIMESTAMP WITH TIME ZONE | TIMESTAMPTZ | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | v_feature_as_of_20260727 | 16 | trade_date | TIMESTAMP | TIMESTAMP | 0 | 2026-07-27 00:00:00 | 2026-07-27 00:00:00 | 1.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | v_feature_latest_historical | 16 | trade_date | TIMESTAMP | TIMESTAMP | 0 | 2026-07-27 00:00:00 | 2026-07-27 00:00:00 | 1.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | v_feature_quality_blockers | 0 | NOT_APPLICABLE | NOT_APPLICABLE | NOT_APPLICABLE | 0 | - | - | 0.000 | AVAILABLE |
| database/akshare_features_stage6.duckdb | main | v_suspected_behavior_evidence | 16 | as_of_date | TIMESTAMP_S | TIMESTAMP | 0 | 2026-07-27 00:00:00 | 2026-07-27 00:00:00 | 1.000 | AVAILABLE |
| database/akshare_features_stage7.duckdb | analysis | analysis_stock_activity | 16 | as_of_date | DATE | DATE | 0 | 2026-07-27 | 2026-07-27 | 1.000 | AVAILABLE |
| database/akshare_features_stage7.duckdb | feature | feature_stock_daily | 11602 | trade_date | DATE | DATE | 0 | 2023-07-27 | 2026-07-27 | 1.000 | AVAILABLE |
| database/akshare_features_stage7.duckdb | quality | data_quality_result | 0 | calculated_at | TIMESTAMP WITH TIME ZONE | TIMESTAMPTZ | 0 | - | - | 0.000 | AVAILABLE |
