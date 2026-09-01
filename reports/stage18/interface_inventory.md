# Stage 18.1 完整能力重新验收（18.1.3）

- Run ID: `4915ea1b-2e00-4a34-a743-d35dfcb66fe2`
- 状态: `PASS`
- Stage 18.2 授权: `true`
- 上游 Stage 17: `4a5599fb-9e60-4013-9c0c-69fcc25a98b2`
- 基准日: `2026-07-27`

## 正式能力矩阵

|市场|能力|状态|选定Provider|通过/计划|
|---|---|---|---|---:|
|A|financial_abstract|PASS|stock_financial_abstract|3/3|
|A|financial_indicator|PASS|stock_financial_analysis_indicator|3/3|
|A|balance_sheet|PASS|stock_balance_sheet_by_report_em|3/3|
|A|income_statement|PASS|stock_profit_sheet_by_report_em|3/3|
|A|cash_flow_statement|PASS|stock_cash_flow_sheet_by_report_em|3/3|
|HK|financial_indicator|PASS|stock_financial_hk_analysis_indicator_em|4/4|
|HK|balance_sheet|PASS|stock_financial_hk_report_em|4/4|
|HK|income_statement|PASS|stock_financial_hk_report_em|4/4|
|HK|cash_flow_statement|PASS|stock_financial_hk_report_em|4/4|
|A|valuation|PASS|EastmoneyDataCenter[valuation_comparison+scale_comparison]|6/6|
|HK|valuation|PASS|stock_hk_financial_indicator_em|2/2|

## 冻结拒绝 Provider

- `stock_zh_a_spot_em`：`FAIL / frozen_connection_error`，未重试、未选用；证据 run `19660ce0-e73d-4d0c-8451-cfaee0b726da`。
- `stock_hk_spot_em`：`FAIL / frozen_connection_error`，未重试、未选用；证据 run `19660ce0-e73d-4d0c-8451-cfaee0b726da`。

## 治理结论

历史财务和估值样本全部位于同一个新 run；没有复用或拼接旧 Stage 18 Raw。
全部新资产均为 `asset_role=interface_audit`、`audit_only=true`、`eligible_for_stage18_2_ingestion=false`。
A 股估值由同一 Eastmoney Data Center Provider 的两个组件共同满足；组件单独不要求覆盖完整市场级语义。
本 run 只给出 Stage 18.2 入口授权，没有启动 Stage 18.2，也没有创建正式财务 Raw、Fact、Feature 或 Stage 19 资产。

本项目仅用于数据能力研究与测试，不构成投资建议。
