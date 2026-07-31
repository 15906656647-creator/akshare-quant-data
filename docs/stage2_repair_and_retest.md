# 阶段2修复与重新验收报告

> 执行日期：2026-07-29
> 基准业务日期：2026-07-27
> 显式股池日期：2026-07-24
> 范围：仅修复并重新验收阶段2，不进入阶段3

## 1. 修复结论

| 项目 | 结论 |
|---|---|
| 阶段0 | PASS |
| 阶段1 | PASS |
| 阶段2工程 | PASS |
| 网络预检查 | BLOCKED |
| 阶段2真实接口 | BLOCKED |
| 是否允许进入阶段3 | **否** |

阶段2工程缺陷已经修复：显式 `--pool-date` 会使涨停池和跌停池完全
独立于日线探针执行。真实重跑的12个探针对应11个唯一AKShare函数；
12项均已实际调用，没有 `skipped` 或 `dependency_failure`。但运行环境对
全部预检查主机的TCP 443连接均报 `WinError 10013`，真实接口仍无法验证。

## 2. 修复前状态与文件完整性

修复前Git基线：

- 当前分支只有一个提交：`9aea2ed Stage 0: Freeze scope and analysis specifications`
- `AGENTS.md` 已修改；阶段1、阶段2实现和报告大多仍为未跟踪文件
- 修复前 `git diff --stat` 仅显示 `AGENTS.md` 增加11行

阶段0冻结文件修复前完整SHA-256：

| 文件 | SHA-256 |
|---|---|
| `config/universe.yml` | `0B6F61D43E753945B7E7931D27359E34A199891EAC3F7D59F29C9D17EFCCEC65` |
| `config/metric_definition.yml` | `13F9415D3E55AACC91E9913652D6E6520D9C681AC3043F09409602C44B5C00C4` |
| `docs/stage0_scope.md` | `18EEEC59594B2CCA67CFC7E7F137855ED2B1F018C10623E426340188AC761615` |

附件要求读取的以下文件不存在，未补造：

- `CODEX_STAGE0_PROMPT.md`
- `docs/stage0_2_codex_audit.md`
- `reports/stage0_2_codex_audit.json`

## 3. 阶段1前置门禁

| 命令 | 退出码 | 结果 |
|---|---:|---|
| `.venv\Scripts\python.exe -m pip check` | 0 | 无依赖冲突 |
| `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`（修复前） | 0 | 86 passed |
| `.venv\Scripts\python.exe run_pipeline.py show-config --as-of-date 2026-07-27` | 0 | 16只股票、ETHUSDT、业务日期正确 |
| `.venv\Scripts\python.exe run_pipeline.py doctor --as-of-date 2026-07-27 --output reports/stage2_repair_doctor.json` | 0 | PASS |

项目解释器为 `.venv\Scripts\python.exe`，Python 3.11.4、64位。未使用全局
Python冒充项目环境。

## 4. 修改内容

| 文件 | 修改原因 | 修改内容 | 验证结果 |
|---|---|---|---|
| `src/akshare_data_test/adapters/akshare_probe.py` | 错误证据和重试信息不足 | 增加根异常、目标主机、HTTP状态码、代理存在标记、重试原因、股池日期来源、样本证据；每接口最多重试一次 | 离线测试及真实CSV通过 |
| `src/akshare_data_test/smoke.py` | 股池错误依赖前复权日线 | 改为CLI日期优先，其次成功的不复权日线；写入样本、Schema及增强manifest | 两个股池独立执行 |
| `src/akshare_data_test/cli.py` | `--pool-date` 未严格验证 | 严格接受 `YYYY-MM-DD`；新增 `network-check` | 非法日期退出码2 |
| `src/akshare_data_test/network_preflight.py` | 缺少独立网络层诊断 | 并行检查DNS、TCP 443、TLS；只记录代理/CA变量是否存在 | 生成JSON和Markdown |
| `tests/test_stage2_repair.py` | 缺少修复回归测试 | 新增19项纯离线测试 | 完整pytest 105 passed |
| `README.md` | 当前阶段说明滞后 | 更新为阶段2工程完成、真实接口阻塞 | 与复验结论一致 |
| `docs/stage2_interface_smoke.md` | “12个函数”表述不精确 | 统一为“12个探针对应11个唯一AKShare函数” | 表述已纠正 |

## 5. 网络预检查

命令：

```text
.venv\Scripts\python.exe run_pipeline.py network-check
  --timeout 5
  --output reports/stage2_network_preflight.json
  --markdown-output docs/stage2_network_preflight.md
```

退出码为1，整体状态为 `BLOCKED`。未检测到HTTP/HTTPS/ALL代理环境变量，
也未检测到 `REQUESTS_CA_BUNDLE` 或 `SSL_CERT_FILE`。只记录了变量存在性，
没有记录变量值。

| host | DNS | TCP 443 | TLS | error_type |
|---|---|---|---|---|
| `push2his.eastmoney.com` | pass | fail | not_tested | connection_error |
| `push2.eastmoney.com` | pass | fail | not_tested | connection_error |
| `quotes.sina.cn` | pass | fail | not_tested | connection_error |
| `money.finance.sina.com.cn` | pass | fail | not_tested | connection_error |
| `emweb.securities.eastmoney.com` | pass | fail | not_tested | connection_error |
| `datacenter-api.jin10.com` | pass | fail | not_tested | connection_error |

所有TCP失败的根异常均为 `PermissionError`，消息为Windows套接字访问权限错误
`WinError 10013`。因此失败层级明确位于DNS之后、TLS之前。

## 6. 修复后测试

| 命令 | 退出码 | 结果 |
|---|---:|---|
| `.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider` | 0 | **105 passed** |
| `.venv\Scripts\python.exe run_pipeline.py smoke-test --help` | 0 | 显示 `--pool-date` |
| `.venv\Scripts\python.exe run_pipeline.py smoke-test --pool-date 2026-02-30 --only limit_up_pool` | 2 | 非法日期被拒绝 |

当前项目未配置Ruff，因此没有伪造Ruff检查结果。所有新增网络测试均使用mock，
普通pytest没有访问真实财经站点。

## 7. 12项真实冒烟测试

执行命令：

```text
.venv\Scripts\python.exe run_pipeline.py smoke-test
  --as-of-date 2026-07-27
  --pool-date 2026-07-24
  --sample-symbol 600763
  --output reports/interface_smoke_test_repaired.csv
  --evidence-dir reports/evidence/stage2-repaired
  --max-sample-rows 20
```

运行ID：`1033978f-9a42-405a-af86-67560de9ac55`
退出码：1
整体状态：`BLOCKED`

| probe_id | status | error_type | rows | cols | attempts | pool_date | source | target_host |
|---|---|---|---:|---:|---:|---|---|---|
| stock_daily_qfq | failed | connection_error | - | - | 2 | - | - | push2his.eastmoney.com |
| stock_daily_raw | failed | connection_error | - | - | 2 | - | - | push2his.eastmoney.com |
| stock_spot | failed | connection_error | - | - | 2 | - | - | 82.push2.eastmoney.com |
| financial_abstract | failed | connection_error | - | - | 2 | - | - | quotes.sina.cn |
| financial_indicator | failed | connection_error | - | - | 2 | - | - | money.finance.sina.com.cn |
| balance_sheet_report | failed | connection_error | - | - | 2 | - | - | emweb.securities.eastmoney.com |
| profit_sheet_report | failed | connection_error | - | - | 2 | - | - | emweb.securities.eastmoney.com |
| cashflow_sheet_report | failed | connection_error | - | - | 2 | - | - | emweb.securities.eastmoney.com |
| individual_fund_flow | failed | connection_error | - | - | 2 | - | - | push2his.eastmoney.com |
| limit_up_pool | failed | connection_error | - | - | 2 | 2026-07-24 | cli | push2ex.eastmoney.com |
| limit_down_pool | failed | connection_error | - | - | 2 | 2026-07-24 | cli | push2ex.eastmoney.com |
| crypto_spot | failed | connection_error | - | - | 2 | - | - | datacenter-api.jin10.com |

每个失败结果均记录：

- `exception_class=ConnectionError`
- `root_exception_class=PermissionError`
- 单行截断并脱敏的外层和根错误消息
- 实际目标主机
- `attempt_count=2`
- `retry_reason=connection_error`
- `proxy_detected=false`
- 未收到HTTP响应，因此 `http_status_code` 为空

没有成功结果，因此不存在可合法生成的行数、Schema哈希或样本数据。未将函数存在、
空结果或失败伪装为成功。`crypto_js_spot` 未完成真实调用验证，所以
`ETHUSDT capability = UNVERIFIED`。

## 8. 股池探针修复结论

- `--pool-date 2026-07-24`：可用，并严格校验日期。
- 日期优先级：CLI → 成功的不复权日线 → unresolved。
- 日线失败时两个股池是否独立执行：**是**。
- 修复后是否仍存在股池 `dependency_failure`：**否**。
- 修复前：两个股池均为 `skipped/dependency_failure`，尝试次数0。
- 修复后：两个股池均为 `failed/connection_error`，尝试次数2，说明真实调用
  和一次重试均已发生。

## 9. 根因分类

| 类别 | 结论 |
|---|---|
| 代码问题 | 已发现并修复股池日期依赖、日期验证和错误证据不足 |
| DNS问题 | 未发现；6个预检查主机均解析成功 |
| TCP/防火墙问题 | **发现**；全部TCP 443连接因WinError 10013失败 |
| TLS问题 | 未能测试；TCP连接未建立 |
| 代理问题 | 未发现相关环境变量；不能排除系统级网络策略 |
| 上游或AKShare解析问题 | 未能测试；请求尚未到达HTTP/解析层 |

## 10. Git整理建议

当前仍存在大量未跟踪的重要文件。不要把全部内容作为一个不可审查的提交。
建议拆分：

1. `chore(audit): checkpoint validated stages 0 and 1`
2. `fix(stage2): decouple limit pool probes and add network diagnostics`
3. `docs(stage2): record repaired smoke-test evidence`

建议提交：`config/`、`src/`、`tests/`、`docs/`、`pyproject.toml`、
`requirements-lock.txt`、`run_pipeline.py`、小型CSV、JSON、Markdown和manifest。

继续忽略：`.venv/`、`.env`、日志、缓存、正式Raw数据、数据库临时文件、
代理配置、Cookie和凭据。本任务没有自动执行 `git commit`，也没有改写历史。

## 11. 阶段3入口结论

核心行情成功数为0/3，财务接口成功数为0/5，不满足阶段3入口条件。

> 阶段2工程修复已经完成，但当前运行环境仍无法访问AKShare上游数据源，真实接口能力仍为BLOCKED，禁止进入阶段3。请在DNS、TCP 443、TLS和代理预检查均通过的网络环境中，使用相同参数重新执行阶段2冒烟测试。
