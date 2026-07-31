# 阶段5最终复验与候选数据库落地审查

> 验收日期：2026-07-30
> 最终状态：**PASS**
> 是否允许进入阶段6：**是**
> 阶段6数据库：`database/akshare_data_test_stage5_repaired.duckdb`

## 1. 结论

原正式库保持只读且仍是旧元数据Schema；未对它执行迁移或覆盖。已从原库复制并
迁移得到独立版本化候选库 `database/akshare_data_test_stage5_repaired.duckdb`。候选库通过对象、行数、
业务键、NULL键、事实内容哈希、全量非空输入幂等复跑、payload冲突回滚、
资金流as-of和财务点时集合关系验收。

## 2. 正式库检查

- SHA-256：`d00f8d6017f5f74b3945f158af70153aef378af0c39f867f5dbd1c1cb1b3c372`
- `issue_key`：无
- `mapping_key`：无
- 两个唯一索引：无
- 资金流安全视图：无
- 需要迁移：是；正式库迁移已应用：否

## 3. 候选库

- 路径：`database/akshare_data_test_stage5_repaired.duckdb`
- SHA-256：`ad466df89b30cf305de16fd9184057c4e0779bf9118f98393301857396928026`
- 表：12
- 视图：8
- Schema版本：`stage5_metadata_idempotency_v2`
- 迁移状态：PASS

## 4. 全部12张表

| table_name | row_count | duplicate_key_count | null_key_count | content_hash | status |
|---|---:|---:|---:|---|---|
| data_lineage | 130 | 0 | 0 | `e6d49c0201652c2774ef170a1d5733d20697b208c4bfa2c111f23c64f85bfa9a` | PASS |
| data_quality_issue | 47 | 0 | 0 | `c95e1fee32178b5b8d59ab064ef84da7c7b2a0b7074e899cbb49db3da08612e1` | PASS |
| dim_security | 16 | 0 | 0 | `0d32ecdd2e78f8a379a7fc21e0d075368b2f7a828929e9bd8be6f3df30d5c65a` | PASS |
| etl_run | 1 | 0 | 0 | `8e3b70fa2d9f3c0f926202f507770ff4fc38d4613b0c7df7139d3244f9b15864` | PASS |
| fact_financial_abstract | 95,600 | 0 | 0 | `6f2a24644235cb973d784ff7ed581688f071aa9552e5ea981de08543b5fdcd36` | PASS |
| fact_financial_indicator | 28,560 | 0 | 0 | `3739a53df71f0830eb52c5958a6e8144a41fdf3f5b94ea8bc9fa8a9228f1d807` | PASS |
| fact_financial_statement | 863,226 | 0 | 0 | `5cb16ffdcec9d9c52db81c80390bab74451905822b8e0521d676ea6ad9af49a4` | PASS |
| fact_stock_daily | 23,204 | 0 | 0 | `90f67465e9d1758ea072b9e53bea15e36dc39c580c357f82854e65f9856283f9` | PASS |
| fact_stock_fund_flow | 1,920 | 0 | 0 | `c1186c92bb4f024a41228b53ff978e00a68361bb9116ae4f3073c4ff81b49f8e` | PASS |
| fact_stock_spot | 5,900 | 0 | 0 | `06ddfaf9ca1ac10f0a327e5b45d48d8e4090140b727fbc7faea8b1c1b37d9c39` | PASS |
| field_mapping_registry | 1,024 | 0 | 0 | `f25d535b105fd0561caf5208f26d63e40c38844dddd5927a088a037bb324d834` | PASS |
| source_file_manifest | 130 | 0 | 0 | `d2e3a53b733cf97244e01e8e124dc378ec58f5aa2d657942c1f25bb657e6acab` | PASS |

## 5. 完整幂等复跑

- 完整输入：10个Clean、47条质量、1,024条映射、130条Raw登记、130条血缘。
- `data_quality_issue`：47 → 47。
- `field_mapping_registry`：1,024 → 1,024。
- 12表行数、业务键哈希、完整内容哈希：全部不变。

## 6. 冲突与回滚

相同key和相同内容被跳过；相同key和不同内容被拒绝。mapping与quality两类
冲突均触发整体事务回滚，回滚后12表内容哈希与事务前一致，未发现部分写入。

## 7. 资金流安全视图

- 完整事实：1,920
- 晚于as_of_date：16
- 安全视图：1,904
- 安全视图未来行：0

## 8. 财务点时视图

三个视图同源于 `v_financial_all`；该基础视图是财务摘要、财务指标和财务报表
三张事实表的 `UNION ALL`，共
987,386行。safe为
863,226行，unknown为
124,160行，lookahead为
0行；三组两两交集均为0，
未覆盖记录为0。safe中
公告日期未知和晚于基准日的记录均为0。

## 9. 不可变性与边界

- 阶段0：PASS
- 阶段3 Raw：34/34，PASS
- 阶段4 Raw：96/96，PASS
- 阶段5 Clean：10/10，PASS
- 原正式DuckDB：PASS
- 原manifest：PASS
- 修复附录：PASS
- 血缘Raw/Clean双向哈希：130/130
- Feature文件：0；阶段6数据库对象：0；真实网络访问：否。

## 10. PowerShell与Git

需要本地PowerShell执行的操作：无。

Git仍有大量阶段1–5源码、SQL、配置、测试、报告与数据产物未跟踪。建议进入
阶段6前人工审阅并建立检查点；本次未stage、未commit。

## 11. 阶段6入口

阶段6必须显式使用 `database/akshare_data_test_stage5_repaired.duckdb`，并只通过
`v_stock_fund_flow_as_of_safe`读取截至`2026-07-27`的资金流。

> 阶段5已经完成最终闭环验收。修复后的正式可用数据库包含稳定元数据键、唯一约束、完整安全视图，并通过完整非空输入全表幂等、冲突回滚、Raw和Clean不可变性验证；当前可以进入阶段6，且阶段6必须使用报告中明确的数据库路径和as-of安全视图。
