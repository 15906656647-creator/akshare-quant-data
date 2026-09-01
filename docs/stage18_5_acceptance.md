# Stage 18.5 正式验收

## 结论

Stage 18.5 formal run `1bc599a7-17eb-4cc8-a543-8c0baaa7c3b8` 为 `PASS`。Stage 18.6 授权为 `true`，但尚未启动。

正式 Feature：

```text
data/features/stage18/run_id=1bc599a7-17eb-4cc8-a543-8c0baaa7c3b8/fundamental_features.parquet
SHA-256: ed3db58277045eca98e9806e324c3a28d7a1a85d773c831a5807dfc16ba3ee64
```

## 覆盖

- 23/23 证券均有覆盖记录；12 个 Feature 共 276 个单元。
- `PASS` 170，`UNAVAILABLE` 106，`FAIL` 0，`BLOCKED` 0。
- 7 只港股的 84 个单元因没有 PIT 合格公告证据全部保持 `UNAVAILABLE`。
- A 股除 ROA/ROE 外的 10 个 Feature 均为 16/16 `PASS`。
- ROA 和 ROE 各为 5 个 `PASS`、11 个 `UNAVAILABLE`；不可用原因是年度利润与可比年度平均资产/权益输入不足，未使用较弱口径补齐。

## 时间与治理门禁

- future-data usage：0。
- announcement-date inference：0。
- valuation leakage：0；23 条当前估值快照未参与计算。
- period mismatch：0；同比只比较相同 `fiscal_period` 的相邻财年。
- Feature 定义与逐行 lineage 完整；分母为零和币种不一致均按 `UNAVAILABLE` 治理。
- Stage 18.4 数据库 SHA-256 在运行前后保持 `ef095fbee26da64da43e19ea7da45f4d8924c9f3977f3c735f29926d70e0812b`。
- Stage 0、Stage 17、Stage 18.1–18.4 正式资产不变；Stage 19 资产为 0；临时文件残留为 0。

正式证据位于 `reports/stage18/1bc599a7-17eb-4cc8-a543-8c0baaa7c3b8/`。
