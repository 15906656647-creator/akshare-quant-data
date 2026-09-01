# Stage 18.1.3 完整能力重新验收与 Stage 18.2 出口授权

## 正式结论

完整 Stage 18.1 新 run `4915ea1b-2e00-4a34-a743-d35dfcb66fe2`
状态为 `PASS`，`stage18_2_authorized=true`，`stage18_2_started=false`。

本 run 独立重新调用全部历史财务能力和 Stage 18.1.2 已选定的估值
Provider；没有拼接或复用 Stage 18.1、18.1.1、18.1.2 的审计 Raw。

## 能力门禁

|市场|能力|结果|通过单元|
|---|---|---|---:|
|A|financial_abstract|PASS|3/3|
|A|financial_indicator|PASS|3/3|
|A|balance_sheet|PASS|3/3|
|A|income_statement|PASS|3/3|
|A|cash_flow_statement|PASS|3/3|
|A|valuation|PASS|6/6|
|HK|financial_indicator|PASS|4/4|
|HK|balance_sheet|PASS|4/4|
|HK|income_statement|PASS|4/4|
|HK|cash_flow_statement|PASS|4/4|
|HK|valuation|PASS|2/2|

A 股估值选定
`EastmoneyDataCenter[valuation_comparison+scale_comparison]`，由
`stock_zh_valuation_comparison_em` 提供 PE/PB、
`stock_zh_scale_comparison_em` 提供总市值/流通市值。港股估值选定
`stock_hk_financial_indicator_em`。

`stock_zh_a_spot_em` 和 `stock_hk_spot_em` 保持
`FAIL / frozen_connection_error`，引用 Stage 18.1.1 run
`19660ce0-e73d-4d0c-8451-cfaee0b726da`，本轮未重试且不影响已由合格
Provider 满足的市场级能力。

## 完整性与阶段边界

- 新 run 产生 78 个 Raw 文件，manifest 登记 78 个；文件大小和 SHA-256
  全部独立复算一致。
- 39 份 metadata 全部为 `asset_role=interface_audit`、`audit_only=true`、
  `eligible_for_stage18_2_ingestion=false`。
- Raw 临时文件为 0；Stage 0 冻结哈希保持不变。
- Stage 17 正式 manifest 的 196 个 Raw 文件在任务前后逐一复算一致，树摘要
  未变化。
- Stage 18 正式财务 Raw、正式 Fact 表、基本面 Feature 和 Stage 19 资产均为 0。
- 本任务只授予 Stage 18.2 入口资格，没有启动 Stage 18.2，也没有把审计样本
  转为正式采集数据。

## 测试证据

- Python 编译及 CLI 冒烟：通过。
- Stage 18.1.3、Stage 18.1.2、Stage 18.1、Stage 0 和项目结构定向测试：
  `47 passed`。
- 正式 run 后完整离线测试：`1017 passed, 1 failed`。
- 唯一失败为已登记的 Stage 8 测试债务：
  `tests/test_stage8_manual_import.py::test_default_cli_fails_closed_without_real_dataset`；
  错误签名仍为“期望返回码 1，实际返回码 0”。没有新增失败。
- 完整测试使用短 `basetemp`，没有 Stage 17 Windows 临时路径长度失败。

Stage 18.1 至此正式通过。后续若启动 Stage 18.2，必须创建新的正式采集
`run_id` 和独立 Raw，禁止复用本阶段 5 只审计样本。

本项目仅用于数据能力研究与测试，不构成投资建议。
