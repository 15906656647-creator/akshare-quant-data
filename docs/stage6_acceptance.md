# 阶段6独立最终验收报告

## 1. 阶段6验收结论

- 阶段6状态：**FAIL**
- 是否允许进入阶段7：**否**
- `feature_run_id`：`48af48ca-2707-4c53-ad51-745a17b6295d`
- `transform_run_id`：`31635b34-d1ee-46d4-9c0f-32ae3f30d567`
- 阶段5源数据库：`database/akshare_data_test_stage5_repaired.duckdb`
- 阶段6特征数据库：`database/stage6/feature_run_id=48af48ca-2707-4c53-ad51-745a17b6295d/akshare_features.duckdb`

独立验收确认时间安全、公式、Feature 文件、数据库内容、manifest、血缘、输入不可变性和阶段边界均通过。阻断项是完整非空输入的同 run、同路径数据库复跑不幂等；数据库 payload 冲突的原始错误还会被二次回滚错误覆盖。

## 2. 前置门禁

| 项目 | 结果 |
|---|---|
| `pip check` | PASS，退出码 0 |
| `compileall` | PASS，退出码 0 |
| 完整 `pytest` | PASS，186 passed，82.94 秒，退出码 0 |
| `doctor` | PASS，14/14 包、9/9 配置、20/20 文件系统检查 |
| 阶段0哈希 | PASS，3/3 匹配 |
| 阶段5最终复验 | PASS，明确允许使用 repaired 数据库 |
| 阶段5数据库只读验证 | PASS |

阶段5最终复验文件明确指定的入口是 `database/akshare_data_test_stage5_repaired.duckdb`，没有按“最新文件”推断。

## 3. 输入不可变性

| 输入 | 预期数 | 验证数 | 哈希匹配数 | 结果 |
|---|---:|---:|---:|---|
| 阶段3 Raw | 34 | 34 | 34 | PASS |
| 阶段4 Raw | 96 | 96 | 96 | PASS |
| 阶段5 Clean | 10 | 10 | 10 | PASS |
| 阶段5数据库 | 1 | 1 | 1 | PASS |

阶段5数据库验收前后 SHA-256 均为 `ad466df89b30cf305de16fd9184057c4e0779bf9118f98393301857396928026`。正式 Feature、阶段6数据库和既有 manifest 的验收前后哈希也均未变化。

## 4. 时间安全

- `as_of_date`：2026-07-27。
- 历史行情最大日期：2026-07-27；未来行情使用数：0。
- 资金流安全输入最大日期：2026-07-27；2026-07-28 使用数：0。
- 公告日期未知的财务源记录：124,160；实际使用数：0。
- 未来公告实际使用数：0。
- spot 快照时间：2026-07-29 11:35:34.785065+08:00；进入历史 Feature 数：0。
- 静态扫描发现负向 `shift`：0；居中 rolling：0。
- 时间泄漏 ERROR：0。

## 5. Feature定义与覆盖

| Feature组 | 定义数 | 行数 | 股票数 | 最小日期 | 最大日期 | 重复键 | 必需键NULL | 质量 |
|---|---:|---:|---:|---|---|---:|---:|---|
| price_daily | 11 | 11,602 | 16 | 2023-07-27 | 2026-07-27 | 0 | 0 | PASS |
| trend_daily | 8 | 11,602 | 16 | 2023-07-27 | 2026-07-27 | 0 | 0 | PASS |
| activity_daily | 13 | 11,602 | 16 | 2023-07-27 | 2026-07-27 | 0 | 0 | PASS |
| limit_event | 10 | 3,862 | 16 | 2025-07-28 | 2026-07-27 | 0 | 0 | PASS/WARN |
| financial_period | 12 | 2,688 | 16 | 2021-12-31 | 2026-03-31 | 0 | 0 | PASS |
| fund_flow_daily | 2 | 1,904 | 16 | 2026-01-13 | 2026-07-27 | 0 | 0 | PASS |
| style_daily | 36 | 11,602 | 16 | 2023-07-27 | 2026-07-27 | 0 | 0 | PASS |
| current_snapshot | 6 | 16 | 16 | 2026-07-29 | 2026-07-29 | 0 | 0 | PASS |
| suspected_behavior_evidence | 11 | 16 | 16 | 2026-07-27 | 2026-07-27 | 0 | 0 | PASS/WARN |

共登记 109 个 Feature 定义，未发现缺失或未经授权的正式 Feature。各组路径见 `reports/stage6_acceptance_feature_files.csv`。

## 6. 公式复算

| Feature组 | 复算Feature数 | 样本数 | 通过 | 失败 | 最大绝对误差 | 最大相对误差 |
|---|---:|---:|---:|---:|---:|---:|
| price_daily | 5 | 400 | 400 | 0 | 0 | 0 |
| trend_daily | 7 | 560 | 560 | 0 | 0 | 0 |
| activity_daily | 1 | 80 | 80 | 0 | 0 | 0 |
| limit_event | 1 | 80 | 80 | 0 | 0 | 0 |
| fund_flow_daily | 2 | 160 | 160 | 0 | 0 | 0 |
| financial_period | 12 | 931 | 931 | 0 | 0 | 0 |
| style_daily | 7 | 560 | 560 | 0 | 0 | 0 |
| current_snapshot | 4 | 64 | 64 | 0 | 0 | 0 |

合计独立复算 39 个 Feature、2,835 个样本，全部通过。expected 值直接从阶段5安全视图按冻结公式独立计算，没有调用生产 Feature 函数。七个均线 `[3,5,7,10,13,20,21]` 全部通过。

## 7. qfq/raw和单位口径

- 收益、均线、趋势：qfq。
- 涨跌停识别：raw。
- 百分比：小数。
- 金额：人民币元。
- 口径混用：0。
- 其他窗口、阈值和权重均追溯到冻结的 `config/metric_definition.yml`。

## 8. 资金流

- 完整事实表：1,920 行。
- `v_stock_fund_flow_as_of_safe`：1,904 行。
- 未来行：16；阶段6实际使用未来行：0。
- 最大输入日期：2026-07-27。
- 未出现确定性“主力”结论。

## 9. 财务和估值

历史财务使用 `v_financial_point_in_time_safe`。未知公告日期源记录 124,160 行，使用 0 行；未来公告使用 0 行。独立复算覆盖单季度、TTM、同比和比率共 12 个 Feature。缺季度时保留 NULL，没有向未来填充。2026-07-29 的当前估值只存在于独立 snapshot 表。

## 10. 涨跌停和风格特征

涨跌停只使用 raw。因缺少逐证券历史规则，3,862 行全部标为 `uncertain`，`threshold_source=security_rule_history_unavailable`，没有猜测阈值。风格公式来自冻结配置，未生成确定性预测。

## 11. 疑似行为证据

证据字段包括异常成交量、换手变化、资金流持续性、价量背离和涨跌停事件。16 行全部为 `insufficient_evidence=true`、`confidence_level=证据不足`，置信度为空。没有确定性主力意图，也没有投资建议。

## 12. 阶段6数据库

- 路径：`database/stage6/feature_run_id=48af48ca-2707-4c53-ad51-745a17b6295d/akshare_features.duckdb`
- 大小：12,595,200 bytes。
- SHA-256：`f7630f1a103acf7726c51ee396ea359fde731e1ba153b640f5b3ac4f2874cb5e`。
- 可只读打开：是。
- 对象：14 张表、5 个视图；缺失 0。
- 9 张事实 Feature 表重复业务键 0、必需键 NULL 0。
- 元数据表：`feature_run=1`、`feature_definition_registry=109`、`feature_file_manifest=9`、`feature_lineage=9`、`feature_quality_issue=9`。

各表精确行数和内容哈希见 `reports/stage6_acceptance_table_counts.csv`。

## 13. 血缘和manifest

- Feature 文件：9；manifest 登记：9；大小匹配：9；SHA-256 匹配：9。
- Feature 定义：109。
- 血缘记录：9；缺失：0。
- 源数据库哈希、Feature 文件哈希、公式版本和 run_id 均可联结。
- manifest SHA-256：`43ee09f2e3b892801200e06f9e1a2e2c437caf8805ae2e84ef8256f3b089a0fa`。
- 个人绝对路径：0。

## 14. 幂等性和事务

使用临时目录、完整非空的 9 张 Feature 表和 5 张元数据表执行独立复验：

- 第一次持久化：PASS。
- 相同 `feature_run_id`、相同完整 payload、相同数据库路径第二次持久化：**FAIL**。
- 实际错误：`FileExistsError:stage6_database_already_exists_use_a_new_path_or_same_run_id`。
- 失败后全部表行数和内容哈希不变，元数据未翻倍。
- Feature 文件相同 payload 可幂等跳过；9/9 变更 payload 均被拒绝。
- 数据库变更 payload 未留下最终文件或部分表，回滚结果有效。
- 但数据库冲突根因被 `TransactionException: ... cannot rollback - no transaction is active` 覆盖，不满足“明确报错”。
- 正式产物测试前后未修改。

因此 `idempotency_validation=FAIL`、`transaction_validation=FAIL`，阶段6不能 PASS。

## 15. 实际执行命令

| 命令 | 退出码 | 耗时 | 网络 | 修改正式产物 | 结果 |
|---|---:|---:|---|---|---|
| `.venv\Scripts\python.exe -m pip check` | 0 | 约4.2秒 | 否 | 否 | PASS |
| `.venv\Scripts\python.exe -m compileall -q src tests run_pipeline.py` | 0 | 约3.2秒 | 否 | 否 | PASS |
| `.venv\Scripts\python.exe run_pipeline.py show-config --as-of-date 2026-07-27` | 0 | <1秒 | 否 | 否 | PASS |
| `.venv\Scripts\python.exe run_pipeline.py doctor --as-of-date 2026-07-27 --output reports/stage6_acceptance_pre_gate.json` | 0 | 约7.1秒 | 否 | 否 | PASS |
| `.venv\Scripts\python.exe -m pytest` | 0 | 85.2秒墙钟 | 否 | 否 | 186 passed |
| 独立只读输入、Feature、公式、时间、血缘扫描 | 0 | <3分钟 | 否 | 否 | PASS |
| 临时完整输入幂等与冲突复验 | 0（测试程序正常完成） | <1分钟 | 否 | 否 | 验收项 FAIL |
| `run_pipeline.py validate-stage6 ... --validate-only` | 0 | 0.806秒 | 否 | 否 | PASS |
| 首次附带 Feature 目录哈希扫描（目录层级写错） | 1 | 1.9秒 | 否 | 否 | 操作错误，随后按 manifest 实际路径复核 PASS |
| `git diff --check` | 0 | <1秒 | 否 | 否 | PASS，只有 CRLF warning |

未执行正式 `build-stage6`。

## 16. 需要用户在本地PowerShell执行的操作

需要本地PowerShell执行的操作：无。

## 17. 测试结果

- 阶段6现有测试包含于完整测试集；完整 pytest：186 passed。
- socket 阻断：启用，未访问真实网络。
- 时间泄漏、公式复算、输入不可变性：PASS。
- 幂等测试：FAIL，同 run、同路径第二次数据库写入被拒绝。
- 冲突拒绝与实际回滚：PASS；冲突错误清晰度：FAIL。
- Ruff：未安装，WARN；本次遵循离线约束未安装。

## 18. 阶段边界

最终排名、交易信号、投资建议、模型训练/预测、阶段7正式产物均为 0。未执行真实网络访问，未重新执行正式 build-stage6，未修改 Raw、Clean、阶段5数据库、正式 Feature、阶段6正式数据库或既有 manifest。

## 19. 安全与Git

未发现有效凭据、个人绝对路径、被跟踪的 `.env` 或遗留 lock/WAL/temp 文件。当前分支 `master`，HEAD `9aea2edb60afdc8930953188149398b25c71675d`；阶段1至阶段6的大量文件仍未跟踪，建议先修复阻断缺陷并复验，再建立 Git 检查点。

## 20. 失败和警告

失败：

1. 完整非空输入的同 run、同路径数据库复跑不幂等。
2. 数据库 payload 冲突错误被二次 rollback 异常覆盖，错误不清晰。

警告：

- 3,862 条涨跌停规则均不确定，但未猜测、未误报。
- rolling warm-up NULL 为预期。
- 16 条疑似主力行为特征均为证据不足。
- `feature_quality_issue` 是组级汇总，未单列 unknown-rule WARN。
- 存在旧的非本次正式 run 数据库，已隔离、未混用。
- 建议的三个拆分模块不存在，相应职责集中在 `stage6_build.py`。
- Ruff 未安装。
- Git 跟踪不完整。

## 21. 验收产物

本次创建 `docs/stage6_acceptance.md`、`reports/stage6_acceptance.json`、pre-gate JSON、11 个指定 CSV，以及补充的 `reports/stage6_acceptance_idempotency_detail.json`。没有覆盖既有阶段6运行报告或 manifest。

## 22. 阶段7入口结论

> 阶段6尚未通过独立验收，当前禁止进入阶段7。请先修复本报告列出的数据库幂等性和冲突错误处理问题，再重新执行阶段6独立验收。
