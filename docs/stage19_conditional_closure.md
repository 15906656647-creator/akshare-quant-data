# Stage 19 条件封板决策

> 决策日期：2026-08-30
> 业务基准日：2026-07-27
> 管理状态：`CONDITIONALLY_CLOSED`
> 技术框架状态：`PASS`
> 正式事件发布状态：`BLOCKED`

## 1. 决策

Stage 19 的 Schema、候选计算、质量校验、发布门禁、BLOCKED 分支和 synthetic PASS 分支
均已完成并通过自动测试，可以在治理层条件封板。条件封板不改变 Stage 19 的真实运行状态，
不等于正式验收 `PASS`，也不发布任何正式涨跌停事件。

以下状态同时成立：

- Stage 19 管理状态为 `CONDITIONALLY_CLOSED`；
- Stage 19 技术框架状态为 `PASS`；
- Stage 19 正式事件发布状态保持 `BLOCKED`；
- 正式事件可用状态保持 `BLOCKED/UNAVAILABLE`；
- Stage 20 受限入口获准，授权模式为 `RESTRICTED/NON_EVENT_ONLY`；
- Stage 20 完整入口未获准；
- 本决策不代表 Stage 20 已经开始。

## 2. 决策依据

- Stage 18 正式验收为 `PASS`，合法授权 Stage 19 入口；
- Stage 19 技术框架、BLOCKED 分支和 synthetic PASS 分支均已验证；
- 全仓自动测试 `1067 passed, 0 failed`；
- 真实 Stage 19 run 保持 3,862 条 candidate、0 条 official event、160 个
  NULL/BLOCKED 正式统计；
- G1、G2、G4、G5、G8、G9 保持 `BLOCKED`，G3、G6、G7 为 `PASS`；
- `stage20_authorized=false` 是条件封板前的正确历史状态，本决策通过独立受限合同授权
  Stage 20 非事件范围，不覆盖或改写该历史记录。

## 3. 未解决阻塞项

以下 remediation 项保持 `OPEN`：

1. 缺少可审计、完整覆盖的权威 `security_status_history`；
2. 证券状态来源审计未完成；
3. 规定的人工复核未完成；
4. Stage 8 正式重建未通过；
5. S15-14 当前补验未通过。

## 4. Stage 20 受限授权

本决策唯一直接授权的下一阶段为 Stage 20，且只允许非事件功能。受限入口为
`AUTHORIZED`，完整入口为 `NOT_AUTHORIZED`。

允许范围：股票、市场、时间及非事件指标筛选；已通过各自质量门禁的 A 股、港股、
ETHUSDT 行情与 K 线；均线、成交量、成交额、换手率和非事件量价指标；Stage 18 正式
PASS 范围内的基本面与 `fundamental_features`；代码、时间和非事件指标维度比较。

分钟 K 线只能消费已通过相应市场、标的、周期质量门禁的正式数据；可行性失败、跳过或
报告层衍生样本不因本决策自动可用。

## 5. 明确禁止范围

Stage 20 不得开发或发布正式涨停/跌停次数、事件列表、连板/连续跌停、事件次日表现、
事件后 3/5/10 日收益、事件 MFE/MAE、事件排名、事件筛选或任何依赖 Stage 19 正式事件
的评分。前端不得自行用涨跌幅、当前名称或 candidate 记录重建正式事件。

`analysis.limit_event_candidate` 仅限内部调试、治理和质量验证，禁止作为面向最终用户的
正式数据源。

## 6. 状态传播

Stage 20 如保留事件模块占位，必须读取 Stage 19 正式发布状态。当前必须输出：

```text
formal_event_release = BLOCKED
availability_status = BLOCKED 或 UNAVAILABLE
value = NULL
```

同时显示明确的中文 blocker 原因。禁止以 0、candidate、推断值、简单 `pct_change` 重算
或静默隐藏替代不可用状态。

## 7. 完全解除条件

Stage 19 只有按以下顺序取得真实证据后才能正式 `PASS`：

```text
权威 security_status_history
→ 证券状态来源审计
→ 消除 gap / UNKNOWN
→ 完成规定人工复核
→ Stage 8 正式重建
→ S15-14 当前补验
→ Stage 19 真实数据重跑
→ G1–G9 全部 PASS
→ 正式事件发布
→ Stage 19 正式 PASS
```

Stage 20 受限开发不得修改 blocker、自动宣告 remediation 完成、自动生成正式事件或覆盖
Stage 19 的 `BLOCKED` 状态。

## 8. 证据与优先级

- `docs/stage_transition_rules.md`
- `docs/stage19_acceptance.md`
- `reports/stage19/8d1e4e7b-4a97-4c2e-9e9e-stage19blocked/stage19_manifest.json`
- `reports/stage19/8d1e4e7b-4a97-4c2e-9e9e-stage19blocked/stage19_gate.json`
- `reports/stage19/8d1e4e7b-4a97-4c2e-9e9e-stage19blocked/formal_release_hardening.json`

后续解释优先级为：新的真实补验结果 → 本条件封板决策 → Stage 19 最新验收与机器证据 →
更早历史记录。本项目仅用于研究与数据工程验证，不构成投资建议。
