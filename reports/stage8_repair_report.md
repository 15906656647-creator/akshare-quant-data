# AKShare 阶段 8 修复报告

## 1. 修复结论

- 阶段 8 工程修复自测：**PASS**
- 正式全年统计发布：**BLOCKED**
- 建议：重新执行独立验收
- 阶段 9：在新的独立验收给出 PASS 或 CONDITIONAL PASS 前不得进入

本轮仅修复现有阶段 8 工作区，不运行正式全年分析，不访问网络，不重新运行
阶段 7，不创建正式阶段 8 数据库。开发者自测 PASS 不替代独立验收。

## 2. 问题关闭矩阵

| 问题 | 状态 | 关键修复 | 主要测试 |
|---|---|---|---|
| S8-AUD-001 | FIXED | `decide_publication` 集中检查事件、证据、质量、原因和 ERROR FAIL | `test_error_quality_failure_blocks_publication`、`test_zero_formal_events_with_unresolved_is_not_formal_zero` |
| S8-AUD-002 | FIXED | 每只证券稳定排序后，仅用有效交易行计算 next/forward/连板 | `test_zero_volume_rows_are_skipped_for_next_and_continued_limit`、`test_forward_windows_count_only_valid_trading_rows` |
| S8-AUD-003 | FIXED | 事件/汇总主键加入 `run_id`，增加 latest view，事务失败回滚 | `test_different_runs_preserve_history_and_latest_view`、`test_transaction_failure_rolls_back_event_rows` |
| S8-AUD-004 | FIXED | 所有质量项由 DataFrame 或数据库回读实际计算 | `test_each_prewrite_quality_check_has_data_driven_opposite_scenario`、`test_post_write_database_mismatch_is_detected` |
| S8-AUD-005 | FIXED | 官方限价需完整来源、版本、状态、时间、证券、日期及 tick 证据 | `test_official_verified_prices_take_priority`、`test_incomplete_or_mismatched_official_evidence_is_rejected` |
| S8-AUD-006 | FIXED | 严格布尔、比例、日期、tick/精度、舍入、来源、枚举、未知字段和区间校验 | `test_invalid_limit_ratios_are_rejected`、`test_rule_interval_overlap_is_rejected` |
| S8-AUD-007 | FIXED | DuckDB 只读打开并检查文件、表、字段、口径、类型、区间、重复键及输出保护 | `test_stage8_validate_only.py` 7 项 |
| S8-AUD-008 | FIXED | JSON/Markdown/CSV/审计表共享 run manifest；样本 CSV 使用 `EVENT_COLUMNS` | `test_full_stage8_pipeline_is_offline_idempotent_and_report_consistent` |
| S8-AUD-009 | FIXED | 365 日读取冻结 metric 配置；stage8 策略字段均在加载时验证并进入 manifest | 同上及完整套件 |
| S8-AUD-010 | FIXED | 补齐 hfq、停牌、回滚、损坏库、traceback、异常收益、门禁等失败路径 | 阶段 8 共 134 passed |

当前限制均为正式数据缺口，不是通过默认值绕过的工程缺口。

## 3. 文件变更

- 配置/文档：`config/stage8.yml`、`docs/stage8_implementation.md`、`README.md`
- CLI/编排：`src/akshare_data_test/cli.py`、`stage8_build.py`
- 规则与检测：`limit_rules.py`、`limit_event_detection.py`
- 汇总与门禁：`stage8_analysis.py`
- 存储与质量：`storage/limit_event_repository.py`、`quality/limit_event_checks.py`
- SQL：`sql/stage8_schema.sql`
- 测试：阶段 8 的 8 个测试文件
- 报告：`reports/stage8_*` 验证、manifest、CSV 和本修复报告

未修改 `config/universe.yml`、`config/metric_definition.yml`、
`docs/stage0_scope.md` 或任何阶段 7 正式数据库/报告。

## 4. 数据库 schema 变更

- 事件事实主键：`(run_id, symbol, trade_date)`；同一 run 每证券每日仅保留一条
  互斥识别结果。
- 年度汇总主键：`(run_id, symbol, period_start, period_end)`。
- 质量主键：`(run_id, check_name)`。
- 新增 `v_latest_limit_event` 和 `v_latest_formal_limit_event`，只选择最新 PASS run。
- 审计表增加时间、输入表/口径、窗口、发布状态、输出类型、质量计数、代码版本、
  配置哈希及完整 `manifest_json`。
- 同 run 重写幂等，不同 run 不覆盖；初始写入和最终质量回写均使用事务，异常完整回滚。
- 阶段 8 尚无正式数据库，因此没有对正式文件执行迁移；SQL/Python 映射只在临时
  DuckDB 验证。

## 5. 发布门禁

集中函数：`src/akshare_data_test/stage8_analysis.py::decide_publication`。

阻断条件包括：

- unresolved/candidate/proxy/gap_proxy；
- unresolved/provisional/unverified 证据；
- 涨跌停事件不是 verified/pass；
- mutual conflict、缺规则、缺状态、缺前收盘、无效交易行、计算错误等未决原因；
- 任意 `severity=ERROR AND status=FAIL` 的质量项；
- 预检、汇总、覆盖和数据库写后回读产生的基础 blocker。

阻断结果固定为 `run_status=BLOCKED`、`publication_status=blocked`、
`exit_code=2`；内部/用户输入错误为退出码 1。WARNING FAIL 会进入报告但不会
被错误提升为 ERROR。

## 6. 有效交易序列

有效行要求日期可解析、OHLC 为有限正数、成交量大于 0，且无 suspended/
non-trading 标记。全量输入行仍写入观察事实用于审计；next、3/5/10 日 forward
和连板只在每只证券自己的有效行序列中计算。输入使用稳定排序，不按自然日偏移，
不跨证券，连续停牌和周末均跳过，尾部不足保持 NULL 并标记样本状态。

## 7. 官方限价证据

官方涨跌停价只有在数值、来源名称、来源引用、来源版本、verified 状态、
verified_at、证券、交易日期、涨价大于跌价及 tick/精度全部通过时优先。
否则记录 `official_limit_unverified` 并降级至经验证的理论 Decimal 路径；
不得仅因价格非空而标记 verified。

## 8. 质量检查

ERROR 检查：

- 实际输入口径为 raw；
- 事件和汇总主键唯一；
- 正式事件互斥；
- unresolved 默认 fail-closed；
- 规则/证券状态实际覆盖率及分子分母；
- 正式证据字段和理论限价字段完整；
- next 日期顺序正确；
- 禁止类型不具备 verified/pass 发布状态；
- 收益为有限合理范围；
- 内存 run_id 一致；
- 写后数据库事件/汇总/正式事件计数与报告一致；
- 数据库业务事实与审计 run_id 一致。

WARNING 检查：

- 3/5/10 日 forward 样本完整率；不完整时 FAIL/WARNING、不得填 0，也不单独
  阻断发布。

每项均保存 run_id、名称、严重度、状态、观测/期望、分子/分母、消息和检查时间。

## 9. 测试结果

| 命令 | 退出码 | 结果 | 耗时 |
|---|---:|---:|---:|
| 阶段 8 全集 | 0 | 134 passed | 22.01s |
| 阶段 7 回归准确集合 | 0 | 22 passed | 2.39s |
| `python -m pytest -q` | 0 | 356 passed | 96.70s |
| 冻结配置 `git diff --exit-code` | 0 | 无差异 | 2.3s |

完整套件：0 failed、0 skipped、0 xfailed；测试数量高于上一轮 320 项。所有 DuckDB
测试文件位于 pytest `tmp_path`，无网络访问。

## 10. P0 临时复现结果

### 场景 A：互斥冲突

- exit_code：2
- run_status：BLOCKED
- publication_status：blocked
- failed_quality：`formal_event_mutual_exclusion`
- event_type：unresolved
- evidence_status：unresolved
- quality_status：failed
- 正式汇总：排除该记录

### 场景 B：数据库/报告不一致

- `database_report_consistent=FAIL`
- 严重度：ERROR
- 发布结果：blocked
- exit_code：2

### 场景 C：跨 run

- run-one/run-two 的 event、summary、quality、audit 均可查询；
- latest view 仅指向 run-two；
- 同 run 重写不增加行数。

### 场景 D：停牌

- 零成交停牌行保留用于审计；
- `next_trade_date` 跳到下一有效交易行；
- forward 窗口按有效交易行计数。

## 11. 剩余正式发布阻断项

- 权威历史涨跌停规则覆盖；
- ST 历史覆盖；
- 板块历史覆盖；
- 上市/退市历史；
- no-limit 历史；
- tick/舍入权威来源；
- 正式 raw 数据覆盖的业务核验；
- 人工样本交叉核对。

默认只读预检实际找到 2025-07-27～2026-07-27 的 raw 行 3,862 条，但权威
规则和证券状态记录均为 0，因此返回 BLOCKED/退出码 2。没有把 fixture 或价格
走势推断用作正式历史。

## 12. 需要用户在 PowerShell 手工执行的操作

无需额外手工操作。所有修复验证均已在临时数据库和测试环境完成。

## 13. Git 状态

- 当前分支：`feature/stage8-limit-events`
- 当前 HEAD：`e11b7dfe80f22257de8b140c7eb3540c7400b9b3`
- 阶段 7 标签目标：`e11b7dfe80f22257de8b140c7eb3540c7400b9b3`
- merge-base：退出码 0
- 暂存区：空
- 未执行 add、commit 或 push
- `git diff --check` 与 `git diff --cached --check`：通过

## 14. 2026-08-01 第二次独立验收跟进修复

- blocked 年度汇总现在将涨停数、跌停数、正式事件数及所有事件后表现统一写为 `NULL` / `not_calculated`；DuckDB、CSV、JSON 与 Markdown 均由同一已门禁汇总生成。
- 官方限价来源名称、引用和版本拒绝 `None`、`NaN`、`pd.NA`、`NaT`、空白及 `nan`、`none`、`null`、`NaT` 等缺失语义字符串。
- YAML 文本字段在任何字符串转换前校验；verified 规则缺失来源时，只读预检直接 `FAILED`，不创建输出库。
- `database_report_consistent` 现在实际读取 DuckDB、JSON、年度 CSV、质量 CSV 和 Markdown；报告侧 formal count、收益、比例、publication、run_id 篡改均导致 ERROR/FAIL。
- 年度汇总补齐次日收盘和未来 3/5/10 日平均收益，blocked 时全部为 NULL；正式零事件仍表达为 0。
- 新增纯互斥冲突、混合 blocked、正式零事件、真实 CLI 和跨产物篡改的生产入口回归。
- 同 run 重试在事务内替换该 run 的完整快照，避免残留旧 post-write 质量行；不同 run 历史不受影响。
- 全量离线套件结果：`356 passed in 96.70s`。
- 未运行正式全年分析，未访问网络，未改写阶段 7 数据库或报告。

工作区仅保留预期阶段 8 修复及 README/CLI 接入；没有数据库、Parquet、日志、
缓存、数据文件或秘密进入 Git。

## 15. 下一步建议

重新进行独立验收。若独立验收仍发现工程缺陷，则继续修复；在其给出 PASS 或
CONDITIONAL PASS 前，不建议提交阶段 8，也不得进入阶段 9。
