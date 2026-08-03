# Stage 11 第三轮独立复验报告

## 1. 最终结论

**FAIL**。原 28 项故障矩阵全部在生产入口阻断，正常 960 行链路返回 `READY`，530 项完整回归全部通过；但附件明确要求的 Manifest 场景“文件存在但未列入 Manifest”仍由真实 `validate-crypto --validate-only` 返回顶层 `READY`、退出码 0。Manifest 故障矩阵仅 **20/21** 阻断，因此不满足 PASS 的硬性条件。

本轮只执行独立验收，没有修改实现代码、Stage 0 冻结文件、原 Raw、原 DuckDB 或既有验收/修复报告；所有故障均在临时副本中制造。本项目仅用于研究和测试，本报告不构成投资建议。

## 2. 关键失败：未列入 Manifest 的物理文件被接受

在一份正常 Raw 临时副本中新增 `orphan.json`，保持 `manifest.json` 不变，再执行真实生产命令 `validate-crypto --validate-only`。实际结果：

- 顶层 `status`: `READY`
- `blocking_reasons`: `[]`
- exit code: `0`
- row count: `960`
- 执行前后临时副本所有文件 SHA-256、大小与 mtime 不变
- 通过无效本地代理隔离网络，命令仍返回 READY

静态根因与动态结果一致：`crypto_evidence.py` 只遍历 `manifest.evidence_files` 中已列出的路径并校验 role/path/hash/size，没有把 Raw 目录中的应受契约约束文件集合与 Manifest 条目做闭集对账。相关逻辑从 `src/akshare_data_test/crypto_evidence.py:274` 开始；专项测试也未包含“额外物理文件未列入 Manifest”的生产 CLI 场景。

这不是第二轮已经发现的“遗漏必需 role”或“重复条目”原样复现：这两类现已正确阻断；它是附件第三轮清单中独立列出的场景 13，仍未 fail-closed。故首轮 `STATIC-06` 不能判定完全关闭，Previous failures closed 为 **25/26**。

## 3. 历史失败—修复—第三轮验证映射

| 原验收失败项 | 第二轮遗留问题 | 声称修复位置 | 第三轮验证方法 | 实际结果 |
|---|---|---|---|---|
| DATA-03 | 已声称关闭 | assets.py; crypto_market.py; crypto_repository.py; stage11_schema.sql | 原矩阵身份注入 + 960 行身份列对账 | PASS |
| FAULT-A4 | 已声称关闭 | quality/crypto_checks.py | 原矩阵顺序/时间质量生产入口复跑 | PASS |
| FAULT-A5 | 已声称关闭 | quality/crypto_checks.py; stage11_build.py | 范围与缺 K 生产入口复跑 | PASS |
| FAULT-B1 | 已声称关闭 | assets.py; crypto_market.py; repository/schema | ETH-USD 注入 | PASS |
| FAULT-B2 | 已声称关闭 | 同上 | ETH-USDT-SWAP 注入 | PASS |
| FAULT-B3 | 已声称关闭 | 同上 | provider 注入 | PASS |
| FAULT-B4 | 已声称关闭 | 同上 | provider/source 注入 | PASS |
| FAULT-B5 | 已声称关闭 | 同上 | 缺少原始身份字段 | PASS |
| FAULT-B6 | 已声称关闭 | 同上 | exchange 注入 | PASS |
| FAULT-C5 | 已声称关闭 | quality/crypto_checks.py | 非有限/非数值输入 | PASS |
| FAULT-D1 | 已声称关闭 | stage11_build.py; cli.py; repository | CSV 删除行 + validate-only | PASS |
| FAULT-D2 | 已声称关闭 | 同上 | JSON/CSV 数值篡改 | PASS |
| FAULT-D3 | 已声称关闭 | 同上 | DuckDB source 篡改 | PASS |
| FAULT-D4 | 已声称关闭 | 同上 | 时间戳篡改 | PASS |
| FAULT-E1 | 已声称关闭 | crypto_evidence.py; stage11_build.py; cli.py | Raw 目录缺失 | PASS |
| FAULT-E2 | 已声称关闭 | 同上 | Raw response 缺失 | PASS |
| FAULT-E3 | 已声称关闭 | 同上 | Raw response 为空 | PASS |
| FAULT-E4 | 已声称关闭 | 同上 | Raw row count 不一致 | PASS |
| FAULT-E5 | 已声称关闭 | 同上 | Raw schema/content hash 不一致 | PASS |
| FAULT-F3 | 已声称关闭 | fundamental_analysis.py; stage10_build.py; cli.py | Stage 10 crypto 生产 CLI + 财务读取隔离回归 | PASS，reads=0 |
| RAW-02 | 已声称关闭 | crypto_evidence.py::write_akshare_probe_evidence | Raw 元数据/契约静态审查与生产验证 | PASS |
| STATIC-02 | 已声称关闭 | assets.py; crypto_market.py; repository/schema | 身份注入 + Repository/格式对账 | PASS |
| STATIC-03 | 已声称关闭 | 同上 | 960 行八个身份维度 distinct 对账 | PASS |
| STATIC-05 | 已声称关闭 | stage11_build.py; cli.py; repository | CSV/JSON/DuckDB 篡改生产入口复跑 | PASS |
| STATIC-06 | 第二轮唯一遗留：遗漏/重复 manifest 条目仍 READY | crypto_evidence.py; test_stage11_manifest_contract.py | 21 项 Manifest 临时副本 + 真实 CLI | **FAIL：20/21；未列入 Manifest 的物理文件仍 READY** |
| STATIC-07 | 已声称关闭 | fundamental_analysis.py; stage10_build.py; cli.py | crypto/stock/unknown asset 隔离复跑 | PASS |

## 4. Manifest 静态审查

以下项目均已确认实现并动态阻断：三个必需 role 各一次、在集合化前统计 multiplicity、同路径重复、同 role 不同路径、大小写/斜杠/`./` 规范化重复、绝对路径、`..`、双 response、列出文件缺失、文件为空、size/hash 不符、entries 非数组、条目字段缺失，以及底层 blocker 向 CLI 的传播。

未通过项：验证器没有枚举 Raw 根目录并拒绝未由 Manifest 声明的额外证据文件。未发现硬编码测试文件名、固定 READY 结果或针对特定用例打补丁的实现逻辑。

## 5. 独立测试结果

| 范围 | collected | passed | failed | skipped | xfailed | warnings | exit code |
|---|---:|---:|---:|---:|---:|---:|---:|
| `tests/test_stage11_manifest_contract.py` | 22 | 22 | 0 | 0 | 0 | 0 | 0 |
| `tests/test_stage11_remediation.py` | 53 | 53 | 0 | 0 | 0 | 0 | 0 |
| Stage 11 全部三文件 | 86 | 86 | 0 | 0 | 0 | 0 | 0 |
| Stage 10 全部三文件 | 45 | 45 | 0 | 0 | 0 | 0 | 0 |
| Stage 0 静态检查 | 35 | 35 | 0 | 0 | 0 | 0 | 0 |
| 完整 `tests` | 530 | 530 | 0 | 0 | 0 | 0 | 0 |

完整命令与实际输出见 `stage11_reaudit_round3_test.log`。测试全绿不足以覆盖本轮发现的 M13 漏检。

## 6. 故障矩阵

- 原故障矩阵：**28/28** 阻断。
- Manifest 故障矩阵：**20/21** 阻断。
- 所有注入使用临时副本；异常流程没有重写 Raw、CSV、JSON 或 DuckDB，也没有自动补全/去重 Manifest。
- validate-only 通过无效 HTTP/HTTPS/ALL proxy 隔离，未发生网络访问。

逐项证据见 `stage11_reaudit_round3_fault_matrix.csv` 和 `stage11_reaudit_round3_results.json`。

## 7. 正常 960 行链路

正常临时证据经生产 CLI 返回 `READY`、exit 0，且前后 SHA-256/mtime 快照完全一致。raw/clean/indicator 各 960 行，profile 1 行，quality 19 行，audit 1 行；requested/raw/normalized instrument、provider、raw/normalized exchange、instrument type、bar interval 八个身份维度均各只有一个值。时间范围与 40×24 小时配置一致，OHLCV、有限数值、时间连续性、CSV/JSON/DuckDB 全量对账及指标门禁通过。

同一 run_id 再执行后价格 CSV、JSON 与 Raw 哈希稳定，数据库逻辑计数保持幂等。旧 Stage 11 DuckDB 被 exit 2 / `BLOCKED` 安全拒绝，旧库 SHA-256 未改变。

## 8. Stage 10 隔离

crypto 生产 CLI 返回结构化 `not_applicable`、exit 0；独立回归确认财务读取次数为 0。股票路径 45/45 回归通过；未知 `commodity` 在 CLI 参数边界被拒绝，未默认进入股票路径。

## 9. Git 与文件完整性

分支 `feature/stage11-ethusdt-validation`；HEAD 始终为 `d6b2b6a447f55c8f59f17f31ff1fd326dfc095c3`；staged 文件数为 0。`git diff --check` exit 0。四个既有 tracked 文件的 LF→CRLF 提示仅记录为观察项，没有在验收中转换换行符。

Stage 0 三文件、原 DuckDB、原 AKShare Raw、既有首轮验收目录、第二轮验收目录和 remediation 文件的前后哈希均一致。实现目录所有 Python 文件前后哈希一致。除 `reports/stage11_reaudit_round3/` 外，本轮没有新增仓库变化。详见 `stage11_reaudit_round3_git_evidence.txt`。

## 10. 最终判定

PASS 条件中的“Manifest 21 项故障全部阻断”和“文件存在但未列入 Manifest 时生产 CLI fail-closed”未满足，因此最终状态只能为 **FAIL**。建议在 Raw evidence 契约中明确允许文件集合，并把目录实际文件集合与 Manifest 声明集合做规范化后的闭集对账，再新增真实 CLI 回归并进行下一轮独立复验。
