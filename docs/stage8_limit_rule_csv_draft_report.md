# Stage8 涨跌停规则历史 CSV 草稿与来源链报告

> 报告日期：2026-08-06
> 分支：`feature/stage15-authoritative-sources`
> run_id：`cd7deb65-8b9f-4c00-83d6-0e200bb0d036`
> 数据集版本：`2026-07-27-stage8-limit-rules-draft-v1`
> as_of_date：`2026-07-27`
> 正式窗口：`2025-07-27` 至 `2026-07-27`
> 本项目仅用于研究与测试，不构成投资建议。

## 1. 结论

```text
规则CSV草稿：PARTIAL（草稿已生成且技术校验通过，但来源链与人工复核未完成）
来源文件哈希：COMPLETE（25 个文件全部可哈希、无缺失、无零字节、无重复哈希、格式有效；新增 2 个哈希已补录）
来源链：INCOMPLETE（上交所精确附件 URL 未补录，retrieved_at 为占位，无人工复核记录）
规则日期覆盖：COMPLETE（2025-07-27..2026-07-05 与 2026-07-06..2026-07-27 连续覆盖）
规则条款可追溯：YES（每条记录可追溯到正文条款号）
人工双人复核：INCOMPLETE
可运行stage8-rules-build --validate-only：NO（人工审批门禁阻断；来源链也尚未完整）
可正式发布规则数据：NO
可执行Stage8重建：NO
可重跑S15-14：NO
可进入Stage16：NO
```

## 2. 实际读取的 CSV Schema

依据 `dataset.schema.yml` 与 `src/akshare_data_test/stage8_manual.py`：

- 必填列：`market exchange board security_type rule_type limit_ratio effective_from effective_to source_name source_document_id source_document_date source_reference retrieved_at raw_file source_sha256 review_status reviewer notes`
- 可选列：`record_id symbol limit_down_ratio tick_size price_precision rounding_rule rule_version verified_at`
- 日期区间：闭区间 `[effective_from, effective_to]`；`effective_to` 为空表示仍有效。
- `review_status` 枚举：`approved / rejected / pending`；实现不支持 `draft`，因此草稿使用 `pending`。
- `rule_type` 枚举：`price_limit / st_price_limit / ipo_first_day / no_limit`。
- `board` 枚举：`main / growth / star / bse`；`exchange` 枚举：`SH / SZ / BJ`。
- `security_type`：大写令牌，如 `A_SHARE`。
- `raw_file`：必须以 `sources/` 开头且不能越出数据集目录。
- `source_sha256`：64 位小写十六进制，必须与 `dataset.yml` 登记哈希及本地文件一致。
- 规则优先级：个股规则（`symbol` 非空）优先，其次板块规则；本项目 12 条均为板块规则，`symbol` 留空。
- 实现实际消费的记录文件是 `limit_rules.csv`（`RULES_RECORD_FILE`）。任务要求生成的 `authoritative_limit_rules.csv` 已保留，两份内容完全一致。

## 3. 规则正文文件与 SHA-256

全部 25 个来源文件均完成 SHA-256 与格式核验；无缺失、零字节、重复哈希或格式错误。
新增 `szse_trading_rules_2023.pdf` 与 `szse_trading_rules_2023_notice.pdf` 哈希已补录到
`data/manual/stage8/limit_rules/rules_source_hashes.csv`。

### 3.1 本次正式规则记录使用的正文

| file_name | size_bytes | sha256 | format_valid | document_title | document_number | source_role |
| --- | ---: | --- | --- | --- | --- | --- |
| szse_trading_rules_2023.pdf | 620843 | 7018114a6e11deb239c2a72e71e49defc6e8841b3e2c093b3bbf809282c67222 | PDF/是 | 深圳证券交易所交易规则（2023年修订） | 深证上〔2023〕98号 | 深市2025-07-27..2026-07-05正式正文 |
| szse_trading_rules_2026.pdf | 282084 | 9b66f8b0db70f84a25ef1ccb4ee2351001724e408117552d75f6d8993483c586 | PDF/是 | 深圳证券交易所交易规则（2026年修订） | 深证上〔2026〕551号 | 深市2026-07-06..2026-07-27正式正文 |
| sse_trading_rules_2023.docx | 51948 | 7aa2319f6dcf597be1e86b3b69d7c2ad0e6acb2a5d0cc6be48a01af602fded40 | DOCX/是 | 上海证券交易所交易规则（2023年修订） | 上证发〔2023〕32号 | 沪市2025-07-27..2026-07-05正式正文 |
| sse_trading_rules_2026.docx | 65302 | fc922c433438b2636cb631eab25cca405209712acbb6aaded768c45456ff8888 | DOCX/是 | 上海证券交易所交易规则（2026年修订） | 上证发〔2026〕41号 | 沪市2026-07-06..2026-07-27正式正文 |

### 3.2 其余来源文件哈希摘要

全部 25 个文件均无重复哈希、无零字节、格式有效，完整清单见
`reports/stage8_rule_source_audit/e9a2d920-c4e2-42f4-b738-edf215c15fd1/tools/source_hashes.json`。

## 4. 来源链完整性

| 项目 | 状态 | 说明 |
| --- | --- | --- |
| 深交所2023正文来源链 | 基本完整 | 已登记官方页面、附件 URL、SHA-256；`retrieved_at` 为草稿占位，需人工确认 |
| 深交所2026正文来源链 | 完整 | 官方页面与附件 URL 均来自本地通知正文，SHA-256 已登记 |
| 上交所2023/2026正文来源链 | 不完整 | 当前仅登记规则目录页 `https://www.sse.com.cn/lawandrules/sselawsrules/stock/trading/`，精确附件 URL 待补录 |
| 双人复核 | 不完整 | `reviewer`、`reviewed_at` 均留空 |
| 哈希登记 | 完整 | `rules_source_hashes.csv` 已含新增两文件；`dataset.yml` 四份正文哈希与本地一致 |

`szse_trading_rules_2023.pdf` 物理页序为反向网页打印顺序，但正文文本完整；原始文件未修改，
哈希基于原始文件，条款按正文条款号引用。

## 5. 各正式文件标题、文号与适用期

| 文件 | 标题 | 文号 | 发布日期 | 施行日 | 草稿适用期 |
| --- | --- | --- | --- | --- | --- |
| szse_trading_rules_2023.pdf | 深圳证券交易所交易规则（2023年修订） | 深证上〔2023〕98号 | 2023-02-17 | 自首只主板注册制股票上市首日起施行（本地文件未给精确日期） | 2025-07-27..2026-07-05 |
| szse_trading_rules_2026.pdf | 深圳证券交易所交易规则（2026年修订） | 深证上〔2026〕551号 | 2026-04-24 | 2026-07-06 | 2026-07-06..2026-07-27 |
| sse_trading_rules_2023.docx | 上海证券交易所交易规则（2023年修订） | 上证发〔2023〕32号 | 2023-02-17 | 自首只主板注册制股票上市首日起施行（本地文件未给精确日期） | 2025-07-27..2026-07-05 |
| sse_trading_rules_2026.docx | 上海证券交易所交易规则（2026年修订） | 上证发〔2026〕41号 | 2026-04-24 | 2026-07-06 | 2026-07-06..2026-07-27 |

## 6. 提取的关键条款

### 6.1 深交所 2023 版

- 3.3.13：主板股票价格涨跌幅限制比例为 10%，创业板股票为 20%。
- 3.3.15：首次公开发行上市后的前五个交易日不实行价格涨跌幅限制；重新上市首日、退市整理期首日等也不实行。
- 3.3.19：涨跌幅限制价格、有效申报价格范围的计算结果按四舍五入原则取至申报价格最小变动单位。
- 4.5.5：主板风险警示股票价格涨跌幅限制比例为 5%；创业板风险警示股票、退市整理股票为 20%。

### 6.2 深交所 2026 版

- 3.3.13：主板股票价格涨跌幅限制比例为 10%，创业板股票为 20%。
- 3.3.15：首次公开发行上市后的前五个交易日不实行价格涨跌幅限制。
- 3.3.19：计算与舍入规则同 2023 版。
- 4.5 风险警示板章节未再单列 ST/风险警示股票涨跌幅比例；草稿按 3.3.13 一般规则处理，已在记录 notes 中标注，需人工复核确认无其他特别规定。

### 6.3 上交所 2023 版

- 3.3.13：股票、基金交易实行价格涨跌幅限制，比例为 10%。
- 3.3.17：涨跌幅限制价格、有效申报价格范围的计算结果按四舍五入原则取至申报价格最小变动单位。
- 4.4.10：风险警示股票价格的涨跌幅限制为 5%，退市整理股票为 10%。

### 6.4 上交所 2026 版

- 3.3.13：股票、基金交易实行价格涨跌幅限制，比例为 10%。
- 3.3.17：计算与舍入规则同 2023 版。
- 4.4 风险警示板章节未再单列 ST 比例；《上海证券交易所交易规则（2026年修订）》起草说明（附件2）明确主板风险警示股票涨跌幅限制比例由 5% 调整为 10%，故草稿按 10% 处理并待人工复核。

## 7. 生成的规则记录数

共 12 条：

| 交易所 | 板块 | 普通/风险警示 | 版本 | 区间 | 比例 |
| --- | --- | --- | --- | --- | --- |
| SZ | main | 普通 | 2023版 | 2025-07-27..2026-07-05 | 0.10 |
| SZ | main | 风险警示 | 2023版 | 2025-07-27..2026-07-05 | 0.05 |
| SZ | main | 普通 | 2026版 | 2026-07-06..2026-07-27 | 0.10 |
| SZ | main | 风险警示 | 2026版 | 2026-07-06..2026-07-27 | 0.10 |
| SZ | growth | 普通 | 2023版 | 2025-07-27..2026-07-05 | 0.20 |
| SZ | growth | 风险警示 | 2023版 | 2025-07-27..2026-07-05 | 0.20 |
| SZ | growth | 普通 | 2026版 | 2026-07-06..2026-07-27 | 0.20 |
| SZ | growth | 风险警示 | 2026版 | 2026-07-06..2026-07-27 | 0.20 |
| SH | main | 普通 | 2023版 | 2025-07-27..2026-07-05 | 0.10 |
| SH | main | 风险警示 | 2023版 | 2025-07-27..2026-07-05 | 0.05 |
| SH | main | 普通 | 2026版 | 2026-07-06..2026-07-27 | 0.10 |
| SH | main | 风险警示 | 2026版 | 2026-07-06..2026-07-27 | 0.10 |

## 8. 每条规则的来源条款

| record_id | 覆盖股票 | 覆盖区间 | 正式文件 | 条款 | 需要原因 |
| --- | --- | --- | --- | --- | --- |
| draft-szse-main-nonst-2023 | 深市主板6只 | 2025-07-27..2026-07-05 | szse_trading_rules_2023.pdf | 3.3.13、3.3.19 | 2023版覆盖窗口前半段普通股票 |
| draft-szse-main-st-2023 | 深市主板ST/*ST | 2025-07-27..2026-07-05 | szse_trading_rules_2023.pdf | 4.5.5、3.3.19 | 主板风险警示股票5% |
| draft-szse-main-nonst-2026 | 深市主板6只 | 2026-07-06..2026-07-27 | szse_trading_rules_2026.pdf | 3.3.13、3.3.19 | 2026版覆盖窗口后半段普通股票 |
| draft-szse-main-st-2026 | 深市主板ST/*ST | 2026-07-06..2026-07-27 | szse_trading_rules_2026.pdf | 3.3.13、3.3.19 | 2026版无独立ST比例，按一般规则10% |
| draft-szse-growth-nonst-2023 | 300274、300433 | 2025-07-27..2026-07-05 | szse_trading_rules_2023.pdf | 3.3.13、3.3.19 | 创业板普通股票20% |
| draft-szse-growth-st-2023 | 创业板ST/*ST | 2025-07-27..2026-07-05 | szse_trading_rules_2023.pdf | 4.5.5、3.3.19 | 创业板风险警示股票20% |
| draft-szse-growth-nonst-2026 | 300274、300433 | 2026-07-06..2026-07-27 | szse_trading_rules_2026.pdf | 3.3.13、3.3.19 | 创业板普通股票20% |
| draft-szse-growth-st-2026 | 创业板ST/*ST | 2026-07-06..2026-07-27 | szse_trading_rules_2026.pdf | 3.3.13、3.3.19 | 2026版无独立ST比例，按一般规则20% |
| draft-sse-main-nonst-2023 | 沪市主板8只 | 2025-07-27..2026-07-05 | sse_trading_rules_2023.docx | 3.3.13、3.3.17 | 上交所主板普通股票10% |
| draft-sse-main-st-2023 | 沪市主板ST/*ST | 2025-07-27..2026-07-05 | sse_trading_rules_2023.docx | 4.4.10、3.3.17 | 风险警示股票5% |
| draft-sse-main-nonst-2026 | 沪市主板8只 | 2026-07-06..2026-07-27 | sse_trading_rules_2026.docx | 3.3.13、3.3.17 | 2026版普通股票10% |
| draft-sse-main-st-2026 | 沪市主板ST/*ST | 2026-07-06..2026-07-27 | sse_trading_rules_2026.docx | 3.3.13、3.3.17、起草说明附件2 | 风险警示股票由5%调整为10% |

## 9. 日期覆盖矩阵

| exchange | board | is_st | effective_from | effective_to | limit_ratio | source_file | article_number | coverage_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SZ | main | false | 2025-07-27 | 2026-07-05 | 0.10 | szse_trading_rules_2023.pdf | 3.3.13/3.3.19 | covered |
| SZ | main | true | 2025-07-27 | 2026-07-05 | 0.05 | szse_trading_rules_2023.pdf | 4.5.5/3.3.19 | covered |
| SZ | main | false | 2026-07-06 | 2026-07-27 | 0.10 | szse_trading_rules_2026.pdf | 3.3.13/3.3.19 | covered |
| SZ | main | true | 2026-07-06 | 2026-07-27 | 0.10 | szse_trading_rules_2026.pdf | 3.3.13/3.3.19 | covered |
| SZ | growth | false | 2025-07-27 | 2026-07-05 | 0.20 | szse_trading_rules_2023.pdf | 3.3.13/3.3.19 | covered |
| SZ | growth | true | 2025-07-27 | 2026-07-05 | 0.20 | szse_trading_rules_2023.pdf | 4.5.5/3.3.19 | covered |
| SZ | growth | false | 2026-07-06 | 2026-07-27 | 0.20 | szse_trading_rules_2026.pdf | 3.3.13/3.3.19 | covered |
| SZ | growth | true | 2026-07-06 | 2026-07-27 | 0.20 | szse_trading_rules_2026.pdf | 3.3.13/3.3.19 | covered |
| SH | main | false | 2025-07-27 | 2026-07-05 | 0.10 | sse_trading_rules_2023.docx | 3.3.13/3.3.17 | covered |
| SH | main | true | 2025-07-27 | 2026-07-05 | 0.05 | sse_trading_rules_2023.docx | 4.4.10/3.3.17 | covered |
| SH | main | false | 2026-07-06 | 2026-07-27 | 0.10 | sse_trading_rules_2026.docx | 3.3.13/3.3.17 | covered |
| SH | main | true | 2026-07-06 | 2026-07-27 | 0.10 | sse_trading_rules_2026.docx | 3.3.13/3.3.17/起草说明附件2 | covered |

## 10. 区间冲突检查

- 同 `exchange/board/is_st` 分组内无重叠；相邻记录以 `2026-07-05 + 1 = 2026-07-06` 无缝衔接。
- 每个分组从 `2025-07-27` 覆盖到 `2026-07-27`，无缺口。
- 未包含科创板、北交所；未包含样例数据；未写入窗口内未发生的 IPO/上市初期规则。

## 11. 股票覆盖

16 只样本全部覆盖：

- 深交所主板：000100、002067、002129、002230、002361、002600。
- 深交所创业板：300274、300433。
- 上交所主板：600231、600438、600763、601012、601500、601636、603259、603799。

S15-14 三个样本均可解析唯一规则：002067=2026-07-09、002361=2026-07-10、002600=2026-06-30。

## 12. 仍需人工填写的字段

- `reviewer`（每条记录）
- `reviewed_at`（dataset.yml）
- `source_registry.yml` 与 `dataset.yml` 中上交所精确官方附件 URL
- `retrieved_at` 的真实值（当前为 `2026-08-06T00:00:00+08:00` 占位）
- 深交所 2023 版规则精确施行日（本地正文仅写“首只主板注册制股票上市首日”，草稿未推断具体日期）
- 2026 版深交所/上交所 ST 比例是否还有其他特别规定（当前按一般条款处理并已标注）

## 13. 仍需双人复核的项目

- 来源 A 级判定与来源链完整性。
- 每条记录的比例、条款号、生效/废止日期。
- 深交所2023版反向页序下条款引用是否正确。
- 2026 版 ST 比例处理口径。
- 正式构建前将 `review_status` 从 `pending` 改为 `approved` 并填写双人复核签名。

## 14. validate-only 与发布门禁

```text
source_chain_complete                 = false（上交所精确URL待补）
date_coverage_complete                = true
all_hashes_registered                 = true
all_rules_supported_by_official_text  = true
manual_review_complete                = false
```

由于 `source_chain_complete=false` 且 `manual_review_complete=false`，本轮不运行
`stage8-rules-build --validate-only`。技术内容校验已就绪，人工审批门禁仍阻断 validate-only。
项目验证器要求 `review_status=approved`、`reviewer` 与 `reviewed_at` 非空；草稿保持 `pending`
并留空签名是正确行为，不得为通过校验而伪造批准。

## 15. 测试结果

```text
python -m compileall -q src tests run_pipeline.py
退出码：0

python -m pytest -q -k "stage8_manual or authoritative or limit_rule" --disable-warnings
结果：1 failed, 53 passed
失败项：test_default_cli_fails_closed_without_real_dataset
原因：该测试假定默认 dataset 目录没有真实 dataset.yml；本轮按任务要求生成了草稿 dataset.yml，
      导致默认 CLI 不再报 dataset_manifest_missing。业务代码与测试期望均未修改。

排除该项后：
python -m pytest -q -k "stage8_manual or authoritative or limit_rule" \
  --deselect tests/test_stage8_manual_import.py::test_default_cli_fails_closed_without_real_dataset
结果：53 passed
```

## 16. 生成的草稿文件

```text
data/manual/stage8/limit_rules/source_registry.yml
data/manual/stage8/limit_rules/authoritative_limit_rules.csv
data/manual/stage8/limit_rules/limit_rules.csv（实现实际读取）
data/manual/stage8/limit_rules/dataset.yml
data/manual/stage8/limit_rules/review_checklist.md
data/manual/stage8/limit_rules/rules_source_hashes.csv（已补录新增两文件）
docs/stage8_limit_rule_csv_draft_report.md（本报告）
```

## 17. 精确下一步 PowerShell 命令

### 17.1 人工补全后（不得在本轮执行）

先补录上交所精确官方附件 URL、真实 `retrieved_at`，完成双人复核并填写 `reviewer`/`reviewed_at`，
将 `dataset.yml` 与 CSV 的 `review_status` 改为 `approved` 后执行：

```powershell
& ".\.venv\Scripts\python.exe" run_pipeline.py stage8-rules-build `
  --as-of-date 2026-07-27 `
  --dataset-dir "data\manual\stage8\limit_rules" `
  --validate-only `
  --log-level INFO
```

### 17.2 当前禁止执行的命令

```text
stage8-rules-build（正式发布）
stage8-status-build（正式发布）
stage8-preflight
stage8-rebuild
stage15-rerun
stage15-s14-reverify
```

本轮未执行 `git add`、`git commit`、`git push`，未修改业务代码和测试期望。
