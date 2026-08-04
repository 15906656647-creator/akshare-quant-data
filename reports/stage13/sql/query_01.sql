SELECT symbol, activity_score, score_status, event_component_source FROM analysis.analysis_stock_activity WHERE as_of_date <= ? ORDER BY activity_score DESC NULLS LAST, symbol;
