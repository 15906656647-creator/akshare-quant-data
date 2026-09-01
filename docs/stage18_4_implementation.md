# Stage 18.4 DuckDB 正式入库实现

## 阶段边界

Stage 18.4 仅将 Stage 18.3 正式 Clean run `66bebf1c-8b64-42a6-a970-1dbf1ecb395f` 离线装载到新的、run 隔离的 DuckDB。实现不调用网络，不重新采集或标准化，不计算基本面 Feature，也不创建 Stage 19 或前端资产。

CLI 命令为：

```text
python run_pipeline.py stage18-db-load --as-of-date 2026-07-27 --upstream-run-id 66bebf1c-8b64-42a6-a970-1dbf1ecb395f
```

配置位于 `config/stage18_4.yml`。配置冻结唯一上游、六张事实表、逐表行数、总行数、证券范围、估值门禁、数据库与报告路径。

## 上游和不可变性治理

任何数据库目录创建之前，入口先验证 Stage 18.3 的 `PASS`、`stage18_4_authorized=true`、`stage18_4_started=false`、Stage 18.2 lineage、六类 Clean manifest/metadata/row count/SHA-256。只读取正式 Clean 目录，不读取中断 run。

运行前后分别计算 Stage 0、Stage 17 Raw、Stage 18.1 audit Raw、Stage 18.2 Raw 和 Stage 18.3 formal Clean 指纹。任一变化都会阻止 Stage 18.4 PASS。

## 数据库写入

数据库路径为 `database/stage18/run_id=<run_id>/fundamentals.duckdb`，既有 run/report 或数据库目录禁止覆盖。六类 Parquet 通过 DuckDB 原生 schema 建表，并显式设置 `hive_partitioning=false`，避免从目录名误推断额外 `run_id` 列。

六张表的建表、全量装载和事务内一致性检查均在同一个 `BEGIN TRANSACTION` 中完成。任一检查失败即 `ROLLBACK`；全部通过才 `COMMIT`、`CHECKPOINT` 并关闭连接。数据库关闭后计算最终 SHA-256，随后仅以 read-only 方式复开验证。

## 一致性检查

验收覆盖逐表精确行数、物理列顺序和 DuckDB 类型、全行 `EXCEPT ALL` 双向多重集等值、治理与 lineage 列等值、确定性抽样、canonical key/valuation symbol 唯一性、日期 NULL 统计、PIT/eligibility 联合分布、23 个证券及 16A/7HK 身份、估值 23/23 不可用于基准日分析，以及 symbol/market/report_date/category/table/pit_status 基础过滤。

本阶段保留全部历史 Clean 行，包括非 `PIT_ELIGIBLE` 行；不推断公告日或更新日，不执行汇率转换，不改写估值时间语义。
