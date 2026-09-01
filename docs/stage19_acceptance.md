# Stage 19 A股涨跌停事件系统验收记录

## 1. Stage 18 entry status

`PASS`。Stage 18 正式 run `9779de8b-6504-4efc-a473-bf07537a7a8d` 明确授权 Stage 19
入口，且没有解除 Stage 19 自身发布门禁。

## 2. Implemented scope

已完成 schema、Stage 8 数据集复用导入、候选事件计算、状态/规则质量校验、交易日序列
连板与事件后表现字段、正式 release gate、NULL/BLOCKED 统计传播、数据库事务写入、
PASS 时正式发布与真实统计、机器报告和自动测试。未实施 Stage 20。

## 3. Target symbols

Stage 0 冻结的 16 只 A 股：002067、002600、002230、600763、603259、603799、601012、
600438、002361、601500、600231、300274、601636、002129、000100、300433。

## 4. Analysis range

`2025-07-27` 至 `2026-07-27`，分析基准日 `2026-07-27`。价格路由为 Stage 17 正式
PASS 批次的 16/16 不复权 A 股日线，逐文件 SHA-256 一致。

## 5. security_status_history coverage

0 条权威记录。32 个覆盖单元（16 symbol × ST/LISTING）均无完整区间覆盖；覆盖矩阵见
正式 run 的 `security_status_coverage.csv`。

## 6. Unresolved UNKNOWN periods

完整分析区间无法证明历史 ST/*ST 与 LISTING 状态。UNKNOWN 没有被解释为 NON_ST；
3,862 条逐日候选观察均保持不可正式发布。

## 7. Rule-history coverage

12 条规则记录通过格式、来源、哈希、区间和覆盖校验；12/12 为 verified 计算输入，
并已写入 `reference.limit_rule_history`；但人工复核状态为
`approved_with_waiver`，不满足正式发布 G4。

## 8. Source audit status

规则来源审计通过（G3 PASS）；证券状态数据集缺少
`security_status_history.csv`，状态来源审计未完成（G2 BLOCKED）。近期涨跌停池未用于
历史回填或正式事件。

## 9. Manual review status

规则双人正式复核 0/12；状态记录 0 条。G4 BLOCKED。

## 10. Stage 8 rebuild status

`BLOCKED`。没有当前正式 Stage 8 `PASS + formal publication` 证据，G8 BLOCKED。

## 11. S15-14 status

`BLOCKED/UNAVAILABLE`。旧 `s14_verification.json` 的 PASS 依赖已失效的 Stage 8/状态
证据，按后续治理优先级不得使用，G9 BLOCKED。

## 12. Release gate status

| Gate | 状态 | 结论 |
| --- | --- | --- |
| G1 | BLOCKED | 权威状态未覆盖全部目标与区间 |
| G2 | BLOCKED | 状态来源审计未完成 |
| G3 | PASS | 规则来源审计完成 |
| G4 | BLOCKED | 双人正式复核未完成 |
| G5 | BLOCKED | 状态覆盖 gap 未消除 |
| G6 | PASS | 当前无输入记录，因此未发现 overlap；不解除 G1/G5 |
| G7 | PASS | 当前未发现独立 conflict；缺失/UNKNOWN 由 G1/G5 阻塞 |
| G8 | BLOCKED | Stage 8 正式重建未通过 |
| G9 | BLOCKED | S15-14 当前补验未通过 |

正式事件 release gate：`BLOCKED`。

## 13. Test results

- Stage 19 + Stage 8 定向测试：93 passed。
- 正式离线 run：16/16 Raw 哈希一致，3,862 条候选观察写入。
- 边界修正后定向回归：51 passed。
- 最终全仓测试：1,062 passed，0 failed，用时 372.64 秒。
- 同一 `run_id` 幂等重跑后：候选 3,862、正式事件 0、正式统计 160、门禁 9，
  行数均未增长；160 个统计值仍全部 NULL。
- Formal-release hardening synthetic tests：15 passed；覆盖 PASS Gate、涨停、跌停、
  unresolved 排除、正式统计、合法 0、不可用 NULL、同 run 幂等和
  PASS→BLOCKED→PASS 清理。
- Hardening 后最终全仓测试：1,067 passed，0 failed，用时 300.03 秒。

## 14. Official event publication status

`BLOCKED`。`analysis.limit_event` 无正式发布记录；160 个正式统计单元
（16 symbol × 10 metrics）全部 `value=NULL, availability_status=BLOCKED`，没有用 0
表示不可用。

## 15. Blockers

权威历史证券状态数据缺失、状态来源审计缺失、规则与状态规定人工复核未完成、Stage 8
正式重建未通过、S15-14 当前补验未通过。

## 16. Final Stage 19 management/runtime status

Stage 19 framework implementation：完成。Stage 19 formal event release：`BLOCKED`。
BLOCKED 分支和 synthetic PASS 分支均已技术闭环；synthetic PASS 不改变真实运行状态。
本工程任务不创建 `CONDITIONALLY_CLOSED` 治理决策，也不把 Stage 19 描述为 PASS。

## 17. Whether Stage 20 is authorized

否。Stage 20 未获授权。若只进入非事件功能，必须另行完成独立的 Stage 19
`CONDITIONALLY_CLOSED` 治理决策；本任务未做该决策。
