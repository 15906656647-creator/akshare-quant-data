# 阶段5独立验收报告

> 验收日期：2026-07-30
> 正式 transform_run_id：`31635b34-d1ee-46d4-9c0f-32ae3f30d567`
> 验收方式：全程离线；正式产物只读；幂等性与回滚仅使用系统临时数据库
> 验收结论：**FAIL**
> 是否允许进入阶段6：**否**

## 1. 阶段5验收结论

阶段5状态：FAIL
是否允许进入阶段6：false
transform_run_id：`31635b34-d1ee-46d4-9c0f-32ae3f30d567`
market_source_run_id：`39a6996e-36d7-4b73-b0b8-c38da4ae672e`
fundamental_source_run_id：`62bbe9df-6ed8-48d5-a06b-10fb90171ee0`

唯一阻塞项是数据库全表幂等性。完全相同的正式输入在临时数据库副本复跑后，6张事实表均未增加，但`data_quality_issue`增加47行、`field_mapping_registry`增加1,024行。既有幂等报告通过给第二次加载传入空质量表和空映射表得出PASS，不能证明完整运行幂等。

## 2. 前置门禁

- `pip check`：PASS，退出码0。
- 完整pytest：161 passed，退出码0；`tests/conftest.py`对每个测试自动阻断真实socket。
- doctor：PASS；14/14依赖、9/9配置、20/20文件系统检查通过。
- 阶段0冻结哈希：3/3完全一致。
- 阶段3：PASS；本次Raw复验34/34。
- 阶段4：PASS；本次Raw复验96/96。专用Stage4 acceptance文件缺失，以阶段0—4最终验收及Raw实证替代。

## 3. Raw不可变性

阶段3 Raw预期数34，验证数34，哈希匹配34；阶段4 Raw预期数96，验证数96，哈希匹配96。全部存在、非空、Parquet可读取、大小匹配、路径含正确source run ID。前置命令前后正式Raw/Clean/DuckDB/manifest组合哈希一致，未发现Raw被修改。

## 4. Clean层验收

| dataset_id | source_rows | clean_rows | rejected | duplicate_keys | manifest_hash | clean_path |
|---|---:|---:|---:|---:|---|---|
| stock_daily_qfq | 11,602 | 11,602 | 0 | 0 | PASS | `data/clean/stock_daily/transform_run_id=31635b34-d1ee-46d4-9c0f-32ae3f30d567/adjust=qfq/data.parquet` |
| stock_daily_raw | 11,602 | 11,602 | 0 | 0 | PASS | `data/clean/stock_daily/transform_run_id=31635b34-d1ee-46d4-9c0f-32ae3f30d567/adjust=raw/data.parquet` |
| stock_spot_full_market | 5,884 | 5,884 | 0 | 0 | PASS | `data/clean/stock_spot/transform_run_id=31635b34-d1ee-46d4-9c0f-32ae3f30d567/full_market.parquet` |
| stock_spot_target_16 | 16 | 16 | 0 | 0 | PASS | `data/clean/stock_spot/transform_run_id=31635b34-d1ee-46d4-9c0f-32ae3f30d567/target_16.parquet` |
| financial_abstract | 1,280 | 95,600 | 0 | 0 | PASS | `data/clean/financial_abstract/transform_run_id=31635b34-d1ee-46d4-9c0f-32ae3f30d567/data.parquet` |
| financial_indicator | 336 | 28,560 | 0 | 0 | PASS | `data/clean/financial_indicator/transform_run_id=31635b34-d1ee-46d4-9c0f-32ae3f30d567/data.parquet` |
| financial_statement_balance_sheet | 1,169 | 355,376 | 0 | 0 | PASS | `data/clean/financial_statement/transform_run_id=31635b34-d1ee-46d4-9c0f-32ae3f30d567/statement_type=balance_sheet/data.parquet` |
| financial_statement_profit_statement | 1,195 | 227,050 | 0 | 0 | PASS | `data/clean/financial_statement/transform_run_id=31635b34-d1ee-46d4-9c0f-32ae3f30d567/statement_type=profit_statement/data.parquet` |
| financial_statement_cash_flow_statement | 1,170 | 280,800 | 0 | 0 | PASS | `data/clean/financial_statement/transform_run_id=31635b34-d1ee-46d4-9c0f-32ae3f30d567/statement_type=cash_flow_statement/data.parquet` |
| fund_flow | 1,920 | 1,920 | 0 | 0 | PASS | `data/clean/fund_flow/transform_run_id=31635b34-d1ee-46d4-9c0f-32ae3f30d567/data.parquet` |

10/10 Clean文件存在、可读、大小与SHA-256匹配；全部只含正式transform_run_id和对应source run ID。财务行数增加来自宽表确定性长表化，无拒绝行。

## 5. 字段映射

mapped=60，passthrough=955，unmapped=9，ambiguous=0，deprecated=0。必需字段未映射0，`source_dataset + source_field`重复0。9个spot未映射字段保存在`source_payload_json`，未静默删除；未发现按数值大小猜字段或单位。

## 6. 单位转换

- 日线与spot全量验证`volume_share = volume_lot × 100`，错误0。
- 日线、spot、资金流的百分数字段与Raw逐行比较，全部为百分数×0.01，错误0。
- 财务百分数字段依据显式`(%)`或`_YOY`证据全量核算，错误0；未知单位保持scale=1，错误0。
- 成交额、市值和资金流金额保持CNY元口径；NULL按逐行比较保持NULL，未发现填0或二次除以100。

## 7. 数据质量

- 日线：qfq/raw各16股、各11,602行，日期键差异0，OHLC错误0，负成交量/金额0。
- spot：全市场5,884行、目标16行；唯一快照为`2026-07-29T11:35:34.785065+08:00`，未伪装成基准日；目标PE/PB/总市值/流通市值均16/16非空。
- 财务摘要95,600行、财务指标28,560行，均覆盖16股；公告日期未知124,160行，正确保留并排除于安全视图。
- 三大报表合计863,226行，三类各覆盖16股，重复业务键0。
- 资金流1,920行、16股，Raw/Clean日期序列一致，范围`2026-01-13`至`2026-07-28`，未补日期。
- 质量CSV与数据库均47行：45 PASS、2 WARN、0 FAIL；拒绝行0。

## 8. DuckDB验收

数据库：`database/akshare_data_test.duckdb`；大小142,880,768字节；只读打开成功；12张表、7个视图；必需对象缺失0；数据库大小/SHA-256与正式manifest一致。

| 事实表 | 行数 | 股票数 | 重复键 | NULL必需键 |
|---|---:|---:|---:|---:|
| fact_stock_daily | 23,204 | 16 | 0 | 0 |
| fact_stock_spot | 5,900 | 5884 | 0 | 0 |
| fact_financial_abstract | 95,600 | 16 | 0 | 0 |
| fact_financial_indicator | 28,560 | 16 | 0 | 0 |
| fact_financial_statement | 863,226 | 16 | 0 | 0 |
| fact_stock_fund_flow | 1,920 | 16 | 0 | 0 |

## 9. 点时性视图

- point_in_time_safe：863,226行。
- announcement_unknown：124,160行。
- potential_lookahead：0行。
- 安全视图中的公告日期未知记录：0。
- 安全视图中公告日晚于基准日记录：0。

三类视图逻辑与实际数据一致，报告期未替代未知公告日期。

## 10. 数据血缘

Clean文件10个、正式manifest登记10个、数据库血缘130条；130/130可关联到存在且哈希匹配的Raw文件，130/130可关联到存在且哈希匹配的Clean文件，缺失血缘0。`data_lineage`本身未直接保存Raw/Clean哈希、target_table和loaded_at，本次通过`source_file_manifest`、正式manifest、dataset映射及`etl_run`完成关联，记WARN。

## 11. 幂等性和事务

- 实际离线验证：是，仅在系统临时目录。
- 同源完整复跑：事实表新增0；`data_quality_issue`新增47；`field_mapping_registry`新增1,024，**FAIL**。
- 旧Clean覆盖：否；正式Clean未参与写入。
- 相同transform_run_id：事实、运行和血缘键阻止重复，但质量/映射登记缺乏幂等键或去重策略。
- 事务回滚：PASS。向空临时库注入重复事实键触发`ConstraintException`后，12张表均为0行。
- 正式数据库：测试前后SHA-256均为`d00f8d6017f5f74b3945f158af70153aef378af0c39f867f5dbd1c1cb1b3c372`，未修改。

最小修复建议：为质量与映射登记定义稳定业务键/唯一约束，并在同一事务中使用幂等upsert或先按transform_run_id受控删除再插入；随后用完整非空输入重跑临时副本验收。此任务不修改源码。

## 12. 实际执行命令

| 命令 | 退出码 | 秒 | 网络 | 修改正式产物 | 结果 |
|---|---:|---:|---|---|---|
| `.venv\Scripts\python.exe -m pip check` | 0 | 3.284 | 否 | 否 | PASS |
| `.venv\Scripts\python.exe -m pytest -q` | 0 | 24.156 | 否 | 否 | 161 passed; autouse socket guard |
| `.venv\Scripts\python.exe run_pipeline.py show-config --as-of-date 2026-07-27` | 0 | 0.14 | 否 | 否 | 16 stocks; ETHUSDT exact match |
| `.venv\Scripts\python.exe run_pipeline.py doctor --as-of-date 2026-07-27 --output reports/stage5_acceptance_doctor.json` | 0 | 1.91 | 否 | 否 | PASS |
| `.venv\Scripts\python.exe run_pipeline.py validate-stage5 --as-of-date 2026-07-27 --database-path database/akshare_data_test.duckdb` | 0 | 0.819 | 否 | 否 | read-only validator PASS |
| `independent Raw/Clean/mapping/unit/DuckDB/lineage verifier` | 0 | 见JSON | 否 | 否 | core data checks PASS; acceptance files refreshed |
| `temporary DuckDB complete-input replay and rollback injection` | 0 | 4.468 | 否 | 否 | idempotency FAIL; transaction rollback PASS; formal DB hash unchanged |

Ruff未安装，因此没有伪造lint结果，也未修改依赖。

## 13. 需要用户在本地PowerShell执行的操作

需要本地PowerShell执行的操作：无

## 14. 阶段边界

`data/feature`和`data/export`无业务文件；数据库无feature、return、moving-average、volatility、activity、limit、TTM、同比或环比对象；未生成阶段6指标，未调用真实网络，未修改Raw。未计算收益率、均线、波动率、活跃度、涨跌停、单季度、TTM、同比、环比或新财务比率。

## 15. 安全和Git

未发现有效凭据；正式Stage5 manifest无个人绝对路径；`.env`未被Git跟踪。分支`master`，HEAD=`9aea2edb60afdc8930953188149398b25c71675d`。Stage1—5大量关键文件未跟踪，属于显著交付追溯风险；在修复并复验通过后，建议人工审阅再建立Git检查点，本任务未执行stage/commit。

## 16. 失败和警告

失败：

1. 完整同源输入在临时数据库副本重放时，data_quality_issue 新增47行（47→94），field_mapping_registry 新增1,024行（1,024→2,048）；数据库写入并非全表幂等，且既有stage5_idempotency_check.json的PASS通过传入空质量/映射表掩盖了该问题。

警告：

1. CODEX_STAGE5_PROMPT.md缺失，使用用户附件作为验收契约。
2. docs/stage4_acceptance.md与reports/stage4_acceptance.json缺失；以docs/stage0_4_final_acceptance.md及Stage4 repair/manifest实证替代。
3. Ruff未安装，未临时安装。
4. 正式Stage5 manifest缺少as_of_date、status及report_files登记；10个Clean文件和数据库的大小/SHA-256仍全部匹配。
5. data_lineage未直接存储source_file_sha256、clean_file_sha256、target_table、loaded_at；本次通过source_file_manifest、Stage5 manifest、dataset映射和etl_run完成外部关联。
6. Stage1-5关键源码、配置、SQL、测试、报告、Raw/Clean和数据库大量未纳入Git，交付可追溯性较弱。
7. 资金流Raw/Clean最晚日期为2026-07-28，晚于业务基准日一天；与阶段4正式Raw一致，且未伪称多年历史。


## 17. 验收产物

- `docs/stage5_acceptance.md`
- `reports/stage5_acceptance.json`
- `reports/stage5_acceptance_clean_validation.csv`
- `reports/stage5_acceptance_database_objects.csv`
- `reports/stage5_acceptance_table_counts.csv`
- `reports/stage5_acceptance_quality_summary.csv`
- `reports/stage5_acceptance_mapping_summary.csv`
- `reports/stage5_acceptance_lineage_validation.csv`
- `reports/stage5_acceptance_raw_immutability.csv`
- `reports/stage5_acceptance_doctor.json`

## 18. 阶段6入口结论

> 阶段5尚未通过独立验收，当前禁止进入阶段6。请先修复本报告列出的Raw不可变性、Clean数据、字段映射、单位转换、数据库、点时性、血缘、幂等性、事务、安全或阶段边界问题。
