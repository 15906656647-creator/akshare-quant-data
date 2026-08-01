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
