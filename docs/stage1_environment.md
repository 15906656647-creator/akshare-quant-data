# 阶段1：环境与项目骨架 — 验收报告

> 文档日期：2026-07-28
> 基线日期：2026-07-27

## 1. 阶段目标和范围

完成一套可复现、可导入、可测试、默认不访问业务网络的 Python 工程环境。建立了项目虚拟环境、依赖管理、标准目录骨架、配置加载器、离线环境检查（doctor）和 CLI 框架。

本阶段：
- 不调用任何 AKShare 数据接口。
- 不抓取真实数据。
- 不创建正式业务数据库表。
- 不进入接口冒烟测试阶段。

## 2. 环境信息

| 项目 | 值 |
|---|---|
| 操作系统 | Windows (win32) |
| Python 版本 | 3.11.4 (64-bit CPython) |
| Python 实现 | cpython |
| 虚拟环境 | `./.venv` (项目根目录) |
| 安装方式 | `pip install -e ".[dev]"` (editable install) |

**偏差说明**：任务要求优先使用 Python 3.12，当前系统为 3.11.4。符合 ≥3.9 的最低要求，但未达到优先推荐版本。系统级 Python 来自 Anaconda，未做修改。

## 3. 核心依赖版本

| 包 | 版本 |
|---|---|
| akshare | 1.18.80 |
| pandas | 3.0.5 |
| numpy | 2.4.6 |
| pyarrow | 25.0.0 |
| duckdb | 1.5.5 |
| sqlalchemy | 2.0.51 |
| pydantic | 2.13.4 |
| pyyaml | 6.0.3 |
| python-dotenv | 1.2.2 |
| tenacity | 9.1.4 |
| matplotlib | 3.11.1 |
| openpyxl | 3.1.5 |
| pytest | 9.1.1 |
| pandera | 0.32.1 |

## 4. 项目目录结构

```text
.
├── AGENTS.md
├── README.md
├── pyproject.toml
├── requirements-lock.txt
├── .env.example
├── .gitignore
├── config/
│   ├── universe.yml
│   └── metric_definition.yml
├── data/
│   ├── raw/.gitkeep
│   ├── clean/.gitkeep
│   ├── feature/.gitkeep
│   └── export/.gitkeep
├── database/.gitkeep
├── logs/.gitkeep
├── notebooks/.gitkeep
├── reports/
│   ├── .gitkeep
│   └── stage1_environment_check.json
├── sql/.gitkeep
├── docs/
│   ├── stage0_scope.md
│   └── stage1_environment.md
├── src/akshare_data_test/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── doctor.py
│   ├── logging_config.py
│   ├── paths.py
│   ├── adapters/__init__.py
│   ├── collectors/__init__.py
│   ├── cleaners/__init__.py
│   ├── features/__init__.py
│   ├── storage/__init__.py
│   ├── quality/__init__.py
│   └── utils/__init__.py
├── tests/
│   ├── test_stage0_config.py
│   ├── test_stage1_cli.py
│   ├── test_stage1_config_loader.py
│   ├── test_stage1_doctor.py
│   └── test_stage1_structure.py
└── run_pipeline.py
```

## 5. 关键模块说明

| 模块 | 功能 |
|---|---|
| `paths.py` | 基于 `__file__` 的项目路径，不依赖 cwd。 |
| `config.py` | 加载 Universe/Metric YAML，解析和验证日期格式，保持股票代码为字符串。 |
| `logging_config.py` | 控制台/文件日志，防重复初始化，不记录敏感信息。 |
| `doctor.py` | 离线环境检查：Python、包、配置、文件系统、DuckDB 内存连接。 |
| `cli.py` | `argparse` 实现 `doctor` 和 `show-config` 子命令。 |

## 6. 配置加载和日期解析规则

- `resolve_as_of_date()`：CLI `--as-of-date` 优先，否则回退到 `universe.yml` 中的 `as_of_date`。
- **绝不静默使用 `datetime.now()` 作为业务日期**。
- 无效日期格式抛出 `ConfigError` 并包含文件路径。

## 7. 验收命令与结果

### 7.1 pip check

```bash
$ .venv\Scripts\python.exe -m pip check
No broken requirements found.
```

退出码：0

### 7.2 show-config

```bash
$ python run_pipeline.py show-config --as-of-date 2026-07-27
Project: AKShare 量化金融数据测试
Schema version: 1.0.0
Timezone: Asia/Shanghai
Base currency: CNY
Resolved as_of_date: 2026-07-27
Stock count: 16
...（16 只股票全部列出）
Crypto: ETHUSDT (exact_match: True)
```

退出码：0

### 7.3 doctor

```bash
$ python run_pipeline.py doctor --as-of-date 2026-07-27 --output reports/stage1_environment_check.json
Doctor check: PASS
  Python: 3.11.4 (64bit)
  Resolved as_of_date: 2026-07-27
  Packages: 14/14 importable
  Config checks: 9/9
  Filesystem checks: 20/20
  DuckDB memory: OK
```

退出码：0。JSON 报告已生成到 `reports/stage1_environment_check.json`。

### 7.4 CLI 入口

```bash
$ akshare-data-test doctor --as-of-date 2026-07-27
Doctor check: PASS
...
```

退出码：0

### 7.5 pytest

```bash
$ .venv\Scripts\python.exe -m pytest -q
74 passed in 18.44s
```

退出码：0。全部 74 个测试通过，包括：
- 配置加载测试 (19)
- CLI 测试 (11)
- 离线 Doctor 测试 (7)
- 目录结构/边界/哈希测试 (37)

## 8. 阶段0文件哈希校验

| 文件 | 开始 SHA-256 | 结束 SHA-256 | 一致 |
|---|---|---|---|
| `config/universe.yml` | `0B6F61...CCEC65` | `0B6F61...CCEC65` | ✓ |
| `config/metric_definition.yml` | `13F941...5C00C4` | `13F941...5C00C4` | ✓ |
| `docs/stage0_scope.md` | `18EEEC...761615` | `18EEEC...761615` | ✓ |

三个文件前后完全一致。

## 9. 偏差与风险

| 项目 | 说明 |
|---|---|
| Python 版本 | 用户系统为 3.11.4，而非优先推荐的 3.12。仍然满足 ≥3.9 的最低要求，不影响功能。 |
| 网络依赖 | 安装依赖时需访问 PyPI，之后所有测试和命令均离线运行。 |

## 10. 下一阶段入口条件

阶段2：接口盘点与冒烟测试。入口条件已满足：
- [x] 64 位 Python 3.9+ 可用
- [x] `.venv` 隔离环境就绪
- [x] 所有运行和开发依赖已安装
- [x] `pyproject.toml` 作为依赖单一来源
- [x] `requirements-lock.txt` 来自真实环境
- [x] 配置加载器可读阶段0配置
- [x] 业务日期仅来自配置或 CLI
- [x] 离线 `doctor` 全部通过
- [x] `pip check` 通过
- [x] 全部 74 个 pytest 测试通过
- [x] 无 AKShare 数据接口调用
- [x] 无真实数据、正式业务表或阶段2代码
- [x] 阶段0 文件哈希未变

> 本任务未调用任何 AKShare 数据接口、未抓取真实数据、未创建正式业务表、未进入接口冒烟测试阶段。
