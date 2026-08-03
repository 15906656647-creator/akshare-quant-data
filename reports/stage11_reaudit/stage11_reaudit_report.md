# Stage 11 第二轮独立验收报告

## 结论

**FAIL**。正常 960 行 ETH-USDT 链路、回归、Stage 10 隔离、validate-only 只读性和旧库拒绝均通过，但 Raw manifest 的必需文件清单门禁存在关键漏检；强制故障未全部阻断，不能判定 PASS。

## 关键失败

生产入口 `validate_raw_evidence` 只遍历 `manifest.evidence_files` 中已有的条目，没有要求该清单恰好包含 `request.json`、`response.json`、`metadata.json` 且各一次。临时副本实测：从清单移除 `metadata.json` 后返回 `READY`，重复 `request.json` 条目也返回 `READY`。物理文件仍存在，因而基础“文件存在”检查无法发现清单与证据集合不一致。证据见 `stage11_reaudit_independent_faults.json`。

这使首轮 `STATIC-06` 不能视为完全关闭；其余首轮失败项已复验关闭。Previous failures closed: **25/26**；本轮 28 个分组强制场景阻断 **27/28**。

## 首轮 26 个 FAIL 映射

| check_id | 原失败原因 | 声称修复位置 | 第二轮方法 | 第二轮结果 |
|---|---|---|---|---|
| DATA-03 | 原始身份可在标准化时被目标身份覆盖，且身份字段/Repository 防线不足 | assets.py; crypto_market.py; crypto_repository.py; stage11_schema.sql | static review + independent production entry/fault rerun | PASS |
| FAULT-A4 | 质量检查先排序再验证，无法发现输入顺序交换 | quality/crypto_checks.py | static review + independent production entry/fault rerun | PASS |
| FAULT-A5 | 质量检查没有严格约束配置时间范围 | quality/crypto_checks.py; stage11_build.py | static review + independent production entry/fault rerun | PASS |
| FAULT-B1 | 原始身份可在标准化时被目标身份覆盖，且身份字段/Repository 防线不足 | assets.py; crypto_market.py; crypto_repository.py; stage11_schema.sql | static review + independent production entry/fault rerun | PASS |
| FAULT-B2 | 原始身份可在标准化时被目标身份覆盖，且身份字段/Repository 防线不足 | assets.py; crypto_market.py; crypto_repository.py; stage11_schema.sql | static review + independent production entry/fault rerun | PASS |
| FAULT-B3 | 原始身份可在标准化时被目标身份覆盖，且身份字段/Repository 防线不足 | assets.py; crypto_market.py; crypto_repository.py; stage11_schema.sql | static review + independent production entry/fault rerun | PASS |
| FAULT-B4 | 原始身份可在标准化时被目标身份覆盖，且身份字段/Repository 防线不足 | assets.py; crypto_market.py; crypto_repository.py; stage11_schema.sql | static review + independent production entry/fault rerun | PASS |
| FAULT-B5 | 原始身份可在标准化时被目标身份覆盖，且身份字段/Repository 防线不足 | assets.py; crypto_market.py; crypto_repository.py; stage11_schema.sql | static review + independent production entry/fault rerun | PASS |
| FAULT-B6 | 原始身份可在标准化时被目标身份覆盖，且身份字段/Repository 防线不足 | assets.py; crypto_market.py; crypto_repository.py; stage11_schema.sql | static review + independent production entry/fault rerun | PASS |
| FAULT-C5 | 数值检查未使用 finite 语义，Infinity 漏检 | quality/crypto_checks.py | static review + independent production entry/fault rerun | PASS |
| FAULT-D1 | validate-only 未读取并全量对账既有 CSV/JSON/DuckDB | stage11_build.py; cli.py; crypto_repository.py | static review + independent production entry/fault rerun | PASS |
| FAULT-D2 | validate-only 未读取并全量对账既有 CSV/JSON/DuckDB | stage11_build.py; cli.py; crypto_repository.py | static review + independent production entry/fault rerun | PASS |
| FAULT-D3 | validate-only 未读取并全量对账既有 CSV/JSON/DuckDB | stage11_build.py; cli.py; crypto_repository.py | static review + independent production entry/fault rerun | PASS |
| FAULT-D4 | validate-only 未读取并全量对账既有 CSV/JSON/DuckDB | stage11_build.py; cli.py; crypto_repository.py | static review + independent production entry/fault rerun | PASS |
| FAULT-E1 | Raw 缺失、空、损坏、行数/schema/哈希没有 fail-closed 契约 | crypto_evidence.py; stage11_build.py; cli.py | static review + independent production entry/fault rerun | PASS |
| FAULT-E2 | Raw 缺失、空、损坏、行数/schema/哈希没有 fail-closed 契约 | crypto_evidence.py; stage11_build.py; cli.py | static review + independent production entry/fault rerun | PASS |
| FAULT-E3 | Raw 缺失、空、损坏、行数/schema/哈希没有 fail-closed 契约 | crypto_evidence.py; stage11_build.py; cli.py | static review + independent production entry/fault rerun | PASS |
| FAULT-E4 | Raw 缺失、空、损坏、行数/schema/哈希没有 fail-closed 契约 | crypto_evidence.py; stage11_build.py; cli.py | static review + independent production entry/fault rerun | PASS |
| FAULT-E5 | Raw 缺失、空、损坏、行数/schema/哈希没有 fail-closed 契约 | crypto_evidence.py; stage11_build.py; cli.py | static review + independent production entry/fault rerun | PASS |
| FAULT-F3 | Stage10 生产入口未在财务读取前隔离 crypto | fundamental_analysis.py; stage10_build.py; cli.py | static review + independent production entry/fault rerun | PASS |
| RAW-02 | AKShare Raw metadata 缺少抓取时间、版本、参数、列、行数和 schema hash | crypto_evidence.py::write_akshare_probe_evidence | static review + independent production entry/fault rerun | PASS |
| STATIC-02 | 原始身份可在标准化时被目标身份覆盖，且身份字段/Repository 防线不足 | assets.py; crypto_market.py; crypto_repository.py; stage11_schema.sql | static review + independent production entry/fault rerun | PASS |
| STATIC-03 | 原始身份可在标准化时被目标身份覆盖，且身份字段/Repository 防线不足 | assets.py; crypto_market.py; crypto_repository.py; stage11_schema.sql | static review + independent production entry/fault rerun | PASS |
| STATIC-05 | validate-only 未读取并全量对账既有 CSV/JSON/DuckDB | stage11_build.py; cli.py; crypto_repository.py | static review + independent production entry/fault rerun | PASS |
| STATIC-06 | Raw 缺失、空、损坏、行数/schema/哈希没有 fail-closed 契约 | crypto_evidence.py; stage11_build.py; cli.py | static review + independent production entry/fault rerun | FAIL: manifest required-file set not enforced |
| STATIC-07 | Stage10 生产入口未在财务读取前隔离 crypto | fundamental_analysis.py; stage10_build.py; cli.py | static review + independent production entry/fault rerun | PASS |

## 正常数据链路

独立重新访问 OKX `history-candles` 公共接口并在临时目录执行 Raw 四文件 → build → CSV/JSON/DuckDB → CLI validate-only → 指标重算 → 同 run_id 重跑。结果：960 行；UTC 范围 2026-06-18 00:00 至 2026-07-27 23:00；时间唯一且严格每小时连续；288 条周末记录；0–23 小时齐全；身份仅为 OKX SPOT `ETH-USDT` / `okx_public_api` / `1h`；末根已确认；OHLC 合理；成交量非负。CLI 返回 `READY`、exit 0。小时年化波动率独立重算误差为 0；同 run_id 的价格与 Raw 稳定内容哈希不变。

CSV、JSON 和 DuckDB 的 960 个主键及规范化逐行哈希一致，详见 `stage11_reaudit_reconciliation.csv`。这些均为统计特征验证，未形成价格预测、交易策略或投资结论。

## validate-only 与旧库

正常 validate-only 前后 Raw、CSV、JSON、DuckDB 的 SHA-256 与 mtime 全部不变，未重新请求 OKX，返回 READY。所有失败注入均在临时副本中执行，失败时没有自动修复或重建原始产物。

原 Stage 11 DuckDB 缺少身份列：`bar_interval, data_provider, instrument_type, normalized_exchange, normalized_instrument, raw_exchange, raw_instrument, requested_instrument`。新验证命令对旧库返回非零 exit 2 / BLOCKED，旧库 SHA-256 前后保持 `6bb69c569eff72aad97d68ea456ffdd1a69ca9901f333ff6842d5103645909f4`，未执行 ALTER 或默认值回填；合规 Raw 可在新临时库完成构建。

## Stage 10 隔离

生产 `analyze_stage10` 入口在读取输入前处理 `asset_type=crypto`，返回结构化 `not_applicable`，reason 明确，财务读取 spy 为 0，未生成 PE/PB/ROE/营收/净利润结果。真实 CLI dry-run 与 Stage 10 全量 45 项回归通过；未知资产类型抛出 `unsupported asset_type`，未落入 stock。

## 测试结果

| 范围 | 命令 | passed | failed | skipped | xfailed | warnings | exit code |
|---|---|---:|---:|---:|---:|---:|---:|
| stage11_remediation | `E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe -m pytest -q tests/test_stage11_remediation.py` | 53 | 0 | 0 | 0 | 0 | 0 |
| stage11 | `E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe -m pytest -q tests/test_stage11_crypto.py tests/test_stage11_remediation.py` | 64 | 0 | 0 | 0 | 0 | 0 |
| stage10 | `E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe -m pytest -q tests\test_stage10_financial.py tests\test_stage10_integration.py tests\test_stage10_repository.py` | 45 | 0 | 0 | 0 | 0 | 0 |
| stage9 | `E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe -m pytest -q tests/test_stage9_audit.py tests/test_stage9_database_integration.py tests/test_stage9_quality.py tests/test_stage9_repository.py tests/test_stage9_validate_only.py tests/test_style_classification.py tests/test_style_features.py tests/test_false_breakouts.py` | 43 | 0 | 0 | 0 | 0 | 0 |
| stage8 | `E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe -m pytest -q tests/test_stage8_analysis.py tests/test_stage8_audit.py tests/test_stage8_database_integration.py tests/test_stage8_quality.py tests/test_stage8_validate_only.py tests/test_limit_event_detection.py tests/test_limit_event_repository.py tests/test_limit_rules.py` | 134 | 0 | 0 | 0 | 0 | 0 |
| stage7 | `E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe -m pytest -q tests/test_stage7_audit.py tests/test_stage7_database_integration.py tests/test_activity_score.py tests/test_stock_daily_features.py` | 22 | 0 | 0 | 0 | 0 | 0 |
| stage0 | `E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe tests/test_stage0_config.py` | 35 | 0 | 0 | 0 | 0 | 0 |
| full | `E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe -m pytest -q tests` | 508 | 0 | 0 | 0 | 0 | 0 |

## 静态检查与边界

16 项不变量中 15 项通过。原始身份在标准化前校验，Repository 二次校验，SQL/应用约束、严格范围、finite 数值语义、三格式对账、Stage10 前置隔离和无硬编码 PASS/960/测试名称均符合；第 9 项 Raw manifest 文件清单完整性失败。LF/CRLF 仅出现四个 tracked 文件“下次 Git 接触将转 CRLF”的 warning，`git diff --numstat` 与忽略行尾差异的 stat 均为 188 行新增，不是整文件纯换行重写，记为 OBSERVATION。

## Git、冻结与证据保护

分支为 `feature/stage11-ethusdt-validation`，HEAD 与 Stage10 标签提交均为 `d6b2b6a447f55c8f59f17f31ff1fd326dfc095c3`，祖先检查 exit 0。Stage0 三文件、原 DuckDB、原 Raw 两文件的前后 SHA-256 均不变。第一轮验收目录只读复核并记录逐文件 SHA-256。本轮仅新增 `reports/stage11_reaudit/`；未修改实现、原始数据库、原始 Raw、首轮验收目录或冻结文件，未执行 add/commit/push。

## 修复建议

Raw validator 应要求 `evidence_files` 的名称集合和计数严格等于 `request.json`、`response.json`、`metadata.json` 各一次，并拒绝重复项、遗漏项、额外项和路径穿越名称；随后新增生产入口回归并重跑本报告全部门禁。
