# 阶段5元数据全表幂等性修复报告

> 修复日期：2026-07-30
> 正式transform_run_id：`31635b34-d1ee-46d4-9c0f-32ae3f30d567`
> 修复状态：**PASS**
> 正式数据库修改：**否**

## 根因与修复

原装载器对六张事实表使用稳定业务键跳过重复，但对
`data_quality_issue`和`field_mapping_registry`无条件追加；原幂等测试又在
第二次加载时传入空质量表和空映射表，掩盖了元数据翻倍。

修复后两表使用统一的规范JSON和SHA-256生成稳定key与record_hash。相同key和
相同payload跳过；相同key但payload不同抛出
`idempotency_payload_conflict`并回滚整个事务。唯一索引在数据库层兜底。

## 完整非空输入复跑

输入为10个Clean数据集、47条质量记录、1,024条字段映射、130条Raw manifest
登记和130条血缘记录。

| table_name | first_count | second_count | first_hash | second_hash | status |
|---|---:|---:|---|---|---|
| data_lineage | 130 | 130 | `e6d49c0201652c2774ef170a1d5733d20697b208c4bfa2c111f23c64f85bfa9a` | `e6d49c0201652c2774ef170a1d5733d20697b208c4bfa2c111f23c64f85bfa9a` | PASS |
| data_quality_issue | 47 | 47 | `c95e1fee32178b5b8d59ab064ef84da7c7b2a0b7074e899cbb49db3da08612e1` | `c95e1fee32178b5b8d59ab064ef84da7c7b2a0b7074e899cbb49db3da08612e1` | PASS |
| dim_security | 16 | 16 | `0d32ecdd2e78f8a379a7fc21e0d075368b2f7a828929e9bd8be6f3df30d5c65a` | `0d32ecdd2e78f8a379a7fc21e0d075368b2f7a828929e9bd8be6f3df30d5c65a` | PASS |
| etl_run | 1 | 1 | `8e3b70fa2d9f3c0f926202f507770ff4fc38d4613b0c7df7139d3244f9b15864` | `8e3b70fa2d9f3c0f926202f507770ff4fc38d4613b0c7df7139d3244f9b15864` | PASS |
| fact_financial_abstract | 95600 | 95600 | `6f2a24644235cb973d784ff7ed581688f071aa9552e5ea981de08543b5fdcd36` | `6f2a24644235cb973d784ff7ed581688f071aa9552e5ea981de08543b5fdcd36` | PASS |
| fact_financial_indicator | 28560 | 28560 | `3739a53df71f0830eb52c5958a6e8144a41fdf3f5b94ea8bc9fa8a9228f1d807` | `3739a53df71f0830eb52c5958a6e8144a41fdf3f5b94ea8bc9fa8a9228f1d807` | PASS |
| fact_financial_statement | 863226 | 863226 | `5cb16ffdcec9d9c52db81c80390bab74451905822b8e0521d676ea6ad9af49a4` | `5cb16ffdcec9d9c52db81c80390bab74451905822b8e0521d676ea6ad9af49a4` | PASS |
| fact_stock_daily | 23204 | 23204 | `90f67465e9d1758ea072b9e53bea15e36dc39c580c357f82854e65f9856283f9` | `90f67465e9d1758ea072b9e53bea15e36dc39c580c357f82854e65f9856283f9` | PASS |
| fact_stock_fund_flow | 1920 | 1920 | `c1186c92bb4f024a41228b53ff978e00a68361bb9116ae4f3073c4ff81b49f8e` | `c1186c92bb4f024a41228b53ff978e00a68361bb9116ae4f3073c4ff81b49f8e` | PASS |
| fact_stock_spot | 5900 | 5900 | `06ddfaf9ca1ac10f0a327e5b45d48d8e4090140b727fbc7faea8b1c1b37d9c39` | `06ddfaf9ca1ac10f0a327e5b45d48d8e4090140b727fbc7faea8b1c1b37d9c39` | PASS |
| field_mapping_registry | 1024 | 1024 | `f25d535b105fd0561caf5208f26d63e40c38844dddd5927a088a037bb324d834` | `f25d535b105fd0561caf5208f26d63e40c38844dddd5927a088a037bb324d834` | PASS |
| source_file_manifest | 130 | 130 | `d2e3a53b733cf97244e01e8e124dc378ec58f5aa2d657942c1f25bb657e6acab` | `d2e3a53b733cf97244e01e8e124dc378ec58f5aa2d657942c1f25bb657e6acab` | PASS |

重点结果：

- `data_quality_issue`：47 → 47；
- `field_mapping_registry`：1,024 → 1,024；
- 全部12张正式表行数、业务键哈希和内容哈希完全一致。

## 冲突与事务

- 相同key、相同内容：跳过；
- 相同key、不同内容：拒绝；
- mapping和quality冲突均验证整体回滚；
- 回滚后12张表内容与事务前完全相同，未发现部分写入。

## 正式产物不可变性

- 阶段3 Raw：34/34；
- 阶段4 Raw：96/96；
- 阶段5 Clean：10/10；
- 正式DuckDB SHA-256前后均为
  `d00f8d6017f5f74b3945f158af70153aef378af0c39f867f5dbd1c1cb1b3c372`；
- 原正式manifest SHA-256前后均为
  `e61f0bfc7b147e203a2c88042592cc9f9993b4f720f266103e69ecbe8fc11c92`。

## 资金流as_of保护

完整事实表保留晚于`2026-07-27`的16行；
`v_stock_fund_flow_as_of_safe`包含1904行，晚于基准日的行数为
0。Raw未修改。

## 阶段边界

未访问网络，未创建Feature数据，未计算阶段6指标。正式数据库只读，所有迁移、
完整复跑和冲突注入均发生在系统临时目录。

## 测试门禁

- `pip check`：PASS；
- 修复前完整pytest：161 passed；
- 修复后完整pytest：168 passed；
- 新增阶段5专项测试：7项；
- 完整非空输入复跑：PASS；
- mapping/quality冲突与整体回滚：PASS；
- 默认socket阻断：PASS；
- `compileall -q src`：PASS；
- `git diff --check`：PASS；
- Ruff：未安装，按规则记WARN，未修改依赖。
