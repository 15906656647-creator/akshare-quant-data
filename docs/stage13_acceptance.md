# Stage 13 修复与再次独立验收准备记录

## 结论

Stage 13 修复完成，具备再次独立验收条件。本记录覆盖 S13-REVERIFY-001 至 003 的实施与自检；未提交、未创建标签、未创建或进入 Stage 14。

## 问题关闭记录

### S13-REVERIFY-001 — CLOSED

- 原问题：`feature_lineage.created_at` 为 VARCHAR，却直接与 DATE 参数比较，产生 Binder Error；inventory 为 BLOCKED 时正式运行仍标为 READY。
- 根因：inventory 只按候选列名选择过滤，没有读取并使用 DuckDB 列类型；发布前没有统一 inventory 阻断门禁。
- 修复文件：`src/akshare_data_test/stage13_presentation.py`、`src/akshare_data_test/quality/stage13_checks.py`、`tests/test_stage13_database_inventory.py`。
- 新增测试：DATE、TIMESTAMP、TIMESTAMPTZ、可解析/部分/完全不可解析 VARCHAR、审计时间、空表、静态表、无 symbol、view、特殊表名、三个正式数据库、真实错误传播、质量 CSV 和旧报告保留。
- 故障注入：临时 Stage 6 数据库加入在过滤时调用 DuckDB `error()` 的 view；运行返回 BLOCKED、非零退出、quality FAIL，已有报告逐字节不变。
- 实际结果：正式 3 个数据库、5 个 schema、42 个表/视图全部 AVAILABLE；BLOCKED=0。`feature_lineage.created_at` 记录为 VARCHAR/NOT_APPLICABLE。

### S13-REVERIFY-002 — CLOSED

- 原问题：confirmed 事件 CSV 没有真实事件价格。
- 根因：Stage 13 查询和输出列丢弃 Stage 6 `feat_limit_event.raw_close`，事件图只绘制方向占位值。
- 修复文件：`src/akshare_data_test/stage13_presentation.py`、`src/akshare_data_test/presentation/charts.py`、`src/akshare_data_test/quality/stage13_checks.py`、`tests/test_stage13_limit_events.py`。
- 新增测试：事件源缺失、零事件完整 schema、confirmed 涨停/跌停、多个事件、未来/未确认排除、权威价格来源、图表输入对账、六种非法价格和完整报告级对账。
- 故障注入：临时 Stage 6 数据库将 000100 的 2026-07-21、2026-07-23 事件设为 confirmed；CSV 与源 `raw_close` 逐行一致，图表收到相同 DataFrame。
- 实际结果：次日收益保持 `-0.020560747663551315`、`-0.0174418604651162`；正式源当前 confirmed=0，但 16 个空 CSV 均保留完整 event price schema。

### S13-REVERIFY-003 — CLOSED

- 原问题：54 项旧测试没有捕获 inventory Binder Error/READY 误报和事件价格缺失。
- 根因：inventory 测试仅检查 Stage 5 文件大小和少量表名；事件测试没有断言权威价格、图表或完整报告。
- 修复文件：上述两个测试文件以及本实施/验收文档。
- 新增测试：14 个实际测试节点；不是数量自检，也没有 skip/xfail。
- 实际结果：定向修复测试 26 passed；全部 Stage 13 测试 68 passed；扩大历史影响测试 334 passed；完整回归 799 passed。

## 正式报告证据

- 截止日：`2026-07-27`；run_id：`stage13-20260727-reverify-remediation`。
- `config/stage13.yml` SHA-256：`aded67bbde36eb19927552d9a280adeb93718463c6dcc8bf7bc7ba52716dc6d7`。
- `visible_input_sha256`：`28fda7115e9d0c3515d85198511dfcdb5771ae341116c2f7242d18a609a1e24a`。
- `canonical_sha256`：`360fcbc6ee33d47c7d765806899dcacf8bf26118d4e2fc2a686d6734a02d31be`。
- `run_identity_sha256`：`05bb6ac9b76208df9569571afc02fb80ae5c6ac3cdcc07a3140a6871cfb9272b`。
- 正式运行：READY；`inventory_blocked_count=0`；`blocking_reasons=[]`；quality `inventory_no_blocked=PASS`。
- inventory：3 个数据库、5 个 schema、42 个表/视图；AVAILABLE 42、PARTIAL 0、NOT_AVAILABLE 0、BLOCKED 0。
- 资产矩阵：144 行；AVAILABLE 112、PARTIAL 16、NOT_AVAILABLE 16、BLOCKED 0。
- 正式目录：222 个文件、128 张 PNG、87 个 CSV、12,621,851 字节；资产 manifest SHA-256 为 `0b04aec9fa893e5e908f2d6121a1dc8ed4445cdf42878261b9d3dddd898750cb`。

## 测试和黑盒门禁

```text
Targeted remediation tests: 26 passed
Stage 13 tests: 68 passed
Affected historical tests: 334 passed
Stage 0 frozen-config checks: 35/35 passed
Full regression: 799 passed
```

全部为 0 failed，无 skip、xfail 或未解释 warning。

- 八类极端未来数据黑盒：222/222 发布文件逐字节一致；visible input、canonical、run identity 一致。
- 网络阻断守卫：socket、requests、urllib、httpx、aiohttp、AKShare 股票/加密接口尝试均为 0。
- CLI dry-run：单行 JSON、READY、退出码 0。
- 原子性、相同输入字节幂等、run ID 冲突、图表稳定、SQL manifest、活跃度和历史保护均通过。
- 输入数据库在正式生成和测试前后 SHA-256 一致。

## 限制与纪律

- 截止日前没有可用估值快照，因此 16 项估值资产保持 NOT_AVAILABLE，不回填、不倒推。
- 当前 Stage 6 正式事件源没有 confirmed 行，因此事件和次日收益展示为合法 AVAILABLE 空样本；正向事件能力由临时真实结构 fixture 验证。
- 40 日图缺少正式突破事件标记，因此保持 PARTIAL。
- 资金流相关内容只能描述为**疑似主力行为特征**并保留证据、置信度和解释。
- 项目仅用于研究和数据链路测试，不构成投资建议。
