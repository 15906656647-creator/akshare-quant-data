# Stage 18.5 PIT 基本面 Feature 实现

## 阶段边界

Stage 18.5 以 Stage 18.4 formal run `b2d7bf6c-b7c7-4760-b16d-33640111cb11` 的 DuckDB 为唯一只读输入，基准日固定为 `2026-07-27`。本阶段不采集、不清洗、不修改数据库、不使用估值快照、不启动 Stage 18.6 或 Stage 19。

CLI：

```text
python run_pipeline.py stage18-feature-build --as-of-date 2026-07-27 --upstream-run-id b2d7bf6c-b7c7-4760-b16d-33640111cb11
```

入口在任何 Feature 写入前验证 Stage 18.4 的 `PASS`、Stage 18.5 授权、manifest 闭合以及数据库固定 SHA-256。数据库使用 DuckDB `read_only=True` 打开，运行前后复算 SHA-256。

## PIT 输入

只有同时满足以下条件的三大报表行可以进入计算：

- `pit_status = PIT_ELIGIBLE`；
- `eligible_for_as_of_date_analysis = true`；
- `announcement_date` 和 `update_date` 均存在且不晚于 `2026-07-27`；
- `mapping_status = CORE_MAPPED`。

摘要、分析指标中的非 PIT 行以及 23 条 valuation snapshot 均不进入计算。公告日或更新时间不会被推断或回填，币种不会转换。

## Feature 口径

输出采用 23 个证券 × 12 个定义的长表，每个单元均为 `PASS` 或 `UNAVAILABLE`。基础规模项和同报告期比率选择最新 PIT 可见报告期；同比严格匹配上一财年相同 `fiscal_period`；ROA/ROE 仅使用年度利润和当前/上一年度平均资产或权益。缺少输入、不可比期间、混合币种或分母为零时输出 `UNAVAILABLE`，不填 0。

每行保存公式、期间语义、输入报告日/公告日/更新时间、source field/table、canonical key、Raw/Clean run lineage、SHA-256、币种及完整 JSON lineage。

## 验收

验收检查证券和 Feature 闭合集、终态、lineage、未来数据、公告日推断、估值泄漏、同期间匹配、分母零处理、币种以及上游资产不可变性。Feature Raw 为 append-only Parquet，正式 run 目录禁止覆盖。
