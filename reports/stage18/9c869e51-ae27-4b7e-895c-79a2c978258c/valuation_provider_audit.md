# Stage 18.1.2 备用实时估值 Provider / 能力审计

- Run ID: `9c869e51-ae27-4b7e-895c-79a2c978258c`
- 状态: `PASS`
- AKShare: `1.18.80`
- 基准日: `2026-07-27`
- 审计资产不得直接进入 Stage 18.2。

## 市场级能力结论

|市场|能力状态|选定Provider|缺口|
|---|---|---|---|
|A|PASS|EastmoneyDataCenter[valuation_comparison+scale_comparison]|-|
|HK|PASS|stock_hk_financial_indicator_em|-|

## Provider终态

|市场|证券|接口|Provider|状态|选用|拒绝原因|
|---|---|---|---|---|---|---|
|A|*|`stock_zh_a_spot_em`|EastmoneyPush2|FAIL|False|connection_error|
|HK|*|`stock_hk_spot_em`|EastmoneyPush2|FAIL|False|connection_error|
|A|600763|`stock_zh_a_spot`|Sina|UNAVAILABLE|False|missing_required_semantics:floating_market_cap,pb,pe,total_market_cap|
|A|000100|`stock_zh_a_spot`|Sina|UNAVAILABLE|False|missing_required_semantics:floating_market_cap,pb,pe,total_market_cap|
|A|603259|`stock_zh_a_spot`|Sina|UNAVAILABLE|False|missing_required_semantics:floating_market_cap,pb,pe,total_market_cap|
|A|600763|`stock_zh_a_spot_tx`|Tencent|UNAVAILABLE|False|missing_required_semantics:floating_market_cap,pb,total_market_cap|
|A|000100|`stock_zh_a_spot_tx`|Tencent|UNAVAILABLE|False|missing_required_semantics:floating_market_cap,pb,total_market_cap|
|A|603259|`stock_zh_a_spot_tx`|Tencent|UNAVAILABLE|False|missing_required_semantics:floating_market_cap,pb,total_market_cap|
|A|600763|`stock_zh_valuation_baidu`|Baidu|UNAVAILABLE|False|missing_required_semantics:floating_market_cap|
|A|000100|`stock_zh_valuation_baidu`|Baidu|UNAVAILABLE|False|missing_required_semantics:floating_market_cap|
|A|603259|`stock_zh_valuation_baidu`|Baidu|UNAVAILABLE|False|missing_required_semantics:floating_market_cap|
|A|600763|`stock_zh_valuation_comparison_em`|EastmoneyDataCenter|UNAVAILABLE|True|missing_required_semantics:floating_market_cap,total_market_cap|
|A|000100|`stock_zh_valuation_comparison_em`|EastmoneyDataCenter|UNAVAILABLE|True|missing_required_semantics:floating_market_cap,total_market_cap|
|A|603259|`stock_zh_valuation_comparison_em`|EastmoneyDataCenter|UNAVAILABLE|True|missing_required_semantics:floating_market_cap,total_market_cap|
|A|600763|`stock_zh_scale_comparison_em`|EastmoneyDataCenter|UNAVAILABLE|True|missing_required_semantics:pb,pe|
|A|000100|`stock_zh_scale_comparison_em`|EastmoneyDataCenter|UNAVAILABLE|True|missing_required_semantics:pb,pe|
|A|603259|`stock_zh_scale_comparison_em`|EastmoneyDataCenter|UNAVAILABLE|True|missing_required_semantics:pb,pe|
|HK|08365.HK|`stock_hk_financial_indicator_em`|EastmoneyDataCenter|PASS|True||
|HK|09669.HK|`stock_hk_financial_indicator_em`|EastmoneyDataCenter|PASS|True||
|HK|08365.HK|`stock_hk_indicator_eniu`|Eniu|PASS|False||
|HK|09669.HK|`stock_hk_indicator_eniu`|Eniu|FAIL|False|parameter_error|
|HK|08365.HK|`stock_hk_valuation_baidu`|Baidu|PASS|False||
|HK|09669.HK|`stock_hk_valuation_baidu`|Baidu|PASS|False||

## 治理

Eastmoney `stock_zh_a_spot_em` 与 `stock_hk_spot_em` 的既有 `FAIL/connection_error` 原样保留，未降级为 `UNAVAILABLE`。
Provider失败与市场级估值能力失败分开判定；只有语义完整且覆盖全部审计样本的Provider可被选择。
全部证据均为 `asset_role=valuation_provider_audit`、`audit_only=true`、`eligible_for_stage18_2_ingestion=false`。
本任务不重跑完整 Stage 18.1，不授权或启动 Stage 18.2。

本报告仅用于数据能力研究与测试，不构成投资建议。
