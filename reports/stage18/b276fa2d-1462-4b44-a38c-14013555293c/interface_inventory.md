# Stage 18.1 基本面接口能力审计

- Run ID: `b276fa2d-1462-4b44-a38c-14013555293c`
- 上游 Stage 17: `4a5599fb-9e60-4013-9c0c-69fcc25a98b2` (`PASS`)
- AKShare: `1.18.80`
- Python: `3.11.4`
- 分析基准日: `2026-07-27`
- 审计状态: `BLOCKED`
- 结果计数: `{"FAIL": 5, "PASS": 33}`

## 样本选择

|市场|代码|上市日期|选择理由|
|---|---|---|---|
|A|600763|1996-10-30|earliest_listed_SH|
|A|000100|2004-01-30|earliest_listed_SZ|
|A|603259|2018-05-08|latest_listed_remaining_A|
|HK|08365.HK|2017-05-26|earliest_listed_HK|
|HK|09669.HK|2023-04-13|latest_listed_HK|

候选证券均来自指定 Stage 17 批次，共 23 只。

## 能力矩阵

|市场|接口|类别|时态|PASS|UNAVAILABLE|FAIL|BLOCKED|
|---|---|---|---|---:|---:|---:|---:|
|A|`stock_balance_sheet_by_report_em`|balance_sheet|history|3|0|0|0|
|A|`stock_cash_flow_sheet_by_report_em`|cash_flow_statement|history|3|0|0|0|
|A|`stock_financial_abstract`|financial_abstract|history|3|0|0|0|
|A|`stock_financial_analysis_indicator`|financial_indicator|history|3|0|0|0|
|A|`stock_profit_sheet_by_report_em`|income_statement|history|3|0|0|0|
|A|`stock_zh_a_spot_em`|valuation_snapshot|snapshot|0|0|3|0|
|HK|`stock_financial_hk_analysis_indicator_em`|financial_indicator|history|4|0|0|0|
|HK|`stock_financial_hk_report_em`|balance_sheet|history|4|0|0|0|
|HK|`stock_financial_hk_report_em`|cash_flow_statement|history|4|0|0|0|
|HK|`stock_financial_hk_report_em`|income_statement|history|4|0|0|0|
|HK|`stock_hk_financial_indicator_em`|valuation_snapshot|snapshot|2|0|0|0|
|HK|`stock_hk_spot_em`|valuation_snapshot|snapshot|0|0|2|0|

## 非 PASS 明细

|状态|市场|代码|接口|错误类型|说明|
|---|---|---|---|---|---|
|FAIL|A|600763|`stock_zh_a_spot_em`|connection_error|HTTPSConnectionPool(host='82.push2.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f12&fs=m%3A0+t%3A6%2Cm%3A0+t%3A80%2Cm%3A1+t%3A2%2Cm%3|
|FAIL|A|000100|`stock_zh_a_spot_em`|connection_error|HTTPSConnectionPool(host='82.push2.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f12&fs=m%3A0+t%3A6%2Cm%3A0+t%3A80%2Cm%3A1+t%3A2%2Cm%3|
|FAIL|A|603259|`stock_zh_a_spot_em`|connection_error|HTTPSConnectionPool(host='82.push2.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f12&fs=m%3A0+t%3A6%2Cm%3A0+t%3A80%2Cm%3A1+t%3A2%2Cm%3|
|FAIL|HK|08365.HK|`stock_hk_spot_em`|connection_error|HTTPSConnectionPool(host='72.push2.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f12&fs=m%3A128+t%3A3%2Cm%3A128+t%3A4%2Cm%3A128+t%3A1%|
|FAIL|HK|09669.HK|`stock_hk_spot_em`|connection_error|HTTPSConnectionPool(host='72.push2.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f12&fs=m%3A128+t%3A3%2Cm%3A128+t%3A4%2Cm%3A128+t%3A1%|

## 时间治理

实时估值仅用于能力审计。所有快照均标记 `audit_only=true`、`eligible_for_analysis=false`，不得回填到 2026-07-27 或进入正式估值事实表。

## 已知测试债务

Stage 8 既有失败属于人工规则数据与旧测试前置假设冲突；本审计不修改 Stage 8，完整测试结果必须单独核对，任何新增失败均阻止 Stage 18.1 通过。

## Stage 18.2 建议

仅可对本清单中状态为 `PASS` 的类别规划全量 Raw 采集。`UNAVAILABLE` 保持显式缺口；存在 `FAIL` 或 `BLOCKED` 时不得授权 Stage 18.2。

本报告仅用于数据能力研究与测试，不构成投资建议。
