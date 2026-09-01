# Stage 18 最终验收与出口冻结

## 最终结论

Stage 18 正式状态为 `PASS`。最终验收 run 为 `9779de8b-6504-4efc-a473-bf07537a7a8d`，36 项最终质量检查全部通过，blocker 为 0。

Stage 19 已获入口授权：`stage19_authorized=true`；Stage 19 尚未启动：`stage19_started=false`。该授权不解除 Stage 19 自身的历史证券状态、涨跌停规则和事件发布硬门禁。

## Feature 覆盖

- 23 只证券、12 个 Feature，共 276 个单元。
- `PASS` 170、`UNAVAILABLE` 106、`FAIL` 0、`BLOCKED` 0。
- 未知原因 `UNAVAILABLE` 为 0。
- 7 只港股共 84 项全部为可解释 `UNAVAILABLE`，未弱化 PIT 规则。
- A 股除 ROA/ROE 外的 10 个 Feature 均为 16/16 PASS。
- A 股 ROA、ROE 各为 5 PASS / 11 UNAVAILABLE。

106 项不可用原因冻结为：

| 原因 | 数量 |
|---|---:|
| `NO_PIT_ELIGIBLE_INPUT` | 49 |
| `NO_COMMON_PIT_REPORT_PERIOD` | 21 |
| `ANNUAL_OR_PRIOR_BALANCE_UNAVAILABLE` | 36 |

## 正式出口哈希

```text
fundamentals.duckdb
ef095fbee26da64da43e19ea7da45f4d8924c9f3977f3c735f29926d70e0812b

fundamental_features.parquet
ed3db58277045eca98e9806e324c3a28d7a1a85d773c831a5807dfc16ba3ee64
```

## 最终门禁

- Stage 18.1–18.5：全部 PASS，manifest 文件逐项复算一致。
- future-data usage、公告日推断、估值泄漏、期间错配：全部为 0。
- 当前 23 条估值记录全部不可用于 `2026-07-27` 历史分析。
- Stage 0、Stage 17、Stage 18.1–18.5 正式资产前后不变。
- `.tmp/.wal` 残留为 0，Stage 19 资产为 0。
- 最终 downstream contract 位于 `reports/stage18/9779de8b-6504-4efc-a473-bf07537a7a8d/downstream_contract.json`。
