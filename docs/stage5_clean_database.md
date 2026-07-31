# 阶段5：数据清洗、字段映射与 DuckDB 建设

> 业务基准日：2026-07-27
> transform_run_id：`31635b34-d1ee-46d4-9c0f-32ae3f30d567`
> 阶段结论：**PASS**

## 1. 范围与来源

本阶段完全离线读取两个已验收 Raw 运行：

- 行情 source run：`39a6996e-36d7-4b73-b0b8-c38da4ae672e`，34/34 Raw；
- 财务及资金流 source run：`62bbe9df-6ed8-48d5-a06b-10fb90171ee0`，96/96 Raw。

开始及结束均验证了文件存在、非空、路径/run_id、大小、SHA-256 和 Parquet
可读性。阶段0三个冻结文件哈希未变化。未调用 AKShare 或任何财经网站。

## 2. 字段和单位策略

字段配置位于 `config/field_mapping.yml`，单位配置位于
`config/unit_mapping.yml`。字段登记结果：

| 状态 | 字段数 |
|---|---:|
| mapped | 60 |
| passthrough | 955 |
| unmapped | 9 |
| ambiguous | 0 |
| unknown unit | 127 |

9个未映射 spot 扩展字段没有猜测性映射，逐行完整保存在
`source_payload_json`，并登记于 `reports/stage5_unmapped_fields.csv`。财务宽表
按源字段生成稳定的 SHA-256 派生代码；原字段名、原值、源列、源行号和 Raw
路径均保留。

明确为百分数的源值除以100入库；成交量同时保存手和股，且
`volume_share = volume_lot * 100`。未知单位保留原值并标记 WARN，不进行换算。

## 3. Clean 结果

| dataset_id | Raw行 | Clean行 | 拒绝行 |
|---|---:|---:|---:|
| stock_daily_qfq | 11,602 | 11,602 | 0 |
| stock_daily_raw | 11,602 | 11,602 | 0 |
| stock_spot_full_market | 5,884 | 5,884 | 0 |
| stock_spot_target_16 | 16 | 16 | 0 |
| financial_abstract | 1,280 | 95,600 | 0 |
| financial_indicator | 336 | 28,560 | 0 |
| financial_statement_balance_sheet | 1,169 | 355,376 | 0 |
| financial_statement_profit_statement | 1,195 | 227,050 | 0 |
| financial_statement_cash_flow_statement | 1,170 | 280,800 | 0 |
| fund_flow | 1,920 | 1,920 | 0 |

财务行数增加来自宽表/转置宽表的确定性长表化，不是补造数据。每个源单元格均
保留为可追溯行项目，包括 NULL 原值。Clean 文件按 transform_run_id 追加写入，
通过临时文件和原子重命名落盘；旧运行不覆盖。

## 4. 点时性

三大报表使用真实 `NOTICE_DATE`。财务摘要和财务指标 Raw 不提供公告日期，
共124,160条长表记录保持 `announcement_date_status=unavailable` 和
`potential_lookahead=NULL`。未知公告日期记录不进入
`v_financial_point_in_time_safe`。

本次 Raw 中公告日期晚于基准日的行项目为0；安全视图包含未知公告日期数为0，
lookahead视图逻辑错误数为0。

## 5. 数据库

数据库：`database/akshare_data_test.duckdb`

- 12张表、7个视图；
- `dim_security`：16行；
- `fact_stock_daily`：23,204行；
- `fact_stock_spot`：5,900行；
- `fact_financial_abstract`：95,600行；
- `fact_financial_indicator`：28,560行；
- `fact_financial_statement`：863,226行；
- `fact_stock_fund_flow`：1,920行；
- 6张事实表重复业务键均为0，NULL主键均为0；
- 130个 Raw 文件均登记于 `source_file_manifest`，130条数据集血缘登记于
  `data_lineage`；
- SQL 可由 `sql/stage5_schema.sql` 和 `sql/stage5_views.sql` 从空库复建。

同一来源数据二次加载前后表行数完全一致，没有新增重复事实行。DuckDB事务
失败回滚由离线自动化测试验证。

## 6. 质量与警告

质量报告共45项 PASS、2项 WARN、0项 FAIL。WARN 均来自财务摘要和财务指标
缺少公告日期；这些记录被保留但不会被认定为点时安全。无拒绝行、无日期解析
失败、无重复业务键、无数据库锁。

Ruff 未安装，按任务规则记录为 WARN，未临时安装或修改依赖。

## 7. 可复建命令

```powershell
& ".\.venv\Scripts\python.exe" run_pipeline.py build-stage5 `
  --as-of-date 2026-07-27 `
  --market-run-id 39a6996e-36d7-4b73-b0b8-c38da4ae672e `
  --fundamental-run-id 62bbe9df-6ed8-48d5-a06b-10fb90171ee0 `
  --transform-run-id <new-uuid> `
  --clean-output-dir data/clean `
  --database-path <new-database-path> `
  --evidence-dir reports/evidence/stage5
```

现有数据库和 Clean 运行不会被静默覆盖；复建必须使用新的 transform_run_id
和新的数据库路径，或执行经审查的受控迁移。

## 8. 阶段边界

本阶段没有创建 Feature 数据，没有计算收益率、均线、波动率、活跃度、涨跌停、
单季度、TTM、同比、环比或新增财务比率，没有生成疑似主力行为分析或投资建议，
没有进入阶段6。
