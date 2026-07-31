# Codex 任务：阶段1——环境与项目骨架

你正在当前 AKShare 数据抓取测试项目的根目录中工作。阶段0已经完全验收，本任务只完成“阶段1：环境与项目骨架”。

> 范围映射说明：本次 Codex 任务合并实施《AKShare数据抓取测试_分阶段操作步骤》中的“阶段一：环境搭建”和“阶段二：建立项目目录和配置”，作为当前项目管理中的阶段1。不得进入该文档的“阶段三：接口盘点与冒烟测试”。

---

## 一、先读取并遵守现有文件

开始修改前，先检查仓库现状并读取以下文件；文件名可能带有“(1)”后缀：

1. `AGENTS.md`（如存在）
2. `AKShare_量化金融数据任务.txt`
3. `AKShare数据抓取测试_总纲.md`
4. `AKShare数据抓取测试_分阶段操作步骤.md`
5. `docs/stage0_scope.md`
6. `config/universe.yml`
7. `config/metric_definition.yml`
8. 阶段0已有测试文件

阶段0产物是本阶段的只读业务契约。除非文件无法解析且有明确证据表明阶段0验收结论错误，否则不得修改：

- `config/universe.yml`
- `config/metric_definition.yml`
- `docs/stage0_scope.md`
- 阶段0测试中已经冻结的业务断言

开始工作时记录上述三个阶段0核心文件的 SHA-256；完成时再次计算并确认哈希未变化。若当前目录缺少这些文件，不得凭空重建口径，也不得继续进入后续实现；应在最终回复中明确列出缺失项。

---

## 二、本阶段目标

完成一套可复现、可导入、可测试、默认不访问业务网络的 Python 工程环境和项目骨架，使下一阶段可以直接实现 AKShare 接口冒烟测试。

本阶段必须完成：

1. 建立或复用项目虚拟环境。
2. 建立单一、清晰的 Python 依赖来源，并生成实际环境锁定文件。
3. 创建标准项目目录和 Python 包骨架。
4. 实现配置加载、项目路径、日志和最小 CLI 框架。
5. 实现离线 `doctor` 环境检查。
6. 添加自动化测试并实际运行。
7. 生成阶段1环境验收记录。

---

## 三、严格禁止的事项

本阶段不得：

- 调用任何 AKShare 数据接口。
- 抓取股票、财务、资金流、涨跌停或加密货币数据。
- 访问东方财富、新浪、交易所、加密货币交易所或其他财经网站。
- 实现阶段2的接口适配器、抓取器、冒烟测试或真实数据库业务表。
- 创建伪造的 Raw/Clean/Feature 数据。
- 将 ETHUSD 或其他品种改名为 ETHUSDT。
- 修改阶段0已经冻结的分析口径。
- 使用系统当天日期作为业务 `as_of_date` 的静默默认值。
- 把密钥、Cookie、代理地址、个人路径、访问令牌或其他敏感信息写入仓库。
- 自动创建或切换 Git 分支。
- 改写既有 Git 历史。

本阶段允许的网络访问仅限于：安装 Python 包时访问包索引。安装完成后，所有项目命令和测试必须在不访问真实业务网络的条件下运行。

---

## 四、Python 环境要求

### 4.1 解释器

- 优先使用 64 位 CPython 3.12。
- 若系统没有 Python 3.12，可使用已安装的 64 位 CPython 3.9 或更高版本，但必须在阶段报告中记录实际版本和偏差。
- 不要自行安装或升级操作系统级 Python。
- 不要修改全局 Python 环境。
- 若已有 `.venv`，先验证其解释器和依赖；有效则复用，不要无故删除。
- 若没有 `.venv`，在项目根目录创建。

验证位数时使用 Python 本身检查，不要仅根据命令名称推断。

### 4.2 依赖管理

以 `pyproject.toml` 作为直接依赖的单一事实来源。使用 `setuptools` 的 `src` 布局。

运行依赖至少包括：

- `akshare`
- `pandas`
- `numpy`
- `pyarrow`
- `duckdb`
- `sqlalchemy`
- `pydantic`
- `pyyaml`
- `python-dotenv`
- `tenacity`
- `matplotlib`
- `openpyxl`

开发/质量依赖至少包括：

- `pytest`
- `pandera`

不要随意加入 Web 框架、任务队列、Notebook 服务、数据库服务器驱动或大型可视化框架。

安装建议：

```bash
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[dev]"
```

安装成功后，用实际虚拟环境生成：

```bash
python -m pip freeze > requirements-lock.txt
```

不得手工伪造 `requirements-lock.txt`。如果依赖安装因网络、权限或兼容性失败，保留已完成的项目骨架和诊断证据，但必须把阶段状态标为“未完全通过”，并给出原始错误摘要。

---

## 五、目标目录结构

保留现有文件，在项目根目录建立以下最小结构。已有文件应审慎合并，不得粗暴覆盖。

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
├── src/
│   └── akshare_data_test/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── doctor.py
│       ├── logging_config.py
│       ├── paths.py
│       ├── adapters/__init__.py
│       ├── collectors/__init__.py
│       ├── cleaners/__init__.py
│       ├── features/__init__.py
│       ├── storage/__init__.py
│       ├── quality/__init__.py
│       └── utils/__init__.py
├── tests/
│   ├── test_stage0_config.py
│   ├── test_stage1_config_loader.py
│   ├── test_stage1_cli.py
│   ├── test_stage1_doctor.py
│   └── test_stage1_structure.py
└── run_pipeline.py
```

如阶段0测试文件名不同，保留原文件，不要为了匹配示例而重命名。目录中的 `.gitkeep` 只用于保留空目录。

---

## 六、需要实现的最小代码

### 6.1 `src/akshare_data_test/paths.py`

实现可靠的项目路径定义，至少提供：

- 项目根目录
- `config`、`data`、`database`、`logs`、`reports`、`sql` 路径
- `universe.yml` 和 `metric_definition.yml` 路径

要求：

- 不依赖调用命令时的当前工作目录。
- 路径使用 `pathlib.Path`。
- 不在导入模块时创建业务数据文件。

### 6.2 `src/akshare_data_test/config.py`

实现阶段0配置的只读加载和基础验证，至少包括：

- 使用 `yaml.safe_load`。
- 加载 `config/universe.yml`。
- 加载 `config/metric_definition.yml`。
- 对根对象类型、必需字段和日期格式做明确校验。
- 将股票代码始终保留为字符串。
- 提供业务基准日解析：CLI 参数优先，否则读取配置中的基准日。
- 禁止使用 `date.today()`、`datetime.now()` 或系统日期作为业务基准日回退。
- 配置错误应抛出项目自定义异常并包含文件路径和可理解的错误信息。

可使用 Pydantic，也可使用清晰的 dataclass/显式验证；不要在本阶段建立庞大的全量领域模型。

### 6.3 `src/akshare_data_test/logging_config.py`

实现最小日志配置：

- 默认控制台日志。
- 日志级别可通过环境变量或 CLI 指定。
- 可选写入 `logs/`。
- 不记录环境变量全集、密钥、Cookie 或敏感请求信息。
- 重复初始化不得造成处理器重复。

### 6.4 `src/akshare_data_test/doctor.py`

实现完全离线的环境检查，至少检查：

1. Python 版本。
2. 解释器是否为 64 位。
3. 以下包是否可导入，并读取可获得的版本号：
   - AKShare
   - pandas
   - numpy
   - pyarrow
   - DuckDB
   - SQLAlchemy
   - Pydantic
   - PyYAML
   - python-dotenv
   - tenacity
   - matplotlib
   - openpyxl
   - pytest
   - pandera
4. 两个阶段0 YAML 是否能解析。
5. 股票数量是否为16。
6. ETHUSDT 是否仍要求精确匹配并禁止替代。
7. 项目所需目录是否存在且可写。
8. DuckDB 是否可建立内存连接并执行 `SELECT 1`；不得在本阶段创建正式业务表。
9. 业务 `as_of_date` 是否来自 CLI 或配置，而不是系统日期。

结果对象至少包含：

- `status`: `pass` 或 `fail`
- `checked_at`: 仅作为运行元数据，可使用带时区的当前时间
- `python`
- `packages`
- `config_checks`
- `filesystem_checks`
- `duckdb_check`
- `resolved_as_of_date`
- `errors`

区分：运行元数据时间可以使用当前时间；业务基准日绝不能因此改变。

### 6.5 `src/akshare_data_test/cli.py`

使用标准库 `argparse` 实现，不要引入额外 CLI 框架。

至少提供：

#### `doctor`

```bash
python run_pipeline.py doctor --as-of-date 2026-07-27
```

可选参数：

- `--as-of-date YYYY-MM-DD`
- `--output <json路径>`
- `--log-level`

行为：

- 不调用任何 AKShare 数据接口。
- 输出简洁的人类可读摘要。
- 可将完整结果写入 JSON。
- 全部通过时退出码为0；有必需检查失败时退出码非0。

#### `show-config`

```bash
python run_pipeline.py show-config --as-of-date 2026-07-27
```

只输出安全的配置摘要，例如股票数量、股票代码、请求交易对、时区和已解析基准日；不要输出环境变量全集。

### 6.6 `run_pipeline.py`

只作为轻量入口，调用包内 CLI，不复制业务逻辑。

同时在 `pyproject.toml` 中配置一个可选命令行入口，例如：

```bash
akshare-data-test doctor --as-of-date 2026-07-27
```

### 6.7 包目录占位模块

`adapters`、`collectors`、`cleaners`、`features`、`storage`、`quality`、`utils` 在本阶段只建立包和简短职责说明，不实现真实接口调用、抓取、清洗、指标或入库逻辑。

---

## 七、配置和环境文件

### 7.1 `.env.example`

只放非敏感示例，例如：

```dotenv
AKSHARE_LOG_LEVEL=INFO
AKSHARE_AS_OF_DATE=2026-07-27
AKSHARE_DATABASE_PATH=database/akshare_test.duckdb
```

注明真实 `.env` 不得提交。不要添加不存在的 API Key 要求。

### 7.2 `.gitignore`

至少忽略：

- `.venv/`
- `.env`
- Python 缓存和测试缓存
- 构建产物
- 日志文件
- DuckDB 数据库及临时文件
- `data/raw`、`data/clean`、`data/feature`、`data/export` 中的生成数据
- Notebook checkpoint

但保留必要的 `.gitkeep`、配置、文档、源码、测试和阶段报告。

### 7.3 `AGENTS.md`

若已有文件，先遵守并做最小合并；不得删除阶段0规则。若不存在，则创建。

至少写明：

- 一次 Codex 任务只完成一个阶段。
- 阶段0配置是业务契约，后续阶段不得静默改写。
- 业务日期必须来自配置或 CLI。
- 真实网络调用只能位于后续适配器/抓取器层。
- 测试默认禁止真实网络。
- Raw 数据未来必须追加保存且不可覆盖。
- 数据库未来必须幂等写入。
- “主力行为”只能使用“疑似”“特征”“证据不足”等限定表达。
- 修改后必须运行相关测试。
- 不得提交敏感信息。

### 7.4 `README.md`

至少包含：

- 项目目的和当前完成阶段。
- Python/虚拟环境要求。
- 安装命令。
- `doctor` 和 `show-config` 用法。
- 当前目录结构简述。
- 明确说明阶段1不抓取真实数据。
- 下一阶段是接口盘点与冒烟测试。

---

## 八、自动化测试

使用 `pytest`。测试必须离线、确定性强，且不能依赖真实财经网站。

### 8.1 配置加载测试

验证：

- 两个 YAML 正常加载。
- 业务基准日来自配置。
- CLI `as_of_date` 可以覆盖配置值。
- 无效日期格式会给出清晰错误。
- 股票代码仍为字符串。
- 不存在系统日期静默回退。

### 8.2 CLI 测试

验证：

- `--help` 正常。
- `show-config` 退出码为0并返回正确股票数量和交易对。
- `doctor` 能生成 JSON。
- 检查失败时退出码非0。

### 8.3 Doctor 离线测试

在测试中阻断 socket 真实联网能力，然后运行 `doctor` 核心逻辑；必须仍然通过正常检查。不得仅用注释声明“不会联网”。

不要阻断正常的本地文件、模块导入和 DuckDB 内存连接。

### 8.4 目录结构测试

验证：

- 必需目录存在。
- 包可导入。
- `run_pipeline.py` 存在。
- 阶段0核心文件存在。
- 阶段0三个核心文件的内容在任务前后未变化。

### 8.5 阶段越界静态检查

仅扫描本项目源码和测试，不扫描虚拟环境或第三方包。至少确认：

- 没有调用 `ak.stock_...`、`ak.crypto_...` 等真实 AKShare 数据函数。
- 没有 `requests.get/post`、`httpx`、`urllib.request.urlopen` 等业务网络调用。
- 没有创建 Raw/Clean/Feature 示例数据。
- 没有正式数据库业务表 DDL。

允许 `import akshare` 和读取 `akshare.__version__`。

---

## 九、阶段报告

创建 `docs/stage1_environment.md`，至少记录：

1. 阶段目标和范围。
2. 实际操作系统与 Python 版本、位数。
3. 虚拟环境位置（使用相对路径，不写个人主目录）。
4. 依赖安装方法。
5. 核心包实际版本。
6. 项目目录和关键模块说明。
7. 配置加载和日期解析规则。
8. 测试命令与结果。
9. Doctor 命令与结果。
10. 阶段0文件哈希前后是否一致。
11. 偏差、失败项和风险。
12. 下一阶段入口条件。

执行并保存：

```bash
python run_pipeline.py doctor \
  --as-of-date 2026-07-27 \
  --output reports/stage1_environment_check.json
```

JSON 中不得包含个人目录、环境变量全集或敏感数据。

---

## 十、建议执行顺序

1. 检查当前目录、Git 状态和现有指令文件。
2. 读取阶段0文件并记录 SHA-256。
3. 检查可用 Python 解释器和位数。
4. 创建或复用 `.venv`。
5. 创建 `pyproject.toml` 和项目目录骨架。
6. 实现路径、配置、日志、doctor 和 CLI。
7. 安装项目及开发依赖。
8. 生成真实 `requirements-lock.txt`。
9. 编写并运行测试。
10. 运行 `show-config`。
11. 运行 `doctor` 并生成 JSON 报告。
12. 再次计算阶段0文件 SHA-256。
13. 检查 `git diff`，确认没有阶段外修改和生成数据。
14. 编写 `docs/stage1_environment.md`。

不要因为某一步失败就伪造后续成功结果。修复可修复的问题；外部环境导致的问题要留下证据并如实降级验收状态。

---

## 十一、必须实际运行的验收命令

根据操作系统激活虚拟环境后，至少运行：

```bash
python -c "import struct, sys; print(sys.version); print(struct.calcsize('P') * 8)"
python -m pip check
python -m pytest -q
python run_pipeline.py show-config --as-of-date 2026-07-27
python run_pipeline.py doctor --as-of-date 2026-07-27 --output reports/stage1_environment_check.json
```

如果安装了命令行入口，再运行：

```bash
akshare-data-test doctor --as-of-date 2026-07-27
```

不得只给出“建议运行”的命令，必须实际执行并记录退出码和关键结果。

---

## 十二、阶段1验收标准

只有同时满足以下条件，阶段1才算完全通过：

- 阶段0三个核心文件哈希前后完全一致。
- 使用64位 Python 3.9或更高版本，优先3.12。
- `.venv` 可用，且没有污染全局环境。
- `pyproject.toml` 是直接依赖的单一事实来源。
- 依赖安装成功，`requirements-lock.txt` 来自实际环境。
- 所有必需包可导入并记录版本。
- 项目目录和 `src` 包骨架完整。
- 配置加载器可以读取阶段0配置。
- 业务日期仅来自配置或 CLI。
- `show-config` 正常运行。
- 离线 `doctor` 全部通过并生成 JSON。
- `python -m pip check` 通过。
- 全部 pytest 测试通过。
- 测试证明项目命令无需访问真实业务网络。
- 没有调用任何 AKShare 数据接口。
- 没有真实数据、正式业务表或阶段2代码。
- 文档完整记录环境、命令、结果和偏差。

只要依赖安装、`pip check`、pytest 或 doctor 中任一必需项失败，最终状态不得写“完全通过”。

---

## 十三、完成时的回复格式

严格按以下顺序回复：

1. **阶段状态**：完全通过 / 部分完成 / 阻塞
2. **完成摘要**
3. **新增和修改文件**
4. **环境与依赖版本**
5. **实际执行的命令、退出码和结果**
6. **测试结果**
7. **阶段0文件哈希校验结果**
8. **未完成项、偏差或风险**
9. **下一阶段的明确入口条件**
10. 最后一行明确声明：

> 本任务未调用任何 AKShare 数据接口、未抓取真实数据、未创建正式业务表、未进入接口冒烟测试阶段。
