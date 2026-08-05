# 阶段 14 验收记录

验收日期：2026-08-04。全部命令从项目根目录、已激活 `.venv` 的解释器执行。

## 自动化测试

单次完整命令在 5 分钟工具时限内运行到 88% 后被外部终止，未将超时记作通过。
随后按测试域拆分执行，结果为：

```text
非 Stage 13：749 passed in 218.47s
Stage 13：68 passed in 100.47s
合计：817 passed, 0 failed
```

Stage 14 定向测试覆盖 CLI 解析、日期验证、顺序、失败停止、原始非零退出码、共享
`run_id`、dry-run 无写入、状态原子写入、异常 traceback、失败 CSV、独立组合步骤
执行和配置顺序。
既有测试继续覆盖 Raw 空表保护、临时文件失败保护、DuckDB upsert、重复运行和
部分失败状态。

## CLI 与 Dry Run

以下命令退出码均为 0：

```text
python run_pipeline.py --help
python run_pipeline.py smoke-test --help
python run_pipeline.py fetch-market --help
python run_pipeline.py run-all --help
python run_pipeline.py run-all --start 20250101 --end 20250131 --dry-run
```

Dry Run 输出了冻结的 11 步顺序，从 `smoke-test` 到 `build-report`，未启动子任务，
也未创建数据、数据库或运行日志。

## 小范围真实网络抓取

为避免覆盖仓库既有 Stage 3 报告，使用系统临时目录作为隔离项目根目录，调用既有
`run_market_fetch`（网络仍只发生在 adapter/collector）：

```text
symbol: 002067
range: 2026-07-20 .. 2026-07-27
spot: skipped
run_id: 1b6a89b6-2491-44df-864e-f551c5a62ab0
status: PASS
daily_success_count: 2/2 (qfq + raw)
raw_file_count: 2
```

相同参数使用新 `run_id=10564cea-fcc3-4251-aa2e-8cff985cad00` 重复执行时，外部
数据源在 qfq 请求中连续 3 次断开连接，任务正确返回非零退出码；raw 请求成功并
只发布 1 个完整文件。结构化记录为：

```text
status_counts: failed=1, success=1
error_type: connection_error
attempt_count: 3
raw_path for failed item: empty
```

第二批成功文件与首批对应文件 SHA-256 相同，但位于不同 `run_id` 分区；首批两个
有效 Raw 文件没有被失败或空结果覆盖。这同时提供了真实故障模拟证据。由于第二次
外部请求部分失败，没有伪造“两次都成功”的结论。

本次最终验收又在系统临时目录隔离执行了一次相同股票和日期范围的请求，`qfq` 与
不复权接口均在 3 次尝试后被远端断开连接，运行据实返回 `PARTIAL`/业务退出码 1，
`run_id=95dd7953-b601-46db-a0d8-cdedfd3eb6cc`。两项记录均为
`error_type=connection_error`、`raw_path` 为空，没有发布损坏或空 Raw 文件。该结果
验证了当前网络故障下的重试、非零状态和 Raw 保护，但不构成成功抓取证据。

## 数据库幂等验证

```text
python run_pipeline.py validate-stage5 \
  --as-of-date 2026-07-27 \
  --database-path database/akshare_data_test_stage5_repaired.duckdb
```

结果为 PASS：16 股的 qfq/raw、实时快照、财务和资金流覆盖均为 16；
`fact_stock_daily`、`fact_stock_spot`、三类财务事实及 `fact_stock_fund_flow` 的
重复主键数全部为 0，空主键数也全部为 0。

## 冻结范围与限制

Stage 0 三个冻结文件未修改。未执行3年全量网络 `run-all`；最终验收执行了阶段0
最低1自然年隔离范围，并真实运行到 Stage 8。Stage 8 已知会因缺少权威历史规则/
状态数据 fail-closed，因此 `run-all` 以真实非零退出码停止。小范围正式 Stage 5
不能接受单股 manifest 冒充完整 16 股输入。以上均作为真实限制保留，不构成投资
建议。

## 2026-08-05 独立复验与修复

作为独立验收再次执行时，发现并修复了两个问题：

1. 阶段14包裹既有 CLI 命令后，完整测试套件通过子进程调用这些命令会在项目
   `logs/` 与 `reports/run_status/` 留下故障注入状态。修复方式：测试会话默认
   设置 `AKSHARE_STAGE14_CHILD=1` 避免嵌套记录，仅两个专门验证状态日志的
   阶段14测试清除该环境变量。
2. `fetch-market` 只传 `--start` 或 `--end` 其中一个时会被静默忽略；现已要求
   两个紧凑日期参数必须成对提供，并新增 CLI 回归测试。

复验结果：

- 全量测试：`820 passed in 366.50s (0:06:06)`，覆盖子进程日志隔离、日期成对
  校验和非交易日起始边界回归测试。
- 阶段14别名 `fetch-financial`、`fetch-event-and-fund-flow`、`clean`、
  `load-database`、`quality-check`、`build-report` 的 dry-run 均退出 0 且不写
  日志。
- `validate-stage5`：PASS，16 股覆盖，重复主键与空主键均为 0。
- Stage 13 离线 dry-run：READY，`inventory_blocked_count=0`。
- Stage 9 输入验证：READY。Stage 8 输入验证：BLOCKED（既有
  `no_authoritative_limit_rules` 与 `no_authoritative_security_status_history`
  阻塞）。
- 临时目录真实 AKShare 抓取 `002067`、`2026-07-24..2026-07-27`：PASS，
  `run_id=e1c1b3f3-e1e6-4ab4-9475-8b3563d25c6d`，qfq/raw 各发布 1 个
  Parquet 文件，均成功；后续同参数抓取出现远端断连时按 `PARTIAL/exit 1`
  据实返回，且不发布空 Raw 文件。

## 2026-08-05 最终真实 run-all 闭环

最终验收在隔离项目副本中执行，不修改主项目数据、日志或报告。副本路径：
`C:\Users\赵\.codex\visualizations\2026\08\05\019fcfaa-a87e-75f1-a4b5-0eab956c7031\stage14_final_acceptance_20260805_110202`

### 8个用户命令验收矩阵

| 用户命令 | --help | 最小合法 dry-run | 是否产生不应有写入 | 底层任务 | 可单独重跑 |
| --- | --- | --- | --- | --- | --- |
| `smoke-test` | 0 | 不支持 dry-run，按 `--help` 验收 | 否 | Stage2冒烟 | 是 |
| `fetch-market` | 0 | 0 | 否 | Stage3行情 | 是 |
| `fetch-financial` | 0 | 0 | 否 | Stage4财务+资金流 | 是 |
| `clean` | 0 | 0 | 否 | Stage5 Clean+DuckDB | 是 |
| `build-features` | 0 | 不支持 dry-run，按 `--help` 验收 | 否 | Stage7特征 | 是 |
| `analyze-limit-events` | 0 | 2（预期BLOCKED） | 否 | Stage8事件 | 是 |
| `analyze-style` | 0 | 0 | 否 | Stage9风格 | 是 |
| `build-report` | 0 | 0 | 否 | Stage13报告 | 是 |

### 11步真实状态

| 步骤 | 状态 | 说明 |
| --- | --- | --- |
| smoke-test | success | 12/12 probes success |
| fetch-market | success | 34/34 Raw，16股 |
| fetch-financial | success | 96/96 Raw，16股 |
| fetch-event-and-fund-flow | skipped | 设计性跳过：Stage4组合入口已发布资金流 |
| clean | success | Clean + DuckDB 原子发布 |
| load-database | skipped | 设计性跳过：Stage5 clean 已原子加载数据库 |
| build-features | success | 16/16，29/29质量检查 |
| analyze-limit-events | failed | Stage8 BLOCKED，退出码2 |
| analyze-style | skipped | 上游失败后未执行 |
| quality-check | skipped | 上游失败后未执行 |
| build-report | skipped | 上游失败后未执行 |

真实运行信息：

- 日期范围：`2025-07-27..2026-07-27`（阶段0最低1自然年；起始日为周日，首条交易日落在10日容差内）。
- `run_id`：`85911fcd-dd80-4d94-bba4-7c091ff3782c`
- 退出码：`2`
- 状态JSON：`reports/stage14_final_acceptance/85911fcd-dd80-4d94-bba4-7c091ff3782c/task_status.json`
- pipeline日志：`reports/stage14_final_acceptance/85911fcd-dd80-4d94-bba4-7c091ff3782c/pipeline.log`
- 失败明细：`reports/stage14_final_acceptance/85911fcd-dd80-4d94-bba4-7c091ff3782c/failed_items.csv`
- Raw安全：零字节文件0；Stage3 34个、Stage4 96个 Raw 文件均成功且写入新 run 分区。
- `validate-stage5`：PASS；重复主键与空主键均为0。

### skipped步骤合规依据

原始文档第14.1节只把8个命令列为用户命令，第14.2节展示11步编排顺序；文档没有要求每个编排步骤都必须启动独立子进程。既有 `financial_fetch.py` 的
`individual_fund_flow` 已包含在 Stage4 组合接口中，既有 `stage5_build.py`
把 Clean 与 DuckDB 事务发布视为一个原子步骤。因此这两个步骤在 `run-all`
中记录为 `skipped` 并写入原因，属于设计性跳过，不是未完成。

### Stage8 BLOCKED 与阶段14验收

`analyze-limit-events` 返回非零退出码2，原因仍为
`no_authoritative_limit_rules` 和 `no_authoritative_security_status_history`。
编排随后未执行 `analyze-style`、`quality-check`、`build-report`，状态JSON、pipeline日志和失败CSV均真实记录。该结果验证了阶段14的失败真实停止和状态可追溯，Stage8业务输入不足不属于阶段14编排失败。

### 本次代码修复

1. `git rev-parse` 子进程在 Windows 中文路径/非 ASCII 输出下可能触发解码异常；阶段14及 run-all 依赖的 Stage5/6/8/9 模块已统一使用 UTF-8 和 `errors="replace"`。
2. `fetch-market` 对非交易日起始日期过于严格，原始命令示例 `20230101` 会因首条交易日晚于起始日而误报 `historical_window_not_covered`；现允许起始日后10个自然日内的首个交易日，并新增回归测试。
