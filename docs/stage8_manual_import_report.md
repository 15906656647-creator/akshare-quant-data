# Stage8 权威数据人工导入能力实施报告

> 报告日期：2026-08-05
> 分支：`feature/stage15-authoritative-sources`
> 基线日期：`2026-07-27`
> 项目用途：研究与测试，不构成投资建议。

## 1. 结论

```text
权威数据导入能力：PASS
权威数据就绪状态：BLOCKED
S15-14：BLOCKED
阶段15：尚未完全通过
Stage16：禁止进入
```

本任务实现的是可审计的人工权威数据导入与验证能力，不是把探测结论改为
通过。当前探测仍为 A 级 0、B 级 4、C 级 5，仓库中没有真实 A 级数据文件，
因此正式规则/状态构建、Stage8 重建、Stage15 重跑和 S15-14 判定继续
fail-closed。

## 2. 修改文件

| 文件 | 说明 |
| --- | --- |
| `src/akshare_data_test/stage8_manual.py` | 新增：人工权威数据导入、八步校验与组合覆盖 |
| `src/akshare_data_test/limit_rules.py` | 扩展 `LimitRule`/`SecurityStatus` 审计字段；状态按 ST/LISTING 类型解析合并 |
| `src/akshare_data_test/stage8_build.py` | 配置加载器接受 `dataset_manifest`/`manual_datasets` 与审计字段 |
| `src/akshare_data_test/stage8_authoritative.py` | 规则/状态构建支持 `dataset_dir`、原子发布、校验/溯源输出 |
| `src/akshare_data_test/cli.py` | 四个 Stage8 命令接入人工数据集目录与组合校验 |
| `sql/stage8_schema.sql` | 规则/状态参考表补齐审计列并支持旧库迁移 |
| `config/stage8.yml` | 增加 `manual_datasets` 目录配置 |
| `.gitignore` | 排除真实人工数据集，保留模板/示例 |
| `tests/test_stage8_manual_import.py` | 新增 26 项人工导入定向测试 |
| `tests/test_stage15_s14_fix.py` | 修复对不存在配置文件的引用，改为契约测试 |
| `data/manual/stage8/**` | 字段模板、虚构示例、README、校验说明、来源登记模板、复核清单 |
| `docs/stage8_manual_import_report.md` | 本报告 |

## 3. 数据契约

两个契约与目录一一对应：

- `authoritative_limit_rules`：`data/manual/stage8/limit_rules`
- `authoritative_security_status_history`：`data/manual/stage8/security_status`

规则历史字段：`market/exchange/board/security_type/rule_type/limit_ratio/
effective_from/effective_to/source_name/source_document_id/
source_document_date/source_reference/retrieved_at/raw_file/source_sha256/
review_status/reviewer/notes`，另支持 `record_id/symbol/limit_down_ratio/
tick_size/price_precision/rounding_rule/rule_version/verified_at`。

状态历史字段：`symbol/exchange/board/status_type/status_value/
effective_from/effective_to/announcement_date/source_name/
source_document_id/source_reference/retrieved_at/raw_file/source_sha256/
review_status/reviewer/notes`，另支持 `record_id/listing_date/
delisting_date/status_version`。

日期使用 ISO `YYYY-MM-DD`；生效区间采用仓库统一规范闭区间
`[effective_from, effective_to]`，`effective_to` 为空表示仍有效。每条记录必须
追溯到 `sources/` 下的原始正式文件，且 SHA-256 必须匹配。

## 4. 模板文件

`data/manual/stage8/README.md` 与两个子目录提供：

- `dataset.schema.yml`：字段模板与取值规范
- `dataset.example.yml`：明确标记的虚构样例清单
- `limit_rules.example.csv` / `security_status_history.example.csv`：虚构样例记录
- `source_registry.template.yml`：来源登记模板
- `review_checklist.template.md`：双人复核清单
- `validation_notes.md`：八步校验说明
- `sources/README.md`：原始文件目录说明与哈希命令

正式构建只读取 `dataset.yml` 与固定记录文件名，绝不读取 `*.example.*`。

## 5. 校验规则

每个数据集按以下阶段校验，全部通过才能发布：

1. 格式验证：文件存在可解析、列集合精确、无重复 `record_id`、非空。
2. 字段验证：枚举、ISO 日期、比例、证券代码、SHA-256、审核状态、复核人。
3. 来源验证：`raw_file` 已登记、登记等级必须为 A、拒绝曾用名推断来源。
4. 哈希验证：原始文件存在且 SHA-256 与登记一致。
5. 区间验证：生效区间合法、公告日期不晚于使用日期、覆盖分析窗口。
6. 冲突验证：同市场/板块/证券类型规则无重叠；同股票同状态类型无重叠。
7. 覆盖验证：规则覆盖窗口内每天恰好一条；16 只样本每天唯一 ST 与 LISTING；
   组合校验覆盖 S15-14 抽样股票和事件日期。
8. 发布：校验通过后原子写入清单、运行配置、校验报告与溯源 JSON；失败
   不留半成品。

## 6. CLI 使用方式

```powershell
# 只校验（不发布）
& ".\.venv\Scripts\python.exe" run_pipeline.py stage8-rules-build `
  --as-of-date 2026-07-27 --validate-only
& ".\.venv\Scripts\python.exe" run_pipeline.py stage8-status-build `
  --as-of-date 2026-07-27 --validate-only

# 正式发布清单与配置
& ".\.venv\Scripts\python.exe" run_pipeline.py stage8-rules-build `
  --as-of-date 2026-07-27 --run-id <uuid> `
  --output-dir database/stage15_s14_fix `
  --output-config config/stage8_s14_fix.yml
& ".\.venv\Scripts\python.exe" run_pipeline.py stage8-status-build `
  --as-of-date 2026-07-27 --run-id <uuid> `
  --output-dir database/stage15_s14_fix `
  --output-config config/stage8_s14_fix.yml

# 组合校验预检（只读）
& ".\.venv\Scripts\python.exe" run_pipeline.py stage8-preflight `
  --as-of-date 2026-07-27

# 重建 Stage 8（配置缺失时自动从人工数据集生成）
& ".\.venv\Scripts\python.exe" run_pipeline.py stage8-rebuild `
  --as-of-date 2026-07-27 --run-id <uuid>
```

规则/状态构建默认读取 `data/manual/stage8/limit_rules` 与
`data/manual/stage8/security_status`；也可用 `--config` 指向已经发布合并的
YAML 配置。

## 7. 定向测试

`tests/test_stage8_manual_import.py` 26 项 + 相关回归：

```text
26 passed in 2.89s      # 新增人工导入测试
134 passed in 14.42s    # stage8/stage15/S15-14 相关测试
54 passed in 26.71s     # Stage 8/15 数据库集成与 CLI
```

覆盖：合法规则/状态通过、缺失来源字段、原始文件缺失、SHA-256 不匹配、
未批准数据、无效日期、区间重叠、冲突规则、当前快照冒充历史、曾用名推断
状态、B 级来源、示例数据隔离、`--validate-only` 不发布、原子写入无半成品、
Windows 中文路径、ST/LISTING 合并解析、组合数据集、规则/状态构建往返、
as-of-date 一致性、未知列失败、默认 CLI fail-closed。

## 8. 全量测试

```text
917 passed in 345.45s (0:05:45)
```

全量回归无失败，阶段 1 至 15 的既有测试无回归。

## 9. 当前是否存在真实 A 级数据

**否**。数据源探测结论仍为 A 级 0、B 级 4、C 级 5；
`authoritative_rule_source_ready = false`、
`authoritative_status_source_ready = false`。

## 10. 是否允许执行规则构建

**否**。`can_continue_rules_build = false`；默认命令因缺少真实 `dataset.yml`
返回非零且不发布。

## 11. 是否允许执行状态构建

**否**。`can_continue_status_build = false`；默认命令因缺少真实数据集返回
非零且不发布。

## 12. 是否允许重建 Stage 8

**否**。没有真实 A 级规则与状态历史，`stage8-rebuild` 的组合校验保持
`BLOCKED`/`FAILED`，不会生成正式 Stage8 数据。

## 13. 是否允许重跑 S15-14

**否**。S15-14 依赖正式 Stage8 事件；在真实权威数据就绪前保持
`BLOCKED`，阶段 15 尚未完全通过。

## 14. 用户下一步需要人工准备的具体材料

1. 沪深北交易所正式涨跌停规则原文（PDF/官方网页快照），含生效/废止日期。
2. 16 只样本股票在 `2025-07-27` 至 `2026-07-27` 的正式状态证据：官方状态
   公告（含生效日期）、官方证券列表、官方公告检索结果。
3. 将原始文件放入两个 `sources/` 目录，用 `Get-FileHash -Algorithm SHA256`
   计算哈希。
4. 按 `dataset.schema.yml` 填写 `limit_rules.csv` 与
   `security_status_history.csv`，覆盖全部 16 只股票。
5. 按 `source_registry.template.yml` 登记来源，等级只能填 `A`。
6. 按 `review_checklist.template.md` 完成双人复核，`review_status` 置为
   `approved`。
7. 执行 `--validate-only` 校验，全部 `PASS` 后正式发布并重建 Stage 8。
8. 重建通过后重跑 Stage 15 与 `stage15-s14-reverify`，有效样本 >= 2 且
   无 UNAVAILABLE/MISMATCH 才允许通过 S15-14。
