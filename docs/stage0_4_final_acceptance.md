# 阶段0—4独立最终验收报告

验收日期：2026-07-29
验收方式：离线、只读核验既有业务产物；未调用新的 AKShare 业务接口。
验收范围：阶段0—4；未执行阶段5。

## 1. 总结论

| 项目 | 结论 |
|---|---|
| 总验收 | **PASS** |
| 阶段0 | PASS |
| 阶段1 | PASS |
| 阶段2工程验收 | PASS |
| 阶段2真实接口证据 | PASS |
| 阶段3 | PASS |
| 阶段4 | PASS |
| 阶段边界 | PASS |
| 安全检查 | PASS（有非阻断警告） |
| 是否允许进入阶段5 | **是** |

本次不存在尚待用户执行的本地 PowerShell 验收项。验收期间未修改业务源码、测试、
Raw 或既有 manifest；只新增了本 Prompt 允许的独立验收报告。

## 2. 实际执行命令

以下时间均为 Asia/Shanghai。

| 命令 | 开始时间 | 秒 | 退出码 | 结果 |
|---|---:|---:|---:|---|
| `.venv\Scripts\python.exe -m pip check` | 20:11:37 | 0.544 | 0 | 无损坏依赖 |
| `.venv\Scripts\python.exe -c <14项必需导入>` | 20:11:38 | 2.052 | 0 | 14/14 |
| `.venv\Scripts\python.exe run_pipeline.py show-config --as-of-date 2026-07-27` | 20:11:40 | 0.151 | 0 | 16股、ETHUSDT 精确匹配 |
| `.venv\Scripts\python.exe run_pipeline.py show-config --as-of-date 2026-07-20` | 20:11:40 | 0.146 | 0 | 覆盖日期生效 |
| `.venv\Scripts\python.exe run_pipeline.py doctor --as-of-date 2026-07-27 --report ...` | 20:11:40 | 0.135 | 2 | 参数名错误，随后纠正 |
| `.venv\Scripts\python.exe run_pipeline.py doctor --as-of-date 2026-07-27 --output reports/stage0_4_acceptance_doctor.json` | 20:12:16 | 2.066 | 0 | PASS |
| `.venv\Scripts\python.exe -m pytest -q` | 20:11:40 | 20.146 | 0 | 143 passed，无 skip |
| `.venv\Scripts\python.exe -m ruff check .` | 20:12:00 | 0.059 | 1 | Ruff 未安装，按规则记 WARN |
| `.venv\Scripts\python.exe -m ruff format --check .` | 20:12:00 | 0.057 | 1 | Ruff 未安装，按规则记 WARN |
| 离线 Python：阶段3/4 manifest、SHA-256、Parquet 元数据复验 | 20:14:05 | 0.377 | 0 | 130/130 Raw 通过 |

首次 doctor 命令误用了不存在的 `--report` 参数。纠正为帮助信息规定的 `--output`
后，doctor 实际门禁通过；失败尝试未被隐去。

## 3. 阶段0结果

- `as_of_date`：`2026-07-27`，两个冻结配置一致。
- 16只股票代码、顺序、交易所映射与冻结范围一致。
- 加密货币目标为 `ETHUSDT`，要求精确匹配，禁止替换交易对。
- 阶段0测试文件存在，完整 pytest 中相关测试通过。

冻结文件 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `config/universe.yml` | `0b6f61d43e753945b7e7931d27359e34a199891eac3f7d59f29c9d17efccec65` |
| `config/metric_definition.yml` | `13f9415d3e55aacc91e9913652d6e6520d9c681ac3043f09409602c44b5c00c4` |
| `docs/stage0_scope.md` | `18eeec59594b2cca67cfc7e7f137855ed2b1f018c10623e426340188ac761615` |

结论：**PASS**。

## 4. 阶段1结果

- 项目虚拟环境有效：Python 3.11.4、64 位。
- `pip check`：PASS。
- 必需包：14/14 可导入。
- `requirements-lock.txt`：58项固定版本与当前环境 58/58 一致。
- `show-config`：默认日期和显式覆盖日期均通过。
- doctor：PASS；14/14 包、9/9 配置、20/20 文件系统检查通过，内存 DuckDB 正常。
- 完整 pytest：143 passed，0 failed，未报告 skip。
- Ruff 未安装；按 Prompt 仅记 WARN，未安装或修改依赖。

结论：**PASS**。

## 5. 阶段2结果

本地真实冒烟 run_id：`728cf611-e063-403e-90ab-a0b736a946f1`。

- 本地网络预检：PASS，6个目标主机均有成功证据。
- 12个探针、11个唯一 AKShare 函数。
- 12/12 状态为 `success`，12/12 返回非空。
- 每个探针对应的12个 sample 和12个 schema 文件均存在、非空且 JSON 可解析。
- 5个财务探针成功，1个个股资金流探针成功。
- 涨停池：`2026-07-24`、40行、`pool_date_source=cli`。
- 跌停池：`2026-07-24`、25行、`pool_date_source=cli`。
- 加密市场探针返回10行非空数据；目标 `ETHUSDT` 的严格能力结论为
  `unsupported`，未替换为其他交易对。

本次只读取既有本地真实证据，没有重新调用 AKShare。

结论：工程验收 **PASS**，真实接口证据 **PASS**。

## 6. 阶段3结果

正式 run_id：`39a6996e-36d7-4b73-b0b8-c38da4ae672e`。

- coverage：49条，49个唯一 dataset，全部 `success`。
- 日线：16股 × qfq/raw = 32/32 成功。
- Raw：34/34 存在、非空、可读取。
- manifest：登记34个 Raw、4个报告文件。
- manifest 全量完整性：38/38 文件大小和 SHA-256 与实际一致。
- qfq/raw：16/16 股票日期键完全一致。
- 日线日期均为 `2023-07-27` 至 `2026-07-27`，无重复日期、OHLC 错误或负成交量/成交额。
- spot 全市场 Raw：5,884行；目标股票：16/16，无缺失。

专项缺口：

- `600438` 比共同交易日参考少10日；
- `601500` 比共同交易日参考少4日；
- 两股 qfq/raw 缺失日期完全一致，文件连续可读，属于停牌型缺口证据，按 Prompt 记 WARN。

结论：**PASS**。

## 7. 阶段4结果

正式 run_id：`62bbe9df-6ed8-48d5-a06b-10fb90171ee0`。

- coverage 恰好96条，`symbol + interface_id` 恰好96个唯一组合。
- `success=96`、`failed=0`、`empty=0`；96项全部非空。
- 六类接口各16/16成功：财务摘要、财务指标、资产负债表、利润表、现金流量表、个股资金流。
- Raw：96/96 存在、非空、可读取。
- manifest：登记96个 Raw、9个报告文件。
- manifest 全量完整性：105/105 文件大小和 SHA-256 与实际一致。
- 原13项失败任务：13/13 已成为非空 `success`。
- 修复前83个成功 Raw：83/83 大小和 SHA-256 均未变化。
- 初始失败 coverage、初始失败 run、初始失败 manifest 和
  `manifest.before_repair.json` 均保留。
- resume stdout/stderr 存在；13项任务对应26个隔离日志文件存在。
- 核心字段报告：16股、10个概念、160条字段可用性记录。
- 点时风险：3,566条；已识别 `potential_lookahead=0`、未来报告期错误0条；
  公告日期不可识别32条均明确标记 `unavailable` 和 WARN，没有当作点时安全。
- 资金流：16股均为120行，实际窗口最早 `2026-01-27`、最晚 `2026-07-28`；
  报告明确声明上游窗口有限，未声称是完整多年历史。
- Raw 保留上游宽表；未发现单季度、TTM、同比、环比或新增财务比率计算，
  未输出确定性主力行为结论。

结论：**PASS**。

## 8. 阶段边界

- `data/clean`、`data/feature`、`data/export` 只有空目录或 `.gitkeep`。
- 未发现 Feature、分析结果、业务导出或阶段5业务产物。
- 未发现 `.db`、`.duckdb`、`.sqlite` 或 `.sqlite3` 业务数据库。
- doctor 仅使用内存 DuckDB 健康检查，不构成业务数据库。

结论：**PASS**，未进入阶段5。

## 9. 安全和 Git

安全扫描未发现有效 API key、Token、Cookie、Authorization、Password、代理凭据
或带凭据 URL；`.env` 未被 Git 跟踪。阶段2—4 evidence manifest 的文件路径均为
项目相对路径。

存在非阻断路径警告：若干环境 doctor 报告、`requirements-lock.txt` 和未跟踪的
`_accept_verify.py` 含本机盘符路径。它们没有包含有效凭据，但交付前宜脱敏或审阅。

Git 当前为 `master`，HEAD
`9aea2edb60afdc8930953188149398b25c71675d`。`git diff --check` 通过，但仓库只有
阶段0检查点：`src`、`reports` 和绝大多数阶段1—4测试/文档均未跟踪，`AGENTS.md`
已修改，且存在未跟踪辅助脚本。这不阻断本次功能验收，但属于显著交付风险。建议在
人工审阅后建立 Git 检查点；本次未执行 `git add` 或 `git commit`。

## 10. 失败和警告

失败：无。

警告：

1. Ruff 未安装，未执行有效 lint/format 检查。
2. 缺少 `CODEX_STAGE0_PROMPT.md`、`CODEX_STAGE3_PROMPT.md`、
   `CODEX_STAGE4_PROMPT.md`、`docs/stage2_repair.md`、
   `docs/stage4_acceptance.md` 和 `reports/stage4_acceptance.json`；等价运行、
   repair、Raw 和 manifest 证据均已独立验证。
3. `600438` 和 `601500` 存在 qfq/raw 一致的停牌型日期缺口。
4. `ETHUSDT` 精确交易对能力为 `unsupported`，且未作交易对替换。
5. 阶段4有32条公告日期不可识别记录，已正确标记风险。
6. 资金流是上游有限窗口，且最晚日期为执行时点附近的 `2026-07-28`。
7. 环境报告、锁文件和辅助脚本存在本机绝对路径，但未发现有效凭据。
8. Git 中阶段1—4关键交付内容大量未跟踪，建议建立审阅后的检查点。
9. 一次 doctor 命令参数误写，已如实记录；纠正后的正式门禁通过。

## 11. 需要用户在本地 PowerShell 执行的操作

无。本环境可访问项目 `.venv`、Git、阶段2本地证据以及全部130个 Raw 文件，
不存在 `[需要本地PowerShell]` 待办。

## 12. 证据文件

- `reports/stage0_4_final_acceptance.json`
- `reports/stage0_4_acceptance_doctor.json`
- `reports/stage0_4_file_integrity.csv`：167条证据文件记录，0失败
- `reports/stage0_4_raw_validation.csv`：130条 Raw 逐文件记录，0失败
- `reports/stage0_4_daily_quality.csv`：32条日线质量记录，0失败
- `reports/stage0_4_stage4_task_matrix.csv`：96项阶段4任务，0失败
- `reports/stage0_4_scope_boundary.csv`
- `reports/stage0_4_security_scan.csv`

## 13. 最终结论

阶段0—4已经完成独立验收，配置、测试、真实接口证据、阶段3的34个Raw文件和阶段4的96个Raw文件均通过完整性检查，当前可以进入阶段5：数据清洗、字段映射、Clean层建设和DuckDB数据库落地。
