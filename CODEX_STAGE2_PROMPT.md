# Codex 任务：阶段2——接口盘点与冒烟测试

你正在当前 AKShare 数据抓取测试项目的根目录中工作。阶段0应已冻结业务范围，阶段1应已完成环境与项目骨架。本任务只完成“阶段2：接口盘点与冒烟测试”。

> 范围映射说明：本任务对应《AKShare数据抓取测试_分阶段操作步骤》中的“阶段三：接口盘点与冒烟测试”。不得进入后续的批量抓取、生产级重试与限速、Raw 数据正式落地、清洗、数据库、指标或分析阶段。

---

## 一、执行前必须读取的文件

开始修改前，先检查仓库现状并完整读取以下文件；文件名可能带有“(1)”后缀：

1. `AGENTS.md`
2. `AKShare_量化金融数据任务.txt`
3. `AKShare数据抓取测试_总纲.md`
4. `AKShare数据抓取测试_分阶段操作步骤.md`
5. `docs/stage0_scope.md`
6. `docs/stage1_environment.md`
7. `config/universe.yml`
8. `config/metric_definition.yml`
9. `pyproject.toml`
10. `requirements-lock.txt`
11. `reports/stage1_environment_check.json`
12. 阶段0和阶段1已有测试
13. 当前源码、README 和 CLI 实现

阶段0的以下文件继续作为只读业务契约：

- `config/universe.yml`
- `config/metric_definition.yml`
- `docs/stage0_scope.md`
- 阶段0测试中已冻结的业务断言

除非阶段1本身存在明确缺陷，否则不要重构阶段1的路径、配置、日志、doctor 或 CLI 基础代码。

---

## 二、阶段1前置验收门禁

在创建或修改任何阶段2业务文件前，必须先实际执行阶段1验收检查。

至少运行：

```bash
python -c "import struct, sys; print(sys.version); print(struct.calcsize('P') * 8)"
python -m pip check
python -m pytest -q
python run_pipeline.py show-config --as-of-date 2026-07-27
python run_pipeline.py doctor \
  --as-of-date 2026-07-27 \
  --output reports/stage1_environment_check.json
```

同时检查：

1. Python 为64位且版本不低于3.9。
2. 当前解释器来自项目 `.venv`，没有误用全局环境。
3. `pyproject.toml` 是直接依赖的单一事实来源。
4. `requirements-lock.txt` 非空，且来自实际安装环境。
5. `reports/stage1_environment_check.json` 存在，顶层状态为通过。
6. `python -m pip check` 退出码为0。
7. 全部离线 pytest 退出码为0。
8. `show-config` 正常输出16只股票、`ETHUSDT`、时区和业务基准日。
9. 阶段0三个核心文件当前 SHA-256 与 `docs/stage1_environment.md` 中记录的完成时哈希一致。
10. 阶段1没有遗留真实抓取代码、正式业务表或伪造数据。

### 硬停止规则

以下任一情况发生时：

- `pip check` 失败；
- pytest 失败；
- doctor 失败；
- 必需依赖缺失；
- 阶段0文件哈希异常；
- 阶段1报告或环境检查文件缺失；
- 当前解释器不满足版本或位数要求；

则本任务状态必须为 `BLOCKED`，不得调用任何 AKShare 数据接口，不得创建伪造的阶段2结果。只输出阻塞证据和阶段1修复建议。

不要通过跳过测试、降低断言、删除失败测试或修改阶段0口径来绕过门禁。

---

## 三、本阶段目标

使用小数据量和单只代表性股票，验证候选 AKShare 接口在当前已锁定环境中的真实可用性、实际函数签名、参数要求、返回字段、数据类型、时间覆盖、空结果和错误类型，形成后续抓取开发的事实依据。

本阶段的核心成果是：

1. 一份机器可读的接口定义配置。
2. 一个最小、可复用但非生产级的接口探测器。
3. 每个候选接口的一条结构化冒烟测试记录。
4. 字段和类型的 Schema 快照。
5. 少量、可审计的测试证据样本。
6. 接口能力矩阵、失败记录和限制说明。
7. 离线、可重复的单元测试。

本阶段不是完整数据抓取阶段。不要对16只股票逐只抓取。

---

## 四、严格禁止的事项

本阶段不得：

- 对16只股票逐只执行历史行情、财务或资金流批量抓取。
- 实现生产级抓取器、任务调度器、并发抓取或复杂重试框架。
- 将冒烟测试证据写入正式 `data/raw`、`data/clean`、`data/feature`。
- 创建正式业务数据库表或 DuckDB 文件。
- 清洗、重命名或删除财务报表原始字段。
- 计算均线、活跃度、涨跌停年度统计、横盘风格或基本面指标。
- 使用当前实时估值回填历史数据。
- 将近期涨跌停池当作全年历史事件来源。
- 将 ETHUSD、ETH/EUR 或其他 ETH 品种改名为 `ETHUSDT`。
- 接入 Binance、OKX、CCXT 或任何非 AKShare 数据源。
- 自动升级或降级 AKShare、Python 或其他依赖。
- 修改阶段0冻结的测试范围和指标口径。
- 使用系统当天日期静默替代业务 `as_of_date`。
- 把空 DataFrame、部分字段或异常结果标记为成功。
- 将网络不可用伪装成接口不支持。
- 把接口不支持伪装成网络故障。
- 提交 Cookie、代理、令牌、个人目录或其他敏感信息。
- 创建或切换 Git 分支，或改写既有 Git 历史。

本阶段允许真实业务网络访问，但只能由显式执行的 `smoke-test` 命令发起。默认 pytest、doctor 和 show-config 必须继续保持离线。

---

## 五、运行事实优先原则

AKShare 接口依赖外部网页，接口签名和返回字段可能随版本或上游变化。必须遵守：

1. 记录当前虚拟环境的实际 AKShare 版本。
2. 对每个候选函数使用 `hasattr`、`getattr` 和 `inspect.signature` 记录实际存在性与函数签名。
3. 运行时函数签名和真实返回结果优先于规划文档中的示例。
4. 如果函数不存在，记录为 `unsupported`，不要自动升级依赖。
5. 如果文档参数与运行时签名不一致，按运行时签名做最小调整，并记录差异。
6. 不得仅凭文档示例写成“测试成功”；成功必须来自真实调用。
7. 不得假设列顺序、列数量或类型长期不变。

---

## 六、固定测试对象与日期规则

### 6.1 代表性股票

本阶段个股接口只测试：

```text
600763
```

对应：

```text
symbol_plain = 600763
symbol_em = SH600763
market_lower = sh
```

上述映射必须从 `config/universe.yml` 读取和验证，不能在业务代码中散落硬编码拼接规则。

### 6.2 全市场接口

`stock_zh_a_spot_em()` 只允许调用一次，然后筛选阶段0配置中的16只股票。不得按股票循环调用全市场接口。

涨停池、跌停池同样是全市场日期接口，每个日期和接口只调用一次，再筛选16只股票。

### 6.3 历史行情冒烟区间

- `as_of_date` 必须来自 CLI 或阶段0配置。
- 冒烟测试历史区间使用基准日前90个自然日至基准日。
- 实际调用时转换为 `YYYYMMDD`。
- 该短区间只用于接口探测，不改变阶段0规定的正式三年日线范围。

### 6.4 实时接口时间

`stock_zh_a_spot_em` 和 `crypto_js_spot` 返回执行时点快照。必须保存实际抓取时间，不得把快照时间写成业务 `as_of_date`，也不得宣称它是历史快照。

### 6.5 涨跌停池日期

优先从成功返回的 `stock_zh_a_hist` 不复权日线中，选择不晚于 `as_of_date` 的最大交易日期，作为涨停池和跌停池的探测日期。

如果无法从日线得到交易日期：

- 可以使用用户通过 CLI 显式提供的 `--pool-date YYYY-MM-DD`；
- 若没有显式参数，则两个股池探测记录为 `skipped`，错误类型为 `dependency_failure`；
- 不得静默使用系统当天日期；
- 不得把无数据解释为“当日0只涨停或跌停”。

---

## 七、候选接口清单

必须为以下探测项各生成一条结果记录：

1. `stock_daily_qfq`
   - 函数：`stock_zh_a_hist`
   - 股票：`600763`
   - `period="daily"`
   - `adjust="qfq"`
   - 短区间

2. `stock_daily_raw`
   - 函数：`stock_zh_a_hist`
   - 股票：`600763`
   - `period="daily"`
   - `adjust=""`
   - 短区间

3. `stock_spot`
   - 函数：`stock_zh_a_spot_em`
   - 全市场仅调用一次
   - 结果筛选16只测试股票

4. `financial_abstract`
   - 函数：`stock_financial_abstract`
   - `symbol="600763"`

5. `financial_indicator`
   - 函数：`stock_financial_analysis_indicator`
   - `symbol="600763"`
   - `start_year` 为基准年向前5年，例如基准日为2026年时使用 `2021`

6. `balance_sheet_report`
   - 函数：`stock_balance_sheet_by_report_em`
   - `symbol="SH600763"`

7. `profit_sheet_report`
   - 函数：`stock_profit_sheet_by_report_em`
   - `symbol="SH600763"`

8. `cashflow_sheet_report`
   - 函数：`stock_cash_flow_sheet_by_report_em`
   - `symbol="SH600763"`

9. `individual_fund_flow`
   - 函数：`stock_individual_fund_flow`
   - `stock="600763"`
   - `market="sh"`

10. `limit_up_pool`
    - 函数：`stock_zt_pool_em`
    - 使用显式解析出的股池日期
    - 全市场仅调用一次
    - 筛选16只测试股票

11. `limit_down_pool`
    - 函数：`stock_zt_pool_dtgc_em`
    - 使用显式解析出的股池日期
    - 全市场仅调用一次
    - 筛选16只测试股票

12. `crypto_spot`
    - 函数：`crypto_js_spot`
    - 单次调用
    - 保存真实市场和真实交易品种
    - 只做 `ETHUSDT` 初步能力判定

不要在本阶段随意扩大接口清单。若运行时发现某函数已经不存在，可以记录替代候选名称，但不得在未说明的情况下改用其他数据源。

---

## 八、必须创建或完善的文件

在遵守现有 `src` 布局的前提下，至少创建或修改：

```text
config/interfaces.yml
src/akshare_data_test/adapters/akshare_probe.py
src/akshare_data_test/smoke.py
src/akshare_data_test/cli.py
run_pipeline.py                         # 仅在需要注册子命令时最小修改
tests/test_stage2_interface_config.py
tests/test_stage2_smoke_runner.py
tests/test_stage2_cli.py
docs/stage2_interface_smoke.md
reports/interface_smoke_test.csv
reports/interface_smoke_test_summary.md
reports/evidence/stage2/<run_id>/manifest.json
logs/stage2_smoke_test.log              # 运行后生成并由 gitignore 忽略
```

可以增加少量职责清晰的辅助模块，但不得引入大型框架或扩展到后续阶段。

### 8.1 `config/interfaces.yml`

至少包含：

- `schema_version`
- 接口探测版本
- 代表性股票配置引用或 ID
- 日期策略
- 样本行数上限
- 候选接口列表

每个接口至少包含：

- `probe_id`
- `interface_name`
- `category`
- `enabled`
- `scope`: `single_symbol` / `full_market` / `single_call`
- `symbol_format`: `plain` / `em` / `market_split` / `none`
- `parameter_policy`
- `expected_columns`
- `required_columns`
- `notes`

`expected_columns` 用于记录文档预期，`required_columns` 仅放调用成功后最基本的必要字段。不得因为新增列而失败；缺少必要列时应记录 `schema_mismatch`。

### 8.2 `akshare_probe.py`

实现最小探测客户端，职责仅包括：

- 延迟导入 `akshare`；
- 检查函数是否存在；
- 读取函数签名；
- 使用显式参数调用函数；
- 返回原始 DataFrame 或结构化异常；
- 不做业务清洗；
- 不创建数据库；
- 不在导入模块时访问网络。

所有真实 AKShare 调用必须集中在适配器/探测器层，CLI 和报告层不得散落直接调用。

### 8.3 `smoke.py`

实现冒烟测试编排和结果记录。要求：

- 顺序执行，不并发；
- 单个接口失败后继续其他接口；
- 记录每次尝试的开始、结束、耗时和尝试次数；
- 初次调用加最多一次仅针对超时、连接中断或明确限流的重试；
- 非瞬时错误不得重试；
- 重试等待固定2秒即可，不实现阶段4的完整指数退避；
- 空 DataFrame 与异常严格区分；
- 全市场接口只调用一次；
- 样本证据与完整行数、完整 Schema 分开记录；
- 不修改原始返回 DataFrame 的字段名和数值；
- 可以复制后筛选证据样本，但必须说明筛选规则。

### 8.4 CLI

在现有 CLI 中新增显式子命令：

```bash
python run_pipeline.py smoke-test \
  --as-of-date 2026-07-27 \
  --sample-symbol 600763 \
  --output reports/interface_smoke_test.csv \
  --evidence-dir reports/evidence/stage2
```

至少支持：

- `--as-of-date YYYY-MM-DD`
- `--sample-symbol`
- `--pool-date YYYY-MM-DD`，可选
- `--output`
- `--evidence-dir`
- `--max-sample-rows`，默认20
- `--only`，可选，逗号分隔探测 ID，用于重跑失败项
- `--log-level`

行为要求：

- 只有该命令允许真实业务网络。
- 输出人类可读进度和最终摘要。
- 逐接口失败时继续执行并写入结果。
- 配置错误、无法初始化运行或无法写报告时退出码非0。
- 若报告成功生成但部分接口失败，命令可以退出0，同时报告中的阶段状态必须准确为 `PASS`、`PARTIAL` 或 `BLOCKED`。
- 提供可选 `--strict`；严格模式下未满足核心通过条件时退出码非0。

---

## 九、结构化结果格式

`reports/interface_smoke_test.csv` 每个探测项一行，至少包含：

```text
run_id
probe_id
category
interface_name
function_exists
function_signature
parameters_json
started_at
finished_at
elapsed_seconds
attempt_count
akshare_version
status
capability_result
row_count
column_count
schema_hash
columns_json
dtypes_json
required_columns_present
missing_required_columns_json
coverage_start
coverage_end
sample_path
error_type
error_message
notes
```

### 9.1 状态定义

`status` 只能使用：

- `success`：调用成功、返回非空 DataFrame，且必要字段存在；
- `empty`：调用成功但返回空 DataFrame；
- `failed`：调用抛出异常，或返回值不是预期结构；
- `unsupported`：当前安装版本不存在该函数；
- `skipped`：依赖条件不满足，例如无法解析股池日期。

不得把 `empty`、`failed`、`unsupported` 或 `skipped` 写成 `success`。

### 9.2 错误类型

尽量归类为：

- `dns_error`
- `connection_error`
- `timeout`
- `ssl_error`
- `http_error`
- `rate_limit`
- `invalid_parameter`
- `upstream_format_error`
- `schema_mismatch`
- `empty_result`
- `dependency_failure`
- `function_missing`
- `unexpected_return_type`
- `unknown_error`

CSV 中的错误信息使用单行、截断和脱敏摘要；完整堆栈写入日志。

### 9.3 Schema 哈希

使用有序列名和对应 dtype 生成稳定 SHA-256，例如对以下 JSON 的 UTF-8 编码计算哈希：

```json
[
  {"name": "日期", "dtype": "object"},
  {"name": "股票代码", "dtype": "object"}
]
```

保留列顺序，不要排序列名。空结果也应记录实际列结构；没有 DataFrame 时 Schema 哈希留空。

### 9.4 时间与覆盖范围

- `started_at`、`finished_at` 使用带时区的运行元数据时间。
- 对能识别日期列的数据，记录最早和最晚日期。
- 无法可靠识别日期列时留空并说明，不要猜测。
- 实时快照不填写伪造的历史覆盖范围。

---

## 十、证据文件规则

在：

```text
reports/evidence/stage2/<run_id>/
```

生成：

1. `manifest.json`
2. 每个探测项的 `*.schema.json`
3. 每个成功或空结果的 `*.sample.csv` 或 `*.sample.json`
4. 必要时的安全参数快照

要求：

- 证据目录不是正式 Raw 层。
- 单个样本最多保存 `--max-sample-rows` 行。
- 对全市场接口保存筛选后的16只股票行，或最多20行代表性样本；同时在记录中保留原始全市场总行数。
- 对财务宽表保留所有列，但样本行数可以限制。
- 不清洗、不翻译、不删除原始列。
- 不保存 Cookie、请求头、代理、个人路径或环境变量全集。
- `sample_path` 使用项目相对路径。
- JSON 必须可解析，CSV 使用 UTF-8 with BOM 或明确 UTF-8，保证中文字段可读。

`manifest.json` 至少包含：

- `run_id`
- `created_at`
- `as_of_date`
- `sample_symbol`
- `pool_date`
- `python_version`
- `akshare_version`
- `git_commit`，如可获取
- `result_csv`
- `probe_count`
- 各状态数量
- 证据文件清单和 SHA-256

---

## 十一、各接口的具体判定规则

### 11.1 `stock_zh_a_hist`

分别测试 `qfq` 和不复权。

至少验证：

- 返回值是 DataFrame；
- 非空；
- 股票代码保持六位字符串；
- 至少包含：日期、股票代码、开盘、收盘、最高、最低、成交量、成交额；
- 记录额外字段，不因为新增列失败；
- 记录日期范围；
- 不在本阶段执行清洗或单位转换。

`qfq` 和不复权必须是两个独立探测记录，不能用一次结果冒充两种口径。

### 11.2 `stock_zh_a_spot_em`

- 全市场只调用一次；
- 记录全市场原始总行数和完整 Schema；
- 筛选16只测试股票作为证据；
- 代码列必须按字符串并补齐六位后再匹配，但证据中保留原始返回值；
- 至少检查：代码、名称、最新价、成交额、换手率、市盈率-动态、市净率；
- 某个估值字段为空不代表整个接口失败，应在说明中记录缺失率；
- 明确这是执行时点快照。

### 11.3 财务关键指标和三大报表

- 每个接口单独调用；
- 保存完整原始字段 Schema；
- 不做转置、字段映射、累计转单季或金额单位转换；
- 记录报告期相关列是否可识别；
- 超宽表不能因为展示方便而删列；
- 若同一函数在当前版本返回结构与文档不同，记录实际结构。

### 11.4 个股资金流

- 记录实际最早、最晚日期和行数；
- 不假设固定100行；
- 若返回约近100个交易日，只作为实际覆盖说明；
- 不将“主力净流入”解释为确定性主力行为。

### 11.5 涨停池和跌停池

- 使用同一个显式股池日期；
- 两个接口分别调用一次；
- 记录全市场行数和16只股票筛选结果；
- 空结果必须区分：真实空表、非交易日、上游无数据或调用失败；若无法区分，写明“不确定”，不能写成0只；
- 明确其只能作为近期交叉验证来源，不能支撑全年事件统计。

### 11.6 `crypto_js_spot`

调用成功后：

1. 保存真实“市场”和“交易品种”字段。
2. 对交易品种做大小写统一和仅移除 `/`、`-`、`_` 的规范化匹配。
3. 初步结论写入 `capability_result`：
   - 精确或规范化后等于 `ETHUSDT`：`success`
   - 存在 ETH 但不是 USDT 计价：`partial_success`
   - 没有 ETH：`unsupported`
4. 不允许把近似币对复制或重命名为 `ETHUSDT`。
5. 只验证实时行情；本阶段不声称存在历史 K 线。
6. 若接口调用失败，`status=failed`，`capability_result` 留空或 `unknown`，不得写成 `unsupported`。

---

## 十二、离线自动化测试

默认 pytest 必须完全离线。使用 monkeypatch、fake AKShare 模块和小型 DataFrame fixture 测试，不调用真实网站。

至少测试：

1. `config/interfaces.yml` 可解析，12个探测 ID 齐全且唯一。
2. 所有配置函数名非空、作用域合法、必要字段格式正确。
3. 探测器导入模块时不访问网络。
4. 函数不存在时返回 `unsupported`。
5. 非空 DataFrame 正确记录为 `success`。
6. 空 DataFrame 正确记录为 `empty`。
7. 异常正确记录为 `failed`，并保留错误类型。
8. 必要列缺失时记录 `schema_mismatch`。
9. Schema 哈希对相同列和 dtype 稳定，对列顺序变化敏感。
10. 样本行数不超过配置上限。
11. 全市场 spot 在一次运行中只调用一次。
12. 涨停池和跌停池各只调用一次。
13. 一个接口失败不阻止其他接口生成记录。
14. 股池日期无法解析时状态为 `skipped`，而不是伪造结果。
15. `ETHUSD` 只能得到 `partial_success`，不能得到 `success`。
16. 网络异常不能被归类为接口 `unsupported`。
17. CLI `smoke-test --help` 正常。
18. CLI 在 fake client 下能生成 CSV、summary 和 manifest。
19. `--only` 只执行指定探测项。
20. 默认 pytest 中阻断 socket 后，全部单元测试仍通过。

真实网络冒烟测试不得作为默认 pytest 测试。若创建 integration test，必须显式标记，例如 `network` 或 `integration`，且默认不运行。

---

## 十三、报告要求

### 13.1 `reports/interface_smoke_test_summary.md`

至少包括：

1. 运行 ID、运行时间、业务基准日、代表股票和股池日期。
2. Python、AKShare、pandas 版本。
3. 接口总数及各状态数量。
4. 按类别列出的能力矩阵。
5. 每个接口的实际函数签名。
6. 返回行数、列数、日期范围和 Schema 哈希。
7. 必要列缺失和字段漂移说明。
8. 网络、限流、参数、空结果和上游格式错误清单。
9. `ETHUSDT` 初步能力结论及证据路径。
10. 全市场接口只调用一次的说明。
11. 实时快照与历史数据的时间口径区别。
12. 哪些结果足以进入阶段3，哪些仍需修复或复测。

### 13.2 `docs/stage2_interface_smoke.md`

至少记录：

1. 阶段目标、范围和非目标。
2. 阶段1前置门禁结果。
3. 实际实现文件和架构说明。
4. 接口探测策略。
5. 实际执行命令、退出码和运行时间。
6. 接口结果摘要。
7. 失败、空结果、Schema 差异和外部风险。
8. 阶段0文件哈希是否保持一致。
9. 阶段1核心环境文件是否被不必要修改。
10. 阶段状态判定。
11. 进入阶段3的明确条件。

---

## 十四、阶段状态判定

### `PASS`

只有同时满足以下条件，阶段2才可标记为 `PASS`：

- 阶段1前置门禁全部通过；
- 阶段0三个核心文件未变化；
- 默认离线 pytest 全部通过；
- `smoke-test` 完成并生成可解析的 CSV、summary 和 manifest；
- 12个探测项都有明确记录；
- `stock_daily_qfq` 和 `stock_daily_raw` 均为 `success`；
- `stock_spot` 为 `success`；
- 至少一个财务类接口为 `success`；
- 所有失败、空结果、unsupported 和 skipped 均有真实证据和原因；
- 没有批量抓取16只股票；
- 没有写入正式 Raw、Clean、Feature 或业务数据库；
- 没有伪造 ETHUSDT 或投资结论。

资金流、涨跌停池或加密货币接口出现真实且有证据的失败、空结果或不支持，不必自动导致整个阶段失败，因为本阶段目标是形成能力矩阵；但必须在报告中突出显示，并判断是否阻塞后续对应模块。

### `PARTIAL`

满足以下任一情况时标记为 `PARTIAL`：

- 报告和测试完成，但 qfq、raw、spot 或财务核心条件未全部满足；
- 网络间歇性故障导致部分核心接口无可靠结论；
- Schema 或参数问题尚未解决，但已有可复现证据；
- 12个探测项中存在未执行且非合理 dependency skip 的项目。

`PARTIAL` 不得直接进入阶段3的完整行情抓取。应先只修复或复测阶段2。

### `BLOCKED`

满足以下任一情况时标记为 `BLOCKED`：

- 阶段1前置门禁失败；
- 运行环境完全无法访问 AKShare 上游；
- 无法导入 AKShare；
- 无法生成结果文件；
- 默认离线测试失败；
- 阶段0契约文件哈希异常。

---

## 十五、建议执行顺序

1. 阅读所有项目约束和阶段报告。
2. 执行阶段1前置门禁。
3. 记录阶段0核心文件 SHA-256。
4. 检查 Git 状态、当前解释器和已安装 AKShare 版本。
5. 创建 `config/interfaces.yml`。
6. 实现最小探测适配器、结果模型和编排器。
7. 扩展 CLI 的 `smoke-test` 子命令。
8. 编写离线单元测试。
9. 运行全部离线测试。
10. 首次真实执行完整12项冒烟测试。
11. 只对明确的瞬时网络失败进行最多一次重试或使用 `--only` 复测。
12. 生成 CSV、证据 manifest 和 Markdown summary。
13. 检查结果文件可解析、路径存在、行数等于12。
14. 再次运行默认 pytest，确保真实运行没有污染离线测试。
15. 再次计算阶段0核心文件 SHA-256。
16. 检查 `git diff`，确认没有阶段外代码、正式 Raw 或数据库产物。
17. 编写 `docs/stage2_interface_smoke.md`。
18. 按状态规则判定 `PASS`、`PARTIAL` 或 `BLOCKED`。

---

## 十六、必须实际运行的命令

在项目 `.venv` 中至少实际运行：

```bash
python -m pip check
python -m pytest -q
python run_pipeline.py doctor \
  --as-of-date 2026-07-27 \
  --output reports/stage1_environment_check.json
python run_pipeline.py smoke-test \
  --as-of-date 2026-07-27 \
  --sample-symbol 600763 \
  --output reports/interface_smoke_test.csv \
  --evidence-dir reports/evidence/stage2 \
  --max-sample-rows 20
python -m pytest -q
```

如果项目已配置代码质量工具，还应运行其现有命令，例如：

```bash
python -m ruff check .
python -m ruff format --check .
```

如果完整运行中某个接口失败，可使用：

```bash
python run_pipeline.py smoke-test \
  --as-of-date 2026-07-27 \
  --sample-symbol 600763 \
  --only <probe_id> \
  --output reports/interface_smoke_test_retry.csv \
  --evidence-dir reports/evidence/stage2-retry
```

不得只写“建议运行”，必须实际执行并记录命令、退出码、持续时间和关键结果。

---

## 十七、完成时的回复格式

严格按以下顺序回复：

1. **阶段状态**：`PASS` / `PARTIAL` / `BLOCKED`
2. **阶段1前置门禁结果**
3. **完成摘要**
4. **新增和修改文件**
5. **运行环境和实际 AKShare 版本**
6. **实际执行命令、退出码和持续时间**
7. **离线测试和代码质量结果**
8. **接口能力矩阵**
9. **成功、空结果、失败、unsupported、skipped 的数量**
10. **每个失败项的原因与证据路径**
11. **Schema、日期覆盖和字段差异摘要**
12. **ETHUSDT 初步能力结论**
13. **阶段0文件哈希校验结果**
14. **阶段外修改检查**
15. **进入阶段3的明确条件**
16. 最后一行明确声明：

> 本任务只完成接口盘点与小样本冒烟测试；未批量抓取16只股票、未写入正式 Raw/Clean/Feature 数据、未创建业务数据库、未计算指标或分析结果、未接入非 AKShare 数据源。
