# Stage 8 权威数据人工导入操作说明

本文档说明如何把人工收集并复核的正式涨跌停规则和证券状态历史导入项目，
供 `stage8-rules-build`、`stage8-status-build`、`stage8-preflight` 和
`stage8-rebuild` 使用。当前没有真实 A 级数据文件时，所有命令都会
fail-closed（非零退出且不发布），不会伪造或推测任何数据。

## 1. 需要人工获取哪些正式来源

规则历史需要交易所正式交易规则或官方规则摘要；状态历史需要交易所官方状态
公告、官方证券列表和官方公告检索结果。必须保存原始文件本身，不能只保存
二次整理的表格。

## 2. 哪些文件可以作为 A 级证据

- 交易所正式规则文件（沪深北交易所官网规则文本/PDF）。
- 交易所官方状态公告（含生效日期）。
- 交易所官方证券列表 + 官方公告检索证据包。
- 证监会指定披露平台的正式公告原文或可下载文件。

## 3. 哪些来源只能作为 B 级辅助证据

- 东方财富当前风险警示板/个股信息快照：仅当前状态交叉校验。
- 交易所当前证券列表单独使用：辅助上市日期与当前简称。
- 名称/简称变更记录单独使用：辅助线索，不能单独构成状态历史。

C 级不可使用：新浪曾用名列表（无生效日期）、空检索结果（不能证明无历史）、
失败接口。

## 4. 如何登记来源

把正式文件放入 `limit_rules/sources/` 或 `security_status/sources/`，然后
在对应目录的 `dataset.yml` 的 `sources` 列表登记
`file/document_id/document_date/source_name/reference/retrieved_at/grade/sha256`。
等级必须为 `A`。模板见两个子目录的 `source_registry.template.yml`。

## 5. 如何计算 SHA256

```powershell
Get-FileHash -Algorithm SHA256 .\sources\文件名.pdf | Select-Object Hash
```

把输出的小写 64 位哈希填入登记清单和每条记录的 `source_sha256`。

## 6. 如何填写规则历史

按 `limit_rules/dataset.schema.yml` 填写 `limit_rules.csv`：

- `market` 与 `exchange` 一致（SH/SZ/BJ）。
- `board` 取 `main/growth/star/bse`；`security_type` 取 `A_SHARE` 等。
- `rule_type` 取 `price_limit/st_price_limit/ipo_first_day/no_limit`。
- `limit_ratio` 为小数比例（`0.10` 表示 10%），上市首日规则可另填
  `limit_down_ratio`。
- 日期用 ISO 格式；`effective_to` 为空表示仍有效；区间为闭区间。

## 7. 如何填写证券状态历史

按 `security_status/dataset.schema.yml` 填写 `security_status_history.csv`：

- 每个股票需要 `ST` 与 `LISTING` 两条类型的状态区间。
- `ST` 取值 `NON_ST/ST/*ST/OTHER`；`LISTING` 取值
  `LISTED/SUSPENDED/DELISTED`。
- `announcement_date` 不得晚于使用日期。
- 非 ST 区间必须由正式证据支持，禁止凭当前快照或曾用名推断。

## 8. 如何进行双人或人工复核

使用两个子目录的 `review_checklist.template.md`，整理人填写后由两位复核人
独立核对来源、区间、覆盖和哈希，全部通过后才把 `review_status` 置为
`approved` 并在 `dataset.yml` 记录 `reviewed_at` 与复核人。

## 9. 如何执行 `--validate-only`

只校验、不发布：

```powershell
& ".\.venv\Scripts\python.exe" run_pipeline.py stage8-rules-build `
  --as-of-date 2026-07-27 --validate-only
& ".\.venv\Scripts\python.exe" run_pipeline.py stage8-status-build `
  --as-of-date 2026-07-27 --validate-only
& ".\.venv\Scripts\python.exe" run_pipeline.py stage8-preflight `
  --as-of-date 2026-07-27
```

## 10. 如何正式发布

数据集通过校验后，去掉 `--validate-only` 即发布清单与配置：

```powershell
& ".\.venv\Scripts\python.exe" run_pipeline.py stage8-rules-build `
  --as-of-date 2026-07-27 --run-id <uuid> `
  --output-dir database/stage15_s14_fix --output-config config/stage8_s14_fix.yml
& ".\.venv\Scripts\python.exe" run_pipeline.py stage8-status-build `
  --as-of-date 2026-07-27 --run-id <uuid> `
  --output-dir database/stage15_s14_fix --output-config config/stage8_s14_fix.yml
```

发布是原子写入：校验失败或写入失败不会留下半成品。

## 11. 如何重建 Stage 8

```powershell
& ".\.venv\Scripts\python.exe" run_pipeline.py stage8-rebuild `
  --as-of-date 2026-07-27 --run-id <uuid> `
  --source-database database/akshare_data_test_stage5_repaired.duckdb
```

若 `config/stage8_s14_fix.yml` 不存在，命令会先从
`data/manual/stage8/limit_rules` 与 `data/manual/stage8/security_status`
组合校验并生成运行配置到本次运行的报告目录。

## 12. 如何重跑 Stage 15 和 S15-14

```powershell
& ".\.venv\Scripts\python.exe" run_pipeline.py stage15-rerun `
  --as-of-date 2026-07-27 `
  --stage8-database database/stage15_s14_fix/<uuid>/stage8_authoritative.duckdb `
  --cross-validation-symbols 002067 002361 002600 --run-id <uuid>

& ".\.venv\Scripts\python.exe" run_pipeline.py stage15-s14-reverify `
  --as-of-date 2026-07-27 `
  --stage8-database database/stage15_s14_fix/<uuid>/stage8_authoritative.duckdb `
  --stage15-reports-dir reports/stage15_s14_fix/<uuid> --run-id <uuid>
```

在真实 A 级文件就绪并通过校验之前，`stage8-preflight` 返回
`BLOCKED`/`FAILED`，S15-14 保持 `BLOCKED`，阶段 15 尚未完全通过，
阶段 16 禁止进入。

## 目录结构

```text
data/manual/stage8/
  README.md
  limit_rules/       # authoritative_limit_rules 契约
  security_status/   # authoritative_security_status_history 契约
```

真实 `dataset.yml`、记录 CSV 与 `sources/*` 被 `.gitignore` 排除；模板、
虚构示例、README、校验说明、来源登记模板和人工审核清单随仓库提交。
