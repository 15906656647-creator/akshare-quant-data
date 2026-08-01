# 阶段 10：基本面分析与估值分析

## 边界与数据来源

阶段 10 是完全离线的分析层，只读取阶段 5 DuckDB 的
`fact_financial_statement` 与 `fact_stock_spot`。所有运行必须显式传入
`as_of_date`；财务记录必须具有不晚于该日期的公告日，并且不能标记为未来数据。
本阶段不调用 AKShare、HTTP 客户端或网页抓取，也不改写阶段 7、8、9 的数据库、
配置、报告或 fail-closed 状态。

## 标准化与版本

`raw.financial_statement` 保存证券、报告期、公告日、更新时间、来源、来源引用、
单位、累计标志、来源运行和版本键。阶段 5 当前没有可靠的更新时间字段时，
`update_time` 保持 NULL，不能由系统时间伪造。不同来源运行和公告版本分别保存；
同一版本中的重复报告事实以 ERROR 拒绝。

标准字段包括总资产、总负债、股东权益、营业收入、营业成本、营业利润、利润总额、
净利润、归母净利润、扣非归母净利润、经营活动现金流净额和基本 EPS。源字段映射、
单位和模型版本来自 `config/stage10.yml`。同一标准指标存在多个源字段时，按
`priority` 顺序确定唯一事实，同时保留 `source_field`、`selected_source`、
`conflict_flag`；来源值不一致时记录质量问题，不执行随机覆盖。

## 累计转单季度与指标

- Q1 直接使用第一季度累计值。
- Q2 = H1 累计值 - Q1 累计值。
- Q3 = Q1-Q3 累计值 - H1 累计值。
- Q4 = 全年累计值 - Q1-Q3 累计值。
- 缺少前期累计时单季度值保持 NULL，并标记 `missing_prior_cumulative`。
- 单位冲突和同版本重复报告直接失败，不因输入顺序改变结果。

指标层保存收入及利润同比、收入及利润 TTM、毛利率、净利率、ROE、经营现金流、
经营现金流/利润、资产负债率和基础财务事实，并保存 `calculation_version`、来源期间
和 `run_id`。分母为零或前期数据缺失时不填 0。

## 估值与摘要

`analysis.valuation_snapshot` 只接受 `snapshot` 类型，保存快照时间、PE、PB、市值、
来源和状态。负 PE 标记为 `loss-making`；PE/PB 缺失保持 NULL；非正 PB 标记为
`invalid`。当前快照不能转写成历史 PE/PB。

`analysis.fundamental_summary` 输出收入增长、利润增长、盈利能力分、财务健康分、
估值状态和基于真实指标的解释。分数是描述性数据摘要，不是估值高低或交易建议。

## 数据库、质量门禁和 CLI

独立数据库包含 `raw.financial_statement`、`clean.financial_fact`、
`feature.fundamental_indicator`、`analysis.fundamental_summary`、
`analysis.valuation_snapshot`、`quality.stage10_quality_result` 和
`audit.stage10_run`。主键包含 `run_id`，同 run 重跑幂等、跨 run 保留历史；latest
视图只指向最新 PASS run；整次写入失败时事务回滚。

质量检查覆盖 Schema、必需字段、单位、版本唯一性、公告日期、金额、累计转换、
同比/TTM相关指标、比率范围、估值类型、负 PE、缺失 PE/PB、run_id、数据库/报告
一致性、禁止文件和投资建议用语。DuckDB、CSV、JSON、Markdown 对发布字段执行
逐字段比较（NULL 统一、浮点绝对误差不超过 `1e-12`、稳定排序）；所有 ERROR 失败均阻断发布。

```powershell
python run_pipeline.py analyze-fundamental --help
python run_pipeline.py analyze-fundamental --as-of-date 2026-07-27 --input-manifest reports/stage5_verified_manifest.json --validate-only
python run_pipeline.py analyze-fundamental --as-of-date 2026-07-27 --input-manifest reports/stage5_verified_manifest.json --dry-run
```

`validate-only` 只读且不创建输出目录，并校验 Stage 5 manifest 的阶段、PASS 状态、
验证标签、run_id 及数据库 `etl_run` 谱系；`dry-run` 只在内存计算；默认错误不显示
traceback，只有 `--debug` 显式开启。系统仅用于研究和数据能力测试，不构成投资建议。
