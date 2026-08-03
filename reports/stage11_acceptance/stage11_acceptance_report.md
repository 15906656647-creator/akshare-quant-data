# Stage 11 ETHUSDT 独立验收报告

## 1. 执行摘要

本次仅执行独立验收，没有修改实现代码、配置、SQL、既有测试或既有报告。独立公网核验、全量数据对账、指标重算、临时数据库幂等测试及 29 项故障注入均已执行。

## 2. 最终结论

**FAIL**。强制检查通过 38/64，失败 26，阻塞 0。尽管 455/455 完整测试通过，仍有强制故障未被门禁检测，按验收规则必须失败。

## 3. 验收范围

覆盖 Git/冻结基线、Stage11 源码与配置、Stage7–11/Stage0/完整回归、AKShare Raw、OKX/Binance 公网来源、960 根 K 线、三格式一致性、独立指标、幂等/回滚、故障注入、Stage10 财务隔离与文档边界。未执行投资分析。

## 4. 环境与版本

Windows，Python 3.11.4；akshare 1.18.80、pandas 3.0.5、numpy 2.4.6、DuckDB 1.5.5、pytest 9.1.1。使用项目现有 `.venv` 和 `requirements-lock.txt`，未另建环境；这是可复现性限制，详见 `stage11_environment.txt`。

## 5. Git 和冻结基线验证

分支 `feature/stage11-ethusdt-validation`；HEAD `d6b2b6a447f55c8f59f17f31ff1fd326dfc095c3`；Stage10 标签 `d6b2b6a447f55c8f59f17f31ff1fd326dfc095c3`，标签为当前祖先且与 HEAD 相同。无 staged changes，`git diff --check` 退出码为 0；三个实施方既有 tracked 改动有 LF→CRLF 提示，记为观察项而非 whitespace failure。

| 冻结文件 | 当前 SHA-256 | 参考 SHA-256 | 结论 | 证据来源 |
|---|---|---|---|---|
| `config/universe.yml` | `0B6F61D43E753945B7E7931D27359E34A199891EAC3F7D59F29C9D17EFCCEC65` | `0B6F61D43E753945B7E7931D27359E34A199891EAC3F7D59F29C9D17EFCCEC65` | PASS | `reports/stage1_acceptance_report.json` |
| `config/metric_definition.yml` | `13F9415D3E55AACC91E9913652D6E6520D9C681AC3043F09409602C44B5C00C4` | `13F9415D3E55AACC91E9913652D6E6520D9C681AC3043F09409602C44B5C00C4` | PASS | `reports/stage1_acceptance_report.json` |
| `docs/stage0_scope.md` | `18EEEC59594B2CCA67CFC7E7F137855ED2B1F018C10623E426340188AC761615` | `18EEEC59594B2CCA67CFC7E7F137855ED2B1F018C10623E426340188AC761615` | PASS | `reports/stage1_acceptance_report.json` |

工作树因实施方 Stage11 未提交变更并不干净；本验收仅新增 `reports/stage11_acceptance/`。

## 6. Stage 11 文件变更审查

适配器边界和 8760 年化口径合理，Repository 使用事务/upsert。关键缺陷是标准化函数覆盖输入身份，数据模型未保存 `data_provider` 和原始 instrument；一致性质量行在写前预置 PASS；Raw 和既有输出未进入 validate-only 门禁。

## 7. 自动化测试结果

| 范围 | 命令 | collected | passed | failed | skipped | exit code | 结论 |
|---|---|---:|---:|---:|---:|---:|---|
| Stage 11 | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" -m pytest tests/test_stage11_crypto.py -q` | 11 | 11 | 0 | 0 | 0 | PASS |
| Stage 10 | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" -m pytest tests/test_stage10_financial.py tests/test_stage10_integration.py tests/test_stage10_repository.py -q` | 45 | 45 | 0 | 0 | 0 | PASS |
| Stage 9 | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" -m pytest tests/test_stage9_audit.py tests/test_stage9_database_integration.py tests/test_stage9_quality.py tests/test_stage9_repository.py tests/test_stage9_validate_only.py tests/test_style_classification.py tests/test_style_features.py tests/test_false_breakouts.py -q` | 43 | 43 | 0 | 0 | 0 | PASS |
| Stage 8 | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" -m pytest tests/test_stage8_analysis.py tests/test_stage8_audit.py tests/test_stage8_database_integration.py tests/test_stage8_quality.py tests/test_stage8_validate_only.py tests/test_limit_event_detection.py tests/test_limit_event_repository.py tests/test_limit_rules.py -q` | 134 | 134 | 0 | 0 | 0 | PASS |
| Stage 7 | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" -m pytest tests/test_stage7_audit.py tests/test_stage7_database_integration.py tests/test_activity_score.py tests/test_stock_daily_features.py -q` | 22 | 22 | 0 | 0 | 0 | PASS |
| Stage 0 | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" tests/test_stage0_config.py` | 35 | 35 | 0 | 0 | 0 | PASS |
| Full | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" -m pytest -q` | 455 | 455 | 0 | 0 | 0 | PASS |
| validate-only | `"E:\大学\实习\嘉驰国际\AKShare 量化金融数据\.venv\Scripts\python.exe" run_pipeline.py validate-crypto --as-of-date 2026-07-27 --config config/stage11.yml --validate-only` | 0 | 0 | 0 | 0 | 0 | PASS |

没有 skip、xfail 或 deselected。完整日志见 `stage11_test_execution.log`。

## 8. AKShare 探针核验

独立读取完整 parquet：10 行、9 列，ETH 相关 0 行，精确 ETHUSDT 0 行，`unsupported` 判断正确。Raw 元数据缺少 `fetched_at`、`akshare_version`、`parameters`、`columns`、`schema_hash`，因此证据完整性 FAIL；Raw 缺失/空/损坏也不会阻断 validate-only。

## 9. OKX 来源和品种核验

独立公网请求返回 200；官方公共 instruments 结果确认 `ETH-USDT` 为 `SPOT`。保存的末根 1H K 线在历史接口重叠区间找到、`confirm=1`，六个数值字段在 1e-12 内一致。Binance HTTP 451 亦独立复现。公网响应哈希、请求参数和结果见 `stage11_network_evidence.json`。

## 10. 960 根小时 K 线质量结果

960 行、960 个唯一 UTC 时间戳；无缺时、重复、非整小时、非法 OHLC、负成交量、NaN/Infinity。范围为 2026-06-18T00:00:00+00:00 至 2026-07-27T23:00:00+00:00。标准字段分布是 ETHUSDT/OKX/spot/1h，但因未保存原始 instrument，不能仅凭这些被标准化后的字段证明每一行原始身份。

## 11. UTC 日边界验证

共有 40 个 UTC 自然日，每日恰好 24 根，数学关系 40×24=960；首根 2026-06-18 00:00 UTC，末根 2026-07-27 23:00 UTC。本地时间字段为 UTC+08:00。DuckDB 客户端可能按会话时区显示 `+08:00`，独立规范化后为同一 UTC 时刻。

## 12. CSV/JSON/DuckDB 一致性

三者均 960 行，主键集合和被比较字段集合一致；全量逐行不一致为 0，数值最大绝对误差 0（布尔/文本/时间亦一致）。规范化 SHA-256 均为 `5c5d6e84d723b2f3b2ca93768b9ed493f178df04b2e5c36b628f1cb162322e47`。数据库表计数：raw 960、clean 960、feature 960、profile 1、quality 11、audit 1。

## 13. 指标独立重算

未导入项目指标函数，自行从 OHLCV 重算 16 个指标，全部在 1e-12 容差内：年化波动率约 66.211%、ATR/close 约 1.0443%、布林带宽约 4.4085%、趋势斜率约 -0.1472%/bar、箱体宽约 4.7111%、确认假突破计数 32。这些仅为统计特征，不构成预测或建议。

## 14. 数据库幂等验证

在临时 DuckDB 副本上用同一 run_id 连续写两次：各表计数和关键哈希稳定、主键重复为 0、quality 仍为 11、audit 仍为 1、其他 run 保留。注入缺列失败后事务回滚完整。结论 PASS。

## 15. 故障注入结果

共 29 项，其中 9 项异常被成功阻断，19 项强制异常漏检，另 1 项为 equity 基线不应阻断。主要漏检：输入顺序/范围、instrument/provider/exchange 身份、Infinity、四类产物篡改、五类 Raw 证据异常、Stage10 生产入口隔离。完整矩阵见 `stage11_fault_injection.csv`。

## 16. Stage 10 财务隔离

`require_equity_asset` helper 对 crypto 返回 `not_applicable` 的单元测试通过，但生产 `analyze_stage10` 入口没有 `asset_type` 参数，也未调用该 helper。Stage11 报告中的 `not_applicable` 是硬编码描述，不能证明生产财务入口拒绝 crypto。结论 FAIL。

## 17. 来源与许可风险

实现文档清楚披露 AKShare unsupported、OKX 实际来源、Binance 451、单一交易所及 40 UTC 日范围。已记录官方公共接口 URL 和参数，但没有足够证据对使用条款作法律判断；建议在进入更广泛使用前由法务确认。

## 18. 回归影响

Stage7 22/22、Stage8 134/134、Stage9 43/43、Stage10 45/45、Stage11 11/11、Stage0 35/35、完整集 455/455 均通过。现有测试覆盖不足以发现本次故障注入揭示的门禁缺陷。

## 19. 发现的问题

- `STATIC-02` 目标 instrument 与市场身份不可被改名冒充：normalize_crypto_bars 按配置覆盖 symbol/exchange/market；注入未阻断。证据：`stage11_fault_injection.csv; src/akshare_data_test/crypto_market.py:45`
- `STATIC-03` 持久化 provider、原始品种、标准品种和周期：仅 source/symbol/exchange/market/interval；无 data_provider/original instrument。证据：`sql/stage11_schema.sql; stage11_data_reconciliation.csv`
- `STATIC-05` CSV/JSON/DuckDB 一致性质量门禁：质量行预置 PASS；validate-only 不读取既有产物，D1-D4 均 READY。证据：`src/akshare_data_test/stage11_build.py:159; stage11_fault_injection.csv`
- `STATIC-06` Raw 探针证据门禁：validate_stage11_inputs 不检查 Raw；E1-E5 均 READY。证据：`src/akshare_data_test/stage11_build.py:56; stage11_fault_injection.csv`
- `STATIC-07` Stage10 生产财务入口隔离 crypto：防护 helper 仅被测试调用；analyze_stage10 无 asset_type 参数/生产防护。证据：`src/akshare_data_test/fundamental_analysis.py:25; src/akshare_data_test/stage10_build.py:271`
- `RAW-02` AKShare Raw 元数据完整性：missing=['fetched_at', 'akshare_version', 'parameters', 'columns', 'schema_hash']。证据：`independent_audit_evidence.json`
- `DATA-03` 原始 instrument 身份保留：无原始品种字段；只有标准 symbol=ETHUSDT。证据：`stage11_data_reconciliation.csv`
- `FAULT-A4` swap adjacent input rows：overall PASS。证据：`stage11_fault_injection.csv`
- `FAULT-A5` prepend bar outside configured 40-day range：overall PASS。证据：`stage11_fault_injection.csv`
- `FAULT-B1` input symbol ETH-USD：status=PASS;exit=0;blockers=[]。证据：`stage11_fault_injection.csv`

其余失败逐项见 `stage11_acceptance_results.json` 和 `stage11_fault_injection.csv`。

## 20. 已知限制

- 使用现有锁定 `.venv`，未从零安装环境。
- 独立网络核验只重叠验证保存数据的末根 K 线；实现方未保存 OKX 完整 Raw HTTP 响应，无法逐页重演 960 根采集链。
- 未作外部接口许可的法律结论。
- 当前实现变更未提交，验收基于工作区快照。

## 21. Git 清洁性复核

末次 `git status --short`、diff、未跟踪/忽略证据和冻结哈希已保存至 `stage11_git_evidence.txt`。除实施方原有文件外，验收过程的新文件全部位于 `reports/stage11_acceptance/`；未 staged、commit 或 push。

## 22. 验收结论和后续动作

最终状态：**FAIL**。建议实施方修复身份与来源不可伪造、Raw/产物完整性门禁、Infinity/范围检查和 Stage10 生产入口隔离后，再由独立验收方复跑本证据包。当前不建议标记 Stage11 已验收。
