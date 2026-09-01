# Stage 18.3 基本面 Raw 标准化与时间语义治理验收

## 正式结论

正式 run `66bebf1c-8b64-42a6-a970-1dbf1ecb395f` 状态为 `PASS`。

- 唯一上游：Stage 18.2 run `df86486a-9a54-4920-a4db-2553f907af92`。
- 上游验证：175/175 Raw、23/23 证券，其中 A 股 16、港股 7。
- 六类 Clean 全部通过；Stage 18.4 `authorized=true`、`started=false`。
- 没有启动数据库、Feature、Stage 19 或前端工作。

## Clean 结果

|类别|Clean 行数|
|---|---:|
|financial_abstract|79,917|
|financial_indicator|78,482|
|balance_sheet|124,211|
|income_statement|76,720|
|cash_flow_statement|109,656|
|valuation_snapshot|23|

历史 Clean 合计 468,986 行。所有 canonical key 唯一，报告日期 dtype 统一，所有历史行
均有明确 PIT 状态。核心字段 mapping 缺失为 0，无法解释的重复冲突为 0。

## 时间与估值门禁

- A 股三大报表中，基准日前公告且基准日前更新的记录标记为 `PIT_ELIGIBLE`。
- 2026-06-30 等报告期不会因为报告期早于基准日而自动获得资格；实际公告或更新日晚于
  基准日时分别标记 `FUTURE_AS_OF_DATE` 或 `UPDATE_AFTER_AS_OF_DATE`。
- A 股摘要/指标和港股历史数据缺失公告日时标记
  `ANNOUNCEMENT_DATE_UNAVAILABLE`，不回填、不推断。
- 39 个估值 Raw 组件合并为 23 行 Clean；23/23 均保留真实快照时间，基准日分析资格
  全部为 false。

## 完整性复核

- 正式 Clean 共 12 个文件：6 个非空 `data.parquet` 和 6 个 `metadata.json`；临时
  文件为 0。
- Manifest 登记 20 个文件，逐文件独立复算大小和 SHA-256，差异为 0。
- 六个 Clean 数据集的 metadata 均为 `asset_role=fundamental_clean`，并引用唯一
  Stage 18.2 run。
- Stage 0 冻结哈希、Stage 17 正式 Raw、Stage 18.1 审计 Raw、Stage 18.2 正式 Raw
  和报告在任务前后保持不变。
- DuckDB/正式 Fact 文件为 0，Feature 文件为 0，Stage 19 资产为 0。

## 测试门禁

- Stage 18.3、18.2、18.1、Stage 0 和项目结构定向离线测试：`61 passed`。
- 正式 run 后完整离线测试：`1031 passed, 1 failed`。
- 唯一失败为既有 Stage 8 测试债务：
  `tests/test_stage8_manual_import.py::test_default_cli_fails_closed_without_real_dataset`；
  错误签名仍为“期望返回码 1，实际返回码 0”。没有新增失败。
- 完整测试使用短 `basetemp`，没有 Stage 17 Windows 临时路径长度失败。

Stage 18.3 至此正式通过。该结论只授权后续独立任务进入 Stage 18.4 DuckDB 正式入库，
本任务没有启动 Stage 18.4。

本项目仅用于数据工程研究与测试，不构成投资建议。
