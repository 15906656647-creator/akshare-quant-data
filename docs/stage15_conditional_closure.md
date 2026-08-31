# Stage 15 条件封板决策

> 决策日期：2026-08-24
> 业务基准日：2026-07-27
> 管理状态：`CONDITIONALLY_CLOSED`
> 运行状态：`PASS_WITH_UNAVAILABLE_ITEMS`

## 1. 决策

Stage 15 的每日质量检查、风险记录机制和不可用项降级机制已经完成，可以在治理层
条件封板，并授权项目进入 Stage 17。条件封板不是完全验收通过，不改变程序、数据库
或历史运行报告中的真实状态。

以下状态同时成立：

- Stage 15 管理状态为 `CONDITIONALLY_CLOSED`；
- `quality-control` 运行状态保持 `PASS_WITH_UNAVAILABLE_ITEMS`；
- S15-14“最近涨停日及次日开盘价”保持 `BLOCKED/UNAVAILABLE`；
- 正式涨停、跌停、连板和事件后收益保持不可发布；
- Stage 17 可以开始，Stage 19 的正式事件发布仍受硬门禁约束。

## 2. 条件封板依据

Stage 15 每日质量检查已经通过，但仓库当前没有可审计、完整覆盖分析窗口的权威
`security_status_history`。在不能确认历史交易日的 ST、*ST、上市、停牌等状态时，
无法为每个交易日唯一选择适用的涨跌幅规则。

涨跌停规则的官方来源链已经建立，但人工复核和正式发布状态也不得描述为完全关闭。
运行结果可能同时报告 `no_authoritative_limit_rules` 与
`no_authoritative_security_status_history`；其中历史证券状态缺失是 S15-14 的主要
实质阻塞。

2026-08-05 的旧 S15-14 修复报告曾基于后来失效的 A 级来源判定宣告完全通过。该结论
不再有效；当前状态以最新根因分析、本决策和后续真实补验结果为准。旧报告正文仅作为
历史审计记录保留。

## 3. 数据与发布约束

- 禁止使用当前证券名称或当前 ST 快照回填历史状态。
- 禁止从价格变化反推当日证券状态或把未知状态当作非 ST。
- 禁止把 `UNAVAILABLE`、`BLOCKED`、缺失或未解决记录填成 0。
- 候选或推断事件只能标记为 `INFERRED/UNVERIFIED`，不得进入正式事件视图和汇总。
- Stage 20/21 如引用涨跌停数据，必须展示或传播 `UNAVAILABLE/BLOCKED`，不得用推断值
  冒充正式结果。
- Raw 追加、唯一 `run_id`、数据库幂等、显式业务日期等既有约束继续有效。

## 4. 后续阶段授权与门禁

所有转换服从 [stage_transition_rules.md](stage_transition_rules.md)。本条件封板只直接授权
Stage 17入口，不具备跨阶段传递效力。

| 阶段 | 本决策是否直接授权 | 实际入口条件 |
| --- | --- | --- |
| Stage 17 | 是 | 读取本决策、Stage 16基线和统一衔接规则 |
| Stage 18 | 否 | Stage 17正式PASS，或另有Stage 17条件封板 |
| Stage 19 | 否 | Stage 18正式PASS，或另有Stage 18条件封板 |
| Stage 20 | 否 | Stage 19正式PASS；若只进入非事件功能，必须另建Stage 19条件封板 |
| Stage 21 | 否 | Stage 20获准范围完成并通过验收 |

Stage 16是原任务已经完成的离线覆盖基线，不要求因本决策重跑，也不构成Stage 17之前的
新执行阶段。本决策和衔接规则的建立不代表Stage 17已经开始。

Stage 20/21如将来获准实施并引用事件数据，仍必须传播 `UNAVAILABLE/BLOCKED`，不得
用推断值或0冒充正式结果。

## 5. 解除条件封板

只有以下条件全部满足，Stage 15 才能由条件封板转为完全通过：

1. 获得可审计的权威历史证券状态数据；
2. 覆盖冻结样本和完整分析区间，无未解释缺口或冲突区间；
3. 保存来源、抓取时间、原始证据和 SHA-256；
4. 涨跌停规则与证券状态完成规定的人工复核和正式批准；
5. Stage 8 使用正式输入重建并通过质量门禁；
6. 重跑 Stage 15，`unavailable_items=0` 且 `blocked_risk_count=0`；
7. S15-14 使用至少两个有效样本完成真实交叉验证。

在上述条件满足前，管理层可以继续非事件阶段工作，但不得将 Stage 15 或正式涨跌停
事件描述为完全通过。

## 6. 依据与优先级

- 最新根因依据：`reports/stage15_stage8_security_status_root_cause.md`
- Stage 15 历史验收：`docs/stage15_acceptance.md`
- Stage 8 当前实现边界：`docs/stage8_implementation.md`
- 旧修复历史记录：`docs/stage15_s14_fix_report.md`

发生结论冲突时，按“后续真实补验结果 → 本决策 → 最新根因分析 → 历史报告”的顺序
解释当前治理状态。项目仅用于研究与数据工程验证，不构成投资建议。
