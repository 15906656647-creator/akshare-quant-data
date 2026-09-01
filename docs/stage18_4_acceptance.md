# Stage 18.4 正式验收

## 结论

Stage 18.4 正式 run `b2d7bf6c-b7c7-4760-b16d-33640111cb11` 验收为 `PASS`。Stage 18.5 规划授权为 `true`，但 Stage 18.5 尚未启动。

唯一上游为 Stage 18.3 formal run `66bebf1c-8b64-42a6-a970-1dbf1ecb395f`，其 Stage 18.2 lineage 为 `df86486a-9a54-4920-a4db-2553f907af92`。上游 manifest、metadata 和 SHA-256 在入库前后保持一致。

## 正式数据库

```text
database/stage18/run_id=b2d7bf6c-b7c7-4760-b16d-33640111cb11/fundamentals.duckdb
SHA-256: ef095fbee26da64da43e19ea7da45f4d8924c9f3977f3c735f29926d70e0812b
```

正式行数：

| 表 | 行数 |
|---|---:|
| fact_financial_abstract | 79,917 |
| fact_financial_indicator | 78,482 |
| fact_balance_sheet | 124,211 |
| fact_income_statement | 76,720 |
| fact_cash_flow_statement | 109,656 |
| fact_valuation_snapshot | 23 |
| 历史合计 | 468,986 |
| 总计 | 469,009 |

## 门禁结果

- 6/6 表创建并可 read-only 复开查询。
- schema validation、lineage validation、PIT validation 的失败数均为 0。
- canonical key / valuation symbol 重复数为 0。
- 23/23 证券存在，市场身份为 16A/7HK。
- valuation 23/23 的 `eligible_for_as_of_date_analysis=false`。
- 数据库关闭后 SHA-256 可复算，`.tmp`/`.wal` 残留为 0。
- Stage 0、Stage 17 Raw、Stage 18.1 audit Raw、Stage 18.2 Raw、Stage 18.3 Clean 均未改变。
- Stage 18 Feature 文件为 0，Stage 19 资产为 0。

正式证据位于 `reports/stage18/b2d7bf6c-b7c7-4760-b16d-33640111cb11/`。完整测试只允许已登记的 Stage 8 测试债务，不允许任何新增失败。
