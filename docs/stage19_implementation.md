# Stage 19 A股涨跌停事件系统实施记录

## 范围与入口

Stage 18 最终验收 `9779de8b-6504-4efc-a473-bf07537a7a8d` 为 `PASS`，其
`downstream_contract.json` 明确 `stage19_authorized=true`。本阶段只实施 A 股涨跌停事件
系统，没有启动 Stage 20，也没有把港股或 ETHUSDT 套入 A 股规则。

分析基准日为 `2026-07-27`，区间为 `2025-07-27` 至 `2026-07-27`，目标为 Stage 0
冻结的 16 只 A 股。价格输入只读取 Stage 17 正式 PASS 批次
`4a5599fb-9e60-4013-9c0c-69fcc25a98b2` 中 `market=A, adjust=raw` 的 16 个 Parquet，
并逐文件复算 SHA-256；qfq/hfq 不进入事件识别。

## 复用与扩展

- 复用 Stage 8 `LimitRule`、`SecurityStatus`、按有效日 temporal lookup、Decimal/tick
  舍入、半 tick 容差和 fail-closed 事件识别。
- 复用 Stage 8 人工数据集格式、来源登记、SHA-256、区间与覆盖校验。
- 新增 `analysis.limit_event_candidate` 候选层与 `analysis.limit_event` 正式层；正式层只在
  G1–G9 全部 PASS 后写入。
- 新增逐 symbol 交易日序列的连板、次日开高低收收益、3/5/10 日 forward return、MFE
  与 MAE。尾部窗口不足时保留 NULL。
- 新增 per-symbol、ST/LISTING 双维度覆盖矩阵，以及 gap、overlap/conflict、UNKNOWN、
  missing source 和 manual review 检查。
- 新增机器可读 G1–G9 门禁和正式统计表。门禁 BLOCKED 时所有正式统计值为 NULL，
  `availability_status=BLOCKED`。

## 数据模型

`sql/stage19_schema.sql` 建立或扩展：

- `reference.security_status_history`
- `reference.limit_rule_history`
- `analysis.limit_event_candidate`
- `analysis.limit_event`
- `analysis.limit_event_statistics`
- `quality.stage19_quality_result`
- `governance.stage19_release_gate`
- `audit.stage19_run`

`is_st=NULL` 保留 UNKNOWN 语义；任何 UNKNOWN、缺失状态或未验证状态均不能进入正式事件。
数据库写入使用 `run_id` 主键、事务和同 run 先删后插，支持幂等重跑。

## 执行

正式离线命令：

```powershell
.venv\Scripts\python.exe run_pipeline.py stage19-build `
  --as-of-date 2026-07-27 `
  --run-id 8d1e4e7b-4a97-4c2e-9e9e-stage19blocked
```

命令退出码 `2` 表示框架执行成功但正式事件发布门禁 BLOCKED；不是计算崩溃。

## 当前限制

规则数据集 12 条记录校验 READY，来源字段与哈希齐全，但 12/12 均为
`approved_with_waiver`，没有双人正式复核。权威 `security_status_history.csv` 不存在，
有效状态记录为 0。因而候选层只保存逐日 `unresolved/missing_security_status` 证据，
不会猜测 NON_ST，也不会发布正式事件。

历史 `s14_verification.json` 曾写 `PASS`，但其所依赖的正式 Stage 8 重建当前不是 PASS，且
该结论已被后续根因报告和 Stage 15 条件封板推翻。Stage 19 明确将该陈旧 PASS 忽略，
G8/G9 同时保持 BLOCKED。

## Formal-release path hardening

后续审计确认原实现只完整覆盖 BLOCKED 路径：`build_stage19()` 无条件生成
`blocked_statistics()`，且持久化没有把合格候选写入 `analysis.limit_event`。本次在 Stage 19
范围内完成以下补强：

- Gate BLOCKED：正式事件强制为空；全部正式统计保持 NULL/BLOCKED，并保存 blocker。
- Gate PASS：先以不可绕过的资格过滤器选取 `limit_up/limit_down + verified + pass`，并要求
  `rule_version`、`security_status_version` 和计算方法完整；unresolved/unknown/blocked
  候选不能进入正式表。
- PASS 统计从正式事件集合计算，而不是从 candidate 全集计算。计数和最大 streak 在完整、
  合法的无事件样本中允许为 0；收益没有事件或 forward window 不足时为
  NULL/UNAVAILABLE，并提供原因。
- `official_event_count` 使用实际合格正式事件行数。
- 每次同 `run_id` 持久化均先清理 candidate、official event、statistics、quality 和 gate；
  因此 PASS→BLOCKED 不会残留旧正式事件，BLOCKED→PASS 不会残留旧 NULL 统计。

Synthetic fixture 已验证 G1–G9 PASS、涨停、跌停、unresolved 混合候选、正式过滤、真实统计、
合法 0、不可用 NULL、同 run 幂等和双向 Gate 切换。该测试只证明技术正向路径闭环，不是
真实 Stage 19 PASS。
