# AKShare 量化金融数据测试

## 项目目的

基于 AKShare 开源金融数据接口，对 16 只 A 股 + ETHUSDT 进行系统化数据抓取、清洗、
指标计算和分析测试。项目按阶段推进，当前已完成：

- **阶段 0**：冻结范围与分析口径
- **阶段 1**：环境与项目骨架
- **阶段 2**：接口盘点与冒烟测试
- **阶段 3**：行情与实时估值 Raw 抓取
- **阶段 4**：财务与资金流 Raw 抓取
- **阶段 5**：Clean 数据与 DuckDB
- **阶段 6**：技术及量价特征
- **阶段 7**：均线、量价与活跃度特征
- **阶段 8**：涨跌停统计与事件研究工程实现（正式发布仍阻塞）
- **阶段 9**：横盘震荡、疑似洗盘特征与量价风格工程实现
- **阶段 10**：基本面与当前估值快照分析工程实现
- **阶段 11**：ETHUSDT 能力验证
- **阶段 12**：可复现筛选分析样例
- **阶段 13**：图表、数据库展示和报告产物
- **阶段 14**：统一命令行自动化编排
- **阶段 15**：质量控制和风险验证

## 当前完成阶段

阶段 7 基线已冻结。阶段 8 已实现离线、fail-closed 的事件识别、质量门禁、
run 版本化存储和只读预检；由于权威历史涨跌停规则及证券状态历史仍缺失，
正式全年统计保持 `BLOCKED`，fixture 结果不得作为正式结论。
阶段 9 核心分析独立使用 qfq OHLCV，不把阶段 8 的 NULL/not_calculated
转换为 0；可选事件辅助字段始终按 formal、candidate、proxy、gap_proxy 和
unresolved 分开保存。

## Python / 虚拟环境

- Python 3.9+（推荐 3.12），64 位
- 使用 `venv` 隔离依赖

## 安装

```bash
python -m venv .venv
# Windows:
.venv\Scripts\Activate.ps1
# Linux/macOS:
source .venv/bin/activate

pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
```

## 命令行用法

```bash
# 离线环境检查
python run_pipeline.py doctor --as-of-date 2026-07-27

# 或通过入口命令
akshare-data-test doctor --as-of-date 2026-07-27

# 查看安全配置摘要
python run_pipeline.py show-config --as-of-date 2026-07-27

# 阶段3行情 Raw 抓取（会访问真实网络）
python run_pipeline.py fetch-market --as-of-date 2026-07-27

# 阶段8只读预检：不创建输出数据库，不访问网络
python run_pipeline.py analyze-limit-events `
  --as-of-date 2026-07-27 `
  --validate-only

# 阶段8离线 dry-run：读取 raw 数据但不写数据库或报告
python run_pipeline.py analyze-limit-events `
  --as-of-date 2026-07-27 `
  --dry-run

# 仅排查内部错误时显式显示 traceback
python run_pipeline.py analyze-limit-events `
  --as-of-date 2026-07-27 `
  --validate-only `
  --debug

# 阶段9只读预检
python run_pipeline.py analyze-style `
  --as-of-date 2026-07-27 `
  --validate-only

# 阶段9离线 dry-run，不写数据库或报告
python run_pipeline.py analyze-style `
  --as-of-date 2026-07-27 `
  --windows 20 40 60 `
  --dry-run

# 阶段10只读预检
python run_pipeline.py analyze-fundamental `
  --as-of-date 2026-07-27 `
  --input-manifest reports/stage5_verified_manifest.json `
  --validate-only

# 阶段10离线 dry-run，不写数据库或报告
python run_pipeline.py analyze-fundamental `
  --as-of-date 2026-07-27 `
  --input-manifest reports/stage5_verified_manifest.json `
  --symbols 002067 002600 `
  --dry-run
```

## 阶段 14 自动化运行

所有阶段 14 命令支持 `--help`。`run-all` 使用一个 UUID `run_id` 串联全部
子任务，任何真实子命令返回非零退出码时立即停止。日期必须为 `YYYYMMDD`，不会
静默交换起止日期。

```bash
# 单阶段命令（未给日期时使用冻结配置中的基线日期与默认回看范围）
python run_pipeline.py fetch-financial
python run_pipeline.py fetch-event-and-fund-flow
python run_pipeline.py clean
python run_pipeline.py load-database
python run_pipeline.py quality-check
python run_pipeline.py build-report

# 行情抓取的显式日期接口（--start 和 --end 必须成对提供）
python run_pipeline.py fetch-market --start 20230101 --end 20260727

# 全流程；日期为必填项
python run_pipeline.py run-all --start 20230101 --end 20260727

# 只显示计划，不执行子任务，不写数据、数据库或运行日志
python run_pipeline.py run-all --start 20250101 --end 20250131 --dry-run

# 查看帮助
python run_pipeline.py --help
python run_pipeline.py fetch-market --help
python run_pipeline.py run-all --help
```

完整顺序为：`smoke-test → fetch-market → fetch-financial →
fetch-event-and-fund-flow → clean → load-database → build-features →
analyze-limit-events → analyze-style → quality-check → build-report`。

现有 Stage 4 以单个不可变 manifest 原子发布财务和资金流，因此全流程中的
`fetch-event-and-fund-flow` 会记录为 `skipped/covered`，不会用同一个 `run_id`
重复写 Raw；单独执行该命令时则真实抓取个股资金流。现有 Stage 5 以一个事务完成
Clean 文件和 DuckDB 发布，因此 `run-all` 中的 `load-database` 记录为已由
`clean` 覆盖；单独执行时则真实复用 Stage 5 原子构建入口。这两个覆盖状态不是
静默成功，原因会写进状态文件。

失败后查看 `logs/<run_id>/pipeline.log` 与
`logs/<run_id>/task_status.json`。结构化失败项位于
`reports/run_status/<run_id>_failed_items.csv`。修复后可使用同名单阶段命令并
指定新的 `--run-id` 重跑；Raw 仍按 run 分区追加，空结果和失败不会覆盖已有
非空文件。Stage 5/7/8/9 的正式数据库写入沿用已有事务、主键 upsert 和质量
门禁。Stage 14 数据库放在 `database/stage14/<run_id>/`，历史报告由既有
Stage 13 发布规则管理。

`--force` 只作为运行意图写入状态记录；它不会绕过 Raw 不可变保护、数据库
唯一键或质量门禁。项目仅用于研究测试，不构成投资建议。

## 阶段 15 质量控制和风险验证

`quality-control` 是阶段15的独立离线入口，读取 Stage 5 DuckDB、Stage 10 财务
字段映射以及 Stage 2/4 耗时报告，生成每日质量检查、交叉验证快照和风险日志。

```bash
# 只读预检，不写输出
python run_pipeline.py quality-control --as-of-date 2026-07-27 --validate-only

# 查看计划，不写输出
python run_pipeline.py quality-control --as-of-date 2026-07-27 --dry-run

# 正式运行（自动生成 UUID run_id）
python run_pipeline.py quality-control --as-of-date 2026-07-27

# 指定 run_id 与自定义输出
python run_pipeline.py quality-control --as-of-date 2026-07-27 \
  --run-id <uuid> \
  --output-database database/stage15/<uuid>/stage15_quality.duckdb
```

退出码：`0` = PASS / WARN / PASS_WITH_UNAVAILABLE_ITEMS，`1` = ERROR 级检查失败，
`2` = 输入预检 BLOCKED。存在 `UNAVAILABLE` 交叉验证项或 BLOCKED 风险时整体状态为
`PASS_WITH_UNAVAILABLE_ITEMS`，不会用 `PASS` 掩盖未完成的交叉验证。
输出位于 `reports/stage15/<run_id>/` 与 `database/stage15/<run_id>/`。Stage 8
正式涨停事件缺失时，交叉验证涨停项标记 `UNAVAILABLE` 并写入 `blocked` 风险，
不伪造正式结果。

截至 2026-08-24，Stage 15 在治理层为 `CONDITIONALLY_CLOSED`，因此允许进入
Stage 17；这不会改变上述程序状态。S15-14 和正式涨跌停事件仍为
`BLOCKED/UNAVAILABLE`，Stage 19 正式发布门禁继续有效。完整决策见
[`docs/stage15_conditional_closure.md`](docs/stage15_conditional_closure.md)。

## Stage 17 多市场原始数据采集

`collect-stage17`按独立`run_id`采集A股、港股和OKX `ETH-USDT` Raw数据。
配置、实施和验收分别见`config/stage17.yml`、
[`docs/stage17_implementation.md`](docs/stage17_implementation.md)和
[`docs/stage17_acceptance.md`](docs/stage17_acceptance.md)。

```bash
python run_pipeline.py collect-stage17 --as-of-date 2026-08-24 --validate-only
python run_pipeline.py collect-stage17 --as-of-date 2026-08-24 --dry-run
python run_pipeline.py collect-stage17 --as-of-date 2026-08-24 --run-id <uuid>
```

截至2026-08-24，重新审计后的正式批次状态仍为`BLOCKED`：A股48/48通过，港股
21/21因主源连接失败且新浪候选存在`ohlc_logic_error`而保持阻塞；正式日线非空数与
质量通过数均为48/69，ETH六周期全部通过。CLI会分别显示非空Raw数和质量通过数。
Stage 18未获授权。本入口不会采集财务报表或生成涨跌停事件。

## 目录结构

```text
config/          — 冻结的业务配置（只读契约）
data/            — 数据分层（raw/clean/feature/export）
database/        — DuckDB 数据库（后续阶段启用）
docs/            — 阶段文档和范围说明
logs/            — 运行日志
notebooks/       — 探索性分析
reports/         — 阶段报告
sql/             — SQL 查询模板
src/             — Python 包源码
tests/           — 自动化测试
```

## 阶段 8 安全限制

- 涨跌停识别只读取 `raw/unadjusted` 真实交易价格。
- `validate-only` 以 DuckDB 只读模式检查文件、表、字段、口径、日期范围和重复键。
- 缺少权威规则、ST/板块/上市状态历史时返回 `BLOCKED`，不把未计算解释为 0。
- `gap_proxy`、candidate、proxy 和 unresolved 永不进入正式年度统计。
- 写后门禁交叉核对 DuckDB、JSON、CSV 和 Markdown；null 与数值 0 严格区分。
- 阶段 8 输出数据库必须与阶段 7 数据库分离；测试数据库仅放临时目录。
- 项目仅用于研究测试，不构成投资建议。

## 阶段 9 口径

- 使用 qfq、按证券有效交易行计算 20/40/60 日窗口，主窗口为 40 日。
- 所有 as-of 特征只使用截止日及以前数据；假突破只计已完成的 1～3 个交易日确认。
- 停牌、零成交及非法 OHLC 行不占窗口；样本不足输出 `insufficient_history`。
- 输出是横盘震荡风格、疑似洗盘特征、量价行为特征和疑似主力行为特征的统计描述。
- 不输出确定性主力行为、交易信号或投资建议。

## 阶段 10 口径

- 只读取阶段 5 中公告日期不晚于显式 `as-of-date` 的财务事实和估值快照，不访问网络。
- 同一报告期的不同来源运行按版本保留；同一标准指标的源字段按配置优先级唯一选取，并保存来源和冲突标记；利润表和现金流量表累计值按 Q1、H1、Q1-Q3、全年转换为单季度。
- 最近四个完整季度用于 TTM；缺少前期累计、上年同期或完整四季度时保持空值并保存原因。
- PE/PB 只作为 `current valuation snapshot`；负 PE 标记 `loss-making`，缺失 PE/PB 不填 0，也不伪造历史估值。
- `validate-only` 只读并要求通过验证的 Stage 5 manifest 与 PASS `etl_run` 一致，`dry-run` 不写数据库或报告；正式写入使用独立 Stage 10 DuckDB 和事务。
- 基本面评分和解释只描述真实指标，不给出价值高低、交易信号或投资建议。
