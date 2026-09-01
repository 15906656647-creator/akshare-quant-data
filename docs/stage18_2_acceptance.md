# Stage 18.2 基本面正式全量 Raw 采集验收

## 正式结论

正式完整 run `df86486a-9a54-4920-a4db-2553f907af92` 状态为 `PASS`。

- 证券范围：23/23，其中 A 股 16、港股 7。
- 计划与终态：175/175，全部 `PASS`；`FAIL=0`、`BLOCKED=0`。
- Stage 18.3：`authorized=true`、`started=false`。

## 覆盖与 Provider

|市场|类别/接口组|数据集|状态|
|---|---|---:|---|
|A|财务摘要、财务指标、三大报表|80|PASS|
|A|估值比较 + 规模比较组合能力|32|PASS|
|HK|财务指标及三大报表年度/报告期|56|PASS|
|HK|`stock_hk_financial_indicator_em` 估值|7|PASS|

A 股估值组合中，估值比较接口提供 PE/PB，规模比较接口提供总市值/流通市值；没有
要求单一组件承担全部字段。

## 完整性复核

- 正式 Raw 共 350 个文件：175 个非空 `data.parquet` 和 175 个
  `metadata.json`；临时文件为 0。
- Manifest 登记 354 个文件，逐文件独立复算大小与 SHA-256，差异为 0。
- 175 份 metadata 均为 `asset_role=fundamental_raw`、`audit_only=false`，且
  run id、证券身份和状态一致。
- 39 个估值快照全部保存 `snapshot_time`，全部明确不可用于基准日分析；136 个历史
  单元均有可解释的最早和最新报告日期。
- `fundamental_collection_plan.csv` 为 175 行且 `dataset_id` 唯一；Manifest 计划行、
  结果行均为 175；覆盖表为 A 股 16、港股 7。
- Stage 0 三个冻结文件哈希不变；Stage 17 正式 Raw 和 Stage 18.1 审计 Raw 的前后
  树摘要不变。
- 正式 Fact 表、Feature 和 Stage 19 资产均为 0；Stage 18.3 未启动。

## 测试门禁

- Stage 18.2、Stage 18.1、Stage 0 和项目结构定向离线测试：`53 passed`。
- 正式 run 后完整离线测试：`1023 passed, 1 failed`。
- 唯一失败为既有 Stage 8 测试债务：
  `tests/test_stage8_manual_import.py::test_default_cli_fails_closed_without_real_dataset`；
  错误签名仍为“期望返回码 1，实际返回码 0”。没有新增失败。
- 完整测试使用短 `basetemp`，没有 Stage 17 Windows 临时路径长度失败。

Stage 18.2 至此正式通过。本文只确认 Stage 18.3 具备入口资格，不启动标准化、入库、
Feature、Stage 19 或前端工作。

本项目仅用于数据能力研究与测试，不构成投资建议。
