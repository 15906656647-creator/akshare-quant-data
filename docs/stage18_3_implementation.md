# Stage 18.3 基本面 Raw 标准化与时间语义治理实施记录

## 阶段范围

本阶段唯一上游为 Stage 18.2 正式 run
`df86486a-9a54-4920-a4db-2553f907af92`。转换只读取其 175 个正式 Raw 数据集，
没有重新采集数据，也没有复制 Stage 18.1 审计样本。

本阶段只写 `data/clean/stage18/`，没有创建 DuckDB Fact 表、基本面 Feature、
Stage 19 或前端资产。

## Canonical Schema 与映射

六类 Clean 数据为：

- `financial_abstract`
- `financial_indicator`
- `balance_sheet`
- `income_statement`
- `cash_flow_statement`
- `valuation_snapshot`

五类历史数据统一为长表，保留证券、Provider、接口、变体、Raw dataset id、Raw
SHA-256、原字段、原指标名和来源分组。核心指标通过
`config/stage18_metric_mapping.yml` 显式映射；其余数值字段生成稳定的
`provider_field_<hash>` passthrough 名称，原字段名称不会丢失。本阶段只标准化 Provider
给出的指标，不重新计算 ROE、毛利率或其他 Feature。

A 股财务摘要执行“指标×报告日期”宽转长。A/H 股宽表指标和 A 股三大报表也转成长表；
港股三大报表沿用 Provider 的项目代码与项目名称。Clean 统一保存：

`report_date`、`announcement_date`、`update_date`、`fiscal_year`、
`fiscal_period`、`period_type`、`currency`、`value`、`source_unit`、
`canonical_unit`、`scale_factor` 和 `normalized_value`。

## PIT、币种与单位治理

PIT 状态使用公告日和更新日，而不是仅使用报告期：

- `PIT_ELIGIBLE`
- `ANNOUNCEMENT_DATE_UNAVAILABLE`
- `FUTURE_AS_OF_DATE`
- `UPDATE_DATE_UNAVAILABLE`
- `UPDATE_AFTER_AS_OF_DATE`

缺失公告日不会回填为报告期；公告日或更新日晚于 `2026-07-27` 时不能进入基准日
分析。A 股摘要/指标缺失公告日时保持不可用。港股报表缺失公告日时同样不具备 PIT
资格。

A 股币种为 CNY；报表优先使用 Provider 的 `CURRENCY`，摘要与指标记录
`market_default`。港股报表币种只在同一证券的财务指标数据给出唯一币种时，通过
`companion_financial_indicator` 传播。本阶段不执行 HKD/CNY 换算。原值、原单位、
缩放因子和标准值并存，不覆盖 Provider 原值。

## 重复与估值治理

港股年度与报告期变体按
`symbol + category + report_date + source_field` 比较。等值重复选择
`report_period` 为主记录，并保存全部 variant、dataset id 和 SHA lineage；数值冲突会
阻断阶段。

A 股财务摘要存在 11,658 个跨“选项”分组重复键，实际审计全部等值、冲突为 0。
同一规则选择稳定主记录，并在 `source_sections` 中保留全部来源。正式 Clean 共记录
18,482 条 `equivalent_duplicate` 主记录，没有无法解释的冲突。

A 股两个估值组件合并为每证券一行：PE/PB 来自估值比较接口，总市值/流通市值来自
规模比较接口。港股每证券一行。39 个 Raw 估值组件最终形成 23 行 Clean，全部保留
真实 `snapshot_time`，且 `eligible_for_as_of_date_analysis=false`。

## 中断资产

run `cc7a1864-e32a-48c5-a020-f0ea85a0357f` 在六类 Clean 写出后因报告辅助函数参数
顺序错误中断。其 12 个文件保持 append-only，并登记在
`stage18_3_interrupted.json`；该 run 明确
`formal_acceptance_eligible=false`、`stage18_4_authorized=false`，未被补写或复用。

本项目仅用于数据工程研究与测试，不构成投资建议。
