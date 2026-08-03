# Stage 11 验收失败修复报告

## 1. 修复摘要

独立验收的 26 个 FAIL 已逐项映射到生产根因、修改模块与自动化测试。修复自测状态为 **READY_FOR_REAUDIT**，不代表独立验收 PASS。28/28 个强制故障场景达到预期。

## 2. 独立验收失败项映射

| acceptance check_id | 原状态 | 根因 | 修改文件 | 新测试 | 修复后自测状态 |
|---|---|---|---|---|---|
| `STATIC-02` | FAIL | 标准化前没有不可绕过的原始身份验证 | assets.py; crypto_market.py; adapters/crypto_exchange.py; stage11_schema.sql; crypto_repository.py | 身份错配、缺字段、Repository绕过测试 | PASS |
| `STATIC-03` | FAIL | 标准化前没有不可绕过的原始身份验证 | assets.py; crypto_market.py; adapters/crypto_exchange.py; stage11_schema.sql; crypto_repository.py | 身份错配、缺字段、Repository绕过测试 | PASS |
| `STATIC-05` | FAIL | validate-only未读取并全量对账已有产物 | stage11_build.py; cli.py; crypto_repository.py | CSV/JSON/DuckDB值、主键、身份和时间篡改测试 | PASS |
| `STATIC-06` | FAIL | Raw证据没有文件、内容和身份契约 | crypto_evidence.py; cli.py; stage11_build.py | Raw缺失/空/损坏/哈希/行数/schema/请求身份测试 | PASS |
| `STATIC-07` | FAIL | 资产隔离helper未接入Stage10公开生产入口 | fundamental_analysis.py; stage10_build.py; cli.py | crypto零读取、equity回归、未知类型拒绝测试 | PASS |
| `RAW-02` | FAIL | Raw证据没有文件、内容和身份契约 | crypto_evidence.py; cli.py; stage11_build.py | Raw缺失/空/损坏/哈希/行数/schema/请求身份测试 | PASS |
| `DATA-03` | FAIL | 标准化前没有不可绕过的原始身份验证 | assets.py; crypto_market.py; adapters/crypto_exchange.py; stage11_schema.sql; crypto_repository.py | 身份错配、缺字段、Repository绕过测试 | PASS |
| `FAULT-A4` | FAIL | 质量函数排序后检查且未验证有限值与配置边界 | quality/crypto_checks.py; stage11_build.py | 顺序、范围、Infinity、NaN、字符串、OHLCV测试 | PASS |
| `FAULT-A5` | FAIL | 质量函数排序后检查且未验证有限值与配置边界 | quality/crypto_checks.py; stage11_build.py | 顺序、范围、Infinity、NaN、字符串、OHLCV测试 | PASS |
| `FAULT-B1` | FAIL | 标准化前没有不可绕过的原始身份验证 | assets.py; crypto_market.py; adapters/crypto_exchange.py; stage11_schema.sql; crypto_repository.py | 身份错配、缺字段、Repository绕过测试 | PASS |
| `FAULT-B2` | FAIL | 标准化前没有不可绕过的原始身份验证 | assets.py; crypto_market.py; adapters/crypto_exchange.py; stage11_schema.sql; crypto_repository.py | 身份错配、缺字段、Repository绕过测试 | PASS |
| `FAULT-B3` | FAIL | 标准化前没有不可绕过的原始身份验证 | assets.py; crypto_market.py; adapters/crypto_exchange.py; stage11_schema.sql; crypto_repository.py | 身份错配、缺字段、Repository绕过测试 | PASS |
| `FAULT-B4` | FAIL | 标准化前没有不可绕过的原始身份验证 | assets.py; crypto_market.py; adapters/crypto_exchange.py; stage11_schema.sql; crypto_repository.py | 身份错配、缺字段、Repository绕过测试 | PASS |
| `FAULT-B5` | FAIL | 标准化前没有不可绕过的原始身份验证 | assets.py; crypto_market.py; adapters/crypto_exchange.py; stage11_schema.sql; crypto_repository.py | 身份错配、缺字段、Repository绕过测试 | PASS |
| `FAULT-B6` | FAIL | 标准化前没有不可绕过的原始身份验证 | assets.py; crypto_market.py; adapters/crypto_exchange.py; stage11_schema.sql; crypto_repository.py | 身份错配、缺字段、Repository绕过测试 | PASS |
| `FAULT-C5` | FAIL | 质量函数排序后检查且未验证有限值与配置边界 | quality/crypto_checks.py; stage11_build.py | 顺序、范围、Infinity、NaN、字符串、OHLCV测试 | PASS |
| `FAULT-D1` | FAIL | validate-only未读取并全量对账已有产物 | stage11_build.py; cli.py; crypto_repository.py | CSV/JSON/DuckDB值、主键、身份和时间篡改测试 | PASS |
| `FAULT-D2` | FAIL | validate-only未读取并全量对账已有产物 | stage11_build.py; cli.py; crypto_repository.py | CSV/JSON/DuckDB值、主键、身份和时间篡改测试 | PASS |
| `FAULT-D3` | FAIL | validate-only未读取并全量对账已有产物 | stage11_build.py; cli.py; crypto_repository.py | CSV/JSON/DuckDB值、主键、身份和时间篡改测试 | PASS |
| `FAULT-D4` | FAIL | validate-only未读取并全量对账已有产物 | stage11_build.py; cli.py; crypto_repository.py | CSV/JSON/DuckDB值、主键、身份和时间篡改测试 | PASS |
| `FAULT-E1` | FAIL | Raw证据没有文件、内容和身份契约 | crypto_evidence.py; cli.py; stage11_build.py | Raw缺失/空/损坏/哈希/行数/schema/请求身份测试 | PASS |
| `FAULT-E2` | FAIL | Raw证据没有文件、内容和身份契约 | crypto_evidence.py; cli.py; stage11_build.py | Raw缺失/空/损坏/哈希/行数/schema/请求身份测试 | PASS |
| `FAULT-E3` | FAIL | Raw证据没有文件、内容和身份契约 | crypto_evidence.py; cli.py; stage11_build.py | Raw缺失/空/损坏/哈希/行数/schema/请求身份测试 | PASS |
| `FAULT-E4` | FAIL | Raw证据没有文件、内容和身份契约 | crypto_evidence.py; cli.py; stage11_build.py | Raw缺失/空/损坏/哈希/行数/schema/请求身份测试 | PASS |
| `FAULT-E5` | FAIL | Raw证据没有文件、内容和身份契约 | crypto_evidence.py; cli.py; stage11_build.py | Raw缺失/空/损坏/哈希/行数/schema/请求身份测试 | PASS |
| `FAULT-F3` | FAIL | 资产隔离helper未接入Stage10公开生产入口 | fundamental_analysis.py; stage10_build.py; cli.py | crypto零读取、equity回归、未知类型拒绝测试 | PASS |

## 3. 根因分析

失败不是指标计算问题，而是信任边界不完整：配置值可覆盖原始身份、Raw没有可验证契约、validate-only只是配置预检、质量检查排序后掩盖输入顺序且没有有限值/完整边界、Stage10 helper没有进入生产调用链。

## 4. 身份与来源模型修复

新增并持久化 requested/raw/normalized instrument、data_provider、raw/normalized exchange、instrument_type、bar_interval 和 completed 标志。精确契约只接受 OKX SPOT `ETH-USDT` 1h。适配器输出实际身份，标准化前验证，Repository写前再次验证，SQL增加 NOT NULL/CHECK。旧版缺列数据库明确拒绝，必须从可信 Raw 重建。

## 5. Raw 证据契约

真实历史 run 使用 request.json、response.json、metadata.json、manifest.json；验证文件存在/非空/可解析、完整响应行数、columns/schema hash、response content hash、文件清单及哈希、请求/响应身份。AKShare probe 保存未筛选完整响应和版本、抓取时间、参数、列、行数与哈希。

## 6. validate-only 修复

严格模式完全离线且只读，要求指定 run_id、Raw、CSV、JSON、DuckDB 和 as-of-date。任何必需输入缺失或旧数据库缺少身份列时返回 BLOCKED/CLI非零，不创建、重建或覆盖文件。

## 7. 产物一致性与防篡改

CSV/JSON/DuckDB统一UTC、固定字段顺序和12位有效数字规范，按主键稳定排序，生成逐行哈希和整体SHA-256，并与Raw投影哈希绑定。写入后才产生一致性质量结果，不再预置 PASS。

## 8. 数值与时间范围检查

新增 `numeric_finite`、严格输入递增、整点、逐小时、唯一、配置起止边界、数学期望行数、完成K线和UTC/本地往返检查。NaN、±Infinity、字符串、负成交量、非法OHLC、缺失/重复/乱序/范围外K线均失败关闭。

## 9. Stage 10 财务隔离

`analyze_stage10(asset_type=...)` 在加载配置、读取数据库或调用财务逻辑前分派。crypto返回结构化 `not_applicable`、空财务结果、quality_failed=0，财务读取次数为0；未知类型报错；equity默认参数保持原行为，Stage10 45/45通过。

## 10. 新增测试

新增 `tests/test_stage11_remediation.py` 共53项，覆盖错误/缺失身份、Repository绕过、Raw契约、三格式篡改、所有数值和时间故障、只读语义、Stage10零读取和未知类型。原Stage11测试同步为可信身份和Raw契约输入。

## 11. 回归测试结果

| 范围 | 命令 | collected | passed | failed | skipped | warnings | exit |
|---|---|---:|---:|---:|---:|---:|---:|
| remediation_faults | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" -m pytest tests/test_stage11_remediation.py -q` | 53 | 53 | 0 | 0 | 0 | 0 |
| stage11 | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" -m pytest tests/test_stage11_crypto.py tests/test_stage11_remediation.py -q` | 64 | 64 | 0 | 0 | 0 | 0 |
| stage10 | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" -m pytest tests/test_stage10_financial.py tests/test_stage10_integration.py tests/test_stage10_repository.py -q` | 45 | 45 | 0 | 0 | 0 | 0 |
| stage9 | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" -m pytest tests/test_stage9_audit.py tests/test_stage9_database_integration.py tests/test_stage9_quality.py tests/test_stage9_repository.py tests/test_stage9_validate_only.py tests/test_style_classification.py tests/test_style_features.py tests/test_false_breakouts.py -q` | 43 | 43 | 0 | 0 | 0 | 0 |
| stage8 | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" -m pytest tests/test_stage8_analysis.py tests/test_stage8_audit.py tests/test_stage8_database_integration.py tests/test_stage8_quality.py tests/test_stage8_validate_only.py tests/test_limit_event_detection.py tests/test_limit_event_repository.py tests/test_limit_rules.py -q` | 134 | 134 | 0 | 0 | 0 | 0 |
| stage7 | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" -m pytest tests/test_stage7_audit.py tests/test_stage7_database_integration.py tests/test_activity_score.py tests/test_stock_daily_features.py -q` | 22 | 22 | 0 | 0 | 0 | 0 |
| stage0 | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" tests/test_stage0_config.py` | 35 | 35 | 0 | 0 | 0 | 0 |
| full | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" -m pytest -q` | 508 | 508 | 0 | 0 | 0 | 0 |

完整测试为 508/508，无 skip、warning 或失败。日志：`reports/stage11_remediation_test.log`。

## 12. 28 个故障场景结果

28/28 均按预期阻断或返回 not_applicable。每个场景的输入、具体门禁和 pytest 节点见 `reports/stage11_remediation_fault_matrix.csv`。

## 13. 冻结文件哈希复核

| 文件 | 当前SHA-256 | 参考SHA-256 | 未变 |
|---|---|---|---|
| `config/universe.yml` | `0B6F61D43E753945B7E7931D27359E34A199891EAC3F7D59F29C9D17EFCCEC65` | `0B6F61D43E753945B7E7931D27359E34A199891EAC3F7D59F29C9D17EFCCEC65` | YES |
| `config/metric_definition.yml` | `13F9415D3E55AACC91E9913652D6E6520D9C681AC3043F09409602C44B5C00C4` | `13F9415D3E55AACC91E9913652D6E6520D9C681AC3043F09409602C44B5C00C4` | YES |
| `docs/stage0_scope.md` | `18EEEC59594B2CCA67CFC7E7F137855ED2B1F018C10623E426340188AC761615` | `18EEEC59594B2CCA67CFC7E7F137855ED2B1F018C10623E426340188AC761615` | YES |

原始 Stage11 DuckDB、原始 Raw 和 `reports/stage11_acceptance/` 未被修改。所有破坏性测试使用 pytest 临时目录；公网复验使用系统临时工作区并在结束后删除。

## 14. 已知限制

- 旧 Stage11 数据库因缺少原始身份字段不能被新验证器静默信任；需要从新 Raw 契约重建。
- 新配置只接受本阶段精确目标 OKX SPOT ETH-USDT 1h；其他加密资产需定义新的明确身份契约，不能复用默认值。
- 外部接口许可仍需法务确认，本修复不作法律结论。

## 15. 待独立复验事项

独立验收应重点复跑身份覆盖、Raw五类故障、CSV/JSON/DuckDB四类篡改、Infinity/范围外K线及Stage10生产入口零调用。临时公网复验重新得到960行，与原数据全部主键和OHLCV误差为0；16项指标逐行最大绝对误差0、空值掩码差0、假突破差0；两次同run重跑幂等，真实CLI validate-only返回READY。

本报告仅描述工程验证和统计特征兼容性，没有形成价格预测、交易信号或投资结论。
