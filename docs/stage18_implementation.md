# Stage 18 基本面数据建设实施记录

## 实施链路

Stage 18 按独立子阶段完成接口能力审计、正式 Raw、Clean 标准化、DuckDB 入库、PIT Feature 和最终出口冻结：

| 子阶段 | 正式 run | 状态 |
|---|---|---|
| Stage 18.1 接口能力审计 | `4915ea1b-2e00-4a34-a743-d35dfcb66fe2` | PASS |
| Stage 18.2 正式 Raw 采集 | `df86486a-9a54-4920-a4db-2553f907af92` | PASS |
| Stage 18.3 Clean 与时间治理 | `66bebf1c-8b64-42a6-a970-1dbf1ecb395f` | PASS |
| Stage 18.4 DuckDB 入库 | `b2d7bf6c-b7c7-4760-b16d-33640111cb11` | PASS |
| Stage 18.5 PIT Feature | `1bc599a7-17eb-4cc8-a543-8c0baaa7c3b8` | PASS |
| Stage 18.6 最终验收 | `9779de8b-6504-4efc-a473-bf07537a7a8d` | PASS |

全流程以 `2026-07-27` 为分析基准日。Raw、Clean、数据库和 Feature 均采用唯一 run lineage 与 append-only 资产；实时估值只保留观测时间，不回填为历史估值。

## 正式出口

Stage 18 对下游只冻结两个正式输入：

1. DuckDB：`database/stage18/run_id=b2d7bf6c-b7c7-4760-b16d-33640111cb11/fundamentals.duckdb`
2. PIT Feature：`data/features/stage18/run_id=1bc599a7-17eb-4cc8-a543-8c0baaa7c3b8/fundamental_features.parquet`

Stage 19 不得回读 Stage 18.1 审计样本或 Stage 18.2 Raw 重新解释基本面。Feature 的 `PASS` 可用；`UNAVAILABLE` 必须保持 NULL/不可用；`FAIL` 和 `BLOCKED` 不允许进入正式出口。

## 时间治理

Feature 只使用 `PIT_ELIGIBLE` 且公告日、更新时间不晚于基准日的输入。同比匹配相同 `fiscal_period` 的上一财年；ROA/ROE 只在年度利润和可比平均资产或权益完整时计算。公告日不推断、币种不混合、分母为零不填值、当前估值不进入历史分析。

Stage 18.6 只做综合验收、出口冻结和下游合同，不重新采集、清洗、入库或补算 Feature，也不启动 Stage 19。
