# Stage 17.6.5：09669.HK人工/外部数据验证

验证批次：`86302abd-834e-4b72-9424-b8e9ff9e7b71`
业务基准日：`2026-08-24`
Provider：`manual_external`

## 结论

- 专项验证状态：`BLOCKED`（0/3 PASS）。
- Stage 17正式状态仍为：`BLOCKED`。
- Stage 18授权：`false`。
- 本批未建设Provider Registry，未重跑完整Stage 17，未创建Stage 18或Stage 19产物。

| adjust | status | rows | first_date | last_date | coverage | source | issue |
| --- | --- | ---: | --- | --- | --- | --- | --- |
| raw | FAIL | 0 | - | - | history_unavailable | - | source_file_missing |
| qfq | FAIL | 0 | - | - | history_unavailable | - | source_file_missing |
| hfq | FAIL | 0 | - | - | history_unavailable | - | source_file_missing |

## 数据来源与语义门禁

输入目录：`data/manual/stage17/hk`

每个口径必须同时提供CSV/Parquet和独立metadata。metadata必须记录来源、获取时间、源文件
SHA-256、字段定义、Provider复权定义及调整依据。`raw`不得冒充`qfq/hfq`，Yahoo
`Adj Close`不得冒充完整复权OHLC；计算型复权必须引用Raw、公司行动和因子三类哈希证据。

## 质量规则

质量检查直接复用Stage 17现有逻辑：非空、日期递增且唯一、无未来日期、OHLC包络、
成交量非负以及`complete_to_verified_listing_date`。本任务没有修改或放宽规则。

## 阶段边界

即使本专项3/3通过，也只代表具备进入后续独立Provider Registry任务的候选条件。本批不是
69项A/H日线与6项ETH的完整正式重跑，不能直接把Stage 17改为PASS或授权Stage 18。
