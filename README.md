# AKShare 量化金融数据测试

## 项目目的

基于 AKShare 开源金融数据接口，对 16 只 A 股 + ETHUSDT 进行系统化数据抓取、清洗、
指标计算和分析测试。项目按阶段推进，当前已完成：

- **阶段 0**：冻结范围与分析口径
- **阶段 1**：环境与项目骨架
- **阶段 2**：接口盘点与冒烟测试
- **阶段 3**：行情与实时估值 Raw 抓取
- **阶段 4**：财务与资金流 Raw 抓取

## 当前完成阶段

阶段 4：16只A股的财务摘要、财务分析指标、三大财务报表和个股资金流
共96项 Raw 已完成抓取和证据留存。正式运行
`62bbe9df-6ed8-48d5-a06b-10fb90171ee0` 已通过离线验收。

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

## 当前阶段限制

阶段 4：
- 仅保存财务摘要、财务分析指标、三大财务报表和个股资金流 Raw；
- Raw 数据按 `run_id` 追加保存；
- 不创建 Clean、Feature 或正式业务数据库；
- 不计算单季度、TTM、同比、环比或财务比率；
- 不进行确定性资金行为解释。

## 下一阶段

阶段 4 已验收通过；如需进入阶段 5，必须另开独立任务实施数据清洗、
字段映射与数据库建设。
