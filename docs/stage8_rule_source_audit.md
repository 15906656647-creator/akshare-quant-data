# Stage8 权威涨跌停规则材料审计报告

> 审计日期：2026-08-06
> 分支：`feature/stage15-authoritative-sources`
> run_id：`e9a2d920-c4e2-42f4-b738-edf215c15fd1`
> 基线日期 / as_of_date：`2026-07-27`
> 审计范围：`data/manual/stage8/limit_rules/sources/` 全部 23 个规则材料文件
> 本项目仅用于研究与测试，不构成投资建议。

## 1. 审计结论

```text
项目是否需要深交所2023版：部分需要（交易规则2023版必需；主板/创业板上市规则2023版不需要）
项目是否需要深交所2024版：不需要（主板/创业板上市规则2024版均已在2025-04-25前被2025版废止）
```

关键证据来自本地 `szse_trading_rules_2026_notice.pdf`（深交所官方通知网页保存件）与
`szse_trading_rules_2026.pdf`（官方正文附则 10.9）：

- 《深圳证券交易所交易规则（2026年修订）》（深证上〔2026〕551号）自 **2026-07-06** 起施行。
- 《深圳证券交易所交易规则（2023年修订）》（深证上〔2023〕98号，2023-02-17 发布）**同时废止**。
- Stage8 正式统计窗口为 **2025-07-27 至 2026-07-27**，其中
  `2025-07-27..2026-07-05` 必须由 2023 版交易规则覆盖，
  `2026-07-06..2026-07-27` 由 2026 版覆盖。

因此：

| 版本 | 结论 | 依据 |
| --- | --- | --- |
| 深交所交易规则2023版 | **必需** | 正式窗口前 11 个多月（2025-07-27 至 2026-07-05）的唯一有效版本；本地缺失 |
| 深交所交易规则2026版 | **必需** | 2026-07-06 起生效并覆盖 S15-14 样本 002067/002361 事件日；本地已有官方正文 |
| 深交所主板上市规则2023版 | **不需要** | 2024-04-30 已由 2024 版取代；正式窗口开始前已失效；涨跌幅比例不以上市规则判定，窗口内无 IPO 首日事件 |
| 深交所创业板上市规则2023版 | **不需要** | 2024-04-30 已由 2024 版取代；正式窗口开始前已失效 |
| 深交所主板上市规则2024版 | **不需要** | 2025-04-25 前后已由 2025 版（深证上〔2025〕393号）取代 |
| 深交所创业板上市规则2024版 | **不需要** | 2025-04-25 前后已由 2025 版（深证上〔2025〕394号）取代 |
| 深交所2025版相关规则 | **可选** | 主板/创业板上市规则2025版在窗口早期有效，仅作 ST/风险警示口径佐证可选；交易规则无2025版（2023 直接过渡到 2026） |
| 深交所2026版相关规则 | **必需（交易规则）/可选（上市规则）** | 交易规则 2026 版覆盖窗口末 22 天；主板/创业板上市规则 2026 版本地已有，非涨跌幅判定必需 |

## 2. 日期证据（直接查询数据库与配置）

```text
stage8_input_min_date      = 2023-07-27
stage8_input_max_date      = 2026-07-27
stage8_event_min_date      = 2025-07-28
stage8_event_max_date      = 2026-07-27
stage8_formal_event_min    = 2025-07-29
stage8_formal_event_max    = 2026-07-13
stage15_sample_min_date    = 2026-06-30
stage15_sample_max_date    = 2026-07-10
s15_14_required_dates      = 002067:2026-07-09; 002361:2026-07-10; 002600:2026-06-30
```

来源：

- `database/akshare_data_test_stage5_repaired.duckdb`：`main.fact_stock_daily` raw/qfq 各 11602 行，
  min/max 均为 `2023-07-27/2026-07-27`，16 只股票。
- `database/stage15_s14_fix/3e8f2a0d-9b1c-4d2e-8f3a-1c2d3e4f5a6b/stage8_authoritative.duckdb`：
  `analysis.fact_limit_event` 3862 行（2025-07-28..2026-07-27），正式事件 77 条
  （涨停 66 条 2025-07-29..2026-07-10，跌停 11 条 2025-09-19..2026-07-13）；
  `audit.stage8_run` 窗口 `2025-07-27..2026-07-27`。
- `database/stage15_s14_fix/s14_verification.md` 与 `reports/stage15_s14_fix/4f5e6d7c-8a9b-4c1d-9e2f-3a4b5c6d7e8f/cross_validation.csv`：
  S15-14 有效样本 3 个，事件日期如上。
- `database/akshare_features_stage7.duckdb`：feature 数据 2023-07-27..2026-07-27。
- 状态历史：16 只股票非 ST `2020-01-01..2026-07-27`，`000100` *ST `2007-05-08..2008-03-28`。

16 只股票板块：深交所主板 6 只（000100、002067、002129、002230、002361、002600），
深交所创业板 2 只（300274、300433），上交所主板 8 只（600231、600438、600763、601012、
601500、601636、603259、603799）；不含科创板、北交所。

正式窗口内不存在样本股票的 IPO 首日/上市初期事件（样本 IPO 均在 2015–2019 年），
因此主板/创业板上市规则的上市首日条款不是本次 Stage8 正式统计的必需输入。

## 3. 本地文件有效性

统计：`valid_official=9`，`auxiliary=10`，`suspicious=4`，`missing_required=1`。

| 文件名 | 格式有效 | 内容有效 | 版本正确 | 官方性 | 是否可作A级候选 | 主要问题 |
| --- | --- | --- | --- | --- | --- | --- |
| sse_main_listing_rules_2024.docx | 是 | 是（全文 98872 字符） | 是（2024年4月第十八次修订） | 是（内容含上证发〔2024〕51号） | 是（候选） | 缺下载 URL/日期来源链 |
| sse_main_listing_rules_2024_transition_notice.pdf | 是（2页） | 是（通知+过渡安排） | 是 | 是（官方网页保存件） | 否（B级辅助） | 网页打印件，非规则正文 |
| sse_main_listing_rules_2026.docx | 是 | 是（全文 104072 字符） | 是（2026年4月第二十次修订） | 是（内容含上证发〔2026〕42号） | 是（候选） | 缺来源链 |
| sse_main_listing_rules_2026_notice.pdf | 是（58页） | 部分（含全文但页序非文档顺序） | 是 | 是（官方网页打印件） | 否（B级辅助） | 物理页序混乱，首页为 3.2.2、文号页在第 8 页，需人工复核或重新下载 |
| sse_star_listing_rules_2024.docx | 是 | 是（全文 69095 字符） | 是 | 是（内容含上证发〔2024〕52号） | 是（候选） | 缺来源链 |
| sse_star_listing_rules_2024_transition_notice.pdf | 是（2页） | 是（通知+过渡安排） | 是 | 是（官方网页保存件） | 否（B级辅助） | 网页打印件，非规则正文 |
| sse_star_listing_rules_2026.docx | 是 | 是（全文 79446 字符） | 是 | 是（内容含上证发〔2026〕43号） | 是（候选） | 缺来源链 |
| sse_star_listing_rules_2026_notice.pdf | 是（46页） | 部分（含全文但页序非文档顺序） | 是 | 是（官方网页打印件） | 否（B级辅助） | 物理页序混乱 |
| sse_trading_rules_2023.docx.docx | 是 | 是（全文 20658 字符） | 是（2023年2月第十一次修订） | 是（内容含上证发〔2023〕32号） | 是（候选） | 文件名为重复 `.docx.docx`；需复核生效日 |
| sse_trading_rules_2023_deferred_articles.docx | 是 | 是（暂缓实施条文） | 是 | 是（官方附件） | 辅助（A级附件） | 不得单独替代正文 |
| sse_trading_rules_2023_explanation.docx | 是 | 是（起草说明） | 是 | 是（官方附件） | 辅助（A级附件） | 不得单独替代正文 |
| sse_trading_rules_2023_notice.pdf | 是（15页） | 部分（正文片段且页序混乱、末尾截断） | 是 | 是（官方网页打印件） | 否（B级辅助） | 不能作为规范正文 PDF；正文以 DOCX 为准 |
| sse_trading_rules_2026.docx | 是 | 是（全文 20827 字符） | 是（2026年4月第十二次修订） | 是（内容含上证发〔2026〕41号） | 是（候选） | 缺来源链；注意主板风险警示股票 5%→10% |
| sse_trading_rules_2026_deferred_articles.docx | 是 | 是（暂缓实施条文） | 是 | 是（官方附件） | 辅助（A级附件） | 不得单独替代正文 |
| sse_trading_rules_2026_explanation.docx | 是 | 是（起草说明） | 是 | 是（官方附件） | 辅助（A级附件） | 不得单独替代正文 |
| sse_trading_rules_2026_notice.pdf | 是（15页） | 部分（正文片段且页序混乱、末尾截断） | 是 | 是（官方网页打印件） | 否（B级辅助） | 不能作为规范正文 PDF；正文以 DOCX 为准 |
| szse_chinext_listing_rules_2026.pdf | 是（159页） | 是 | 是（2026年4月第十一次修订） | 是（官方正文，附件 URL 一致） | 是（候选） | 缺来源链记录 |
| szse_chinext_listing_rules_2026_notice.pdf | 是（1页） | 是（通知） | 是 | 是（官方网页保存件，含附件 URL） | 否（B级辅助） | 网页打印件，非规则正文 |
| szse_main_listing_rules_2026.pdf | 是（198页） | 是 | 是（2026年4月第十七次修订） | 是（官方正文，附件 URL 一致） | 是（候选） | 缺来源链记录 |
| szse_main_listing_rules_2026_notice.pdf | 是（2页） | 是（通知） | 是 | 是（官方网页保存件，含附件 URL） | 否（B级辅助） | 网页打印件，非规则正文 |
| szse_trading_rules_2026.pdf | 是（40页） | 是（全文可解析，含 3.3.13/3.3.15/4.5 等条款） | 是 | 是（官方正文，附件 URL 一致） | 是（候选） | 缺来源链记录 |
| szse_trading_rules_2026_explanation.pdf | 是（3页） | 是（修订说明） | 是 | 是（官方附件） | 辅助（A级附件） | 不得单独替代正文 |
| szse_trading_rules_2026_notice.pdf | 是（1页） | 是（通知） | 是 | 是（官方网页保存件，含附件 URL） | 否（B级辅助） | 网页打印件，非规则正文 |

所有 23 个文件 SHA-256 均可计算且互不重复；无同内容不同名文件、无同名不同内容文件。
详细字段见 `reports/stage8_rule_source_audit/<run_id>/file_inventory.csv`。

## 4. 缺失材料

### P0：缺失后立即阻断

| 文件 | 文号/版本 | 影响日期 | 影响股票/板块 | 阻断 Stage8 | 阻断 S15-14 |
| --- | --- | --- | --- | --- | --- |
| 深圳证券交易所交易规则（2023年修订）正文 | 深证上〔2023〕98号，2023年修订 | 2025-07-27 至 2026-07-05 | 深市主板 6 只、创业板 2 只；S15-14 样本 002600（2026-06-30） | 是 | 是 |

### P1：正式构建前必须补齐（辅助证据）

| 文件 | 说明 |
| --- | --- |
| 深交所交易规则（2023年修订）发布通知官方页面/PDF | 正文附则通常已含生效/废止日期；通知仅作来源链辅助，不能替代正文 |

### P2：建议保留的辅助材料

- 深交所主板/创业板股票上市规则（2025年修订）正文与通知（深证上〔2025〕393/394号）：
  可选佐证 ST/风险警示口径，不阻断。
- 上交所 4 个规则 PDF（`sse_*_notice.pdf`）建议重新下载官方正文 PDF 或人工核对页序；
  上交所正式正文可由 6 个 DOCX 提供。

## 5. 分级处置

### 方案A（可列为 A 级候选）

本地 `szse_trading_rules_2026.pdf`、`szse_main_listing_rules_2026.pdf`、
`szse_chinext_listing_rules_2026.pdf` 及 6 个上交所规则 DOCX 均为完整官方正文，即使原下载
链接失效，只要补足来源链即可列为 A 级候选。来源链必须包含：

- 原始下载 URL（深交所文件可填官方附件 URL，见 `file_inventory.csv`；上交所文件待补录）；
- 下载日期；
- 本地 SHA-256；
- 官方发布通知或废止目录（深交所通知网页保存件已含废止关系）；
- 文件内部文号与标题；
- 双人人工审核记录。

### 方案B（只能作 B 级辅助）

深交所 3 个通知网页保存件、上交所 4 个过渡/失效通知网页保存件：可证明文号、发布日期、
生效日期、废止关系与过渡安排，不能提供规则正文。

### 方案D（完全缺失）

《深圳证券交易所交易规则（2023年修订）》正文（深证上〔2023〕98号）必须向深交所申请或从
官网规则库下载。建议工单/邮件说明：项目需要 2023 版交易规则官方正文用于覆盖
2025-07-27 至 2026-07-05 的正式分析窗口及 S15-14 样本 002600 事件日（2026-06-30），
并注明 2026 版通知已列明该版本于 2026-07-06 废止。

## 6. 数据契约能力判断

```text
can_prepare_source_registry     = true  （现有有效候选文件可开始登记草稿；A级标记须先补来源链与双人复核）
can_prepare_draft_rule_csv      = true  （可为已覆盖区间起草；不得发布）
can_mark_approved               = false
can_run_rules_validate_only     = false （覆盖窗口缺 2023 版交易规则，覆盖校验必失败）
can_run_rules_publish           = false
```

禁止仅因文件能打开就置为 `approved`；缺 2023 版正文前，任何正式构建命令保持 fail-closed。

## 7. 后续操作

1. 获取《深圳证券交易所交易规则（2023年修订）》官方正文（深证上〔2023〕98号），
   放入 `data/manual/stage8/limit_rules/sources/`，计算 SHA-256。
2. 为上交所 6 个 DOCX 与深交所 3 个规则 PDF 补录来源链（URL、下载日期、SHA-256）。
3. 按 `dataset.schema.yml` 起草 `limit_rules.csv`：
   - SZSE 主板普通 ±10%、ST ±5%：2025-07-27..2026-07-05 引用 2023 版交易规则；
     2026-07-06 起引用 2026 版交易规则（ST 比例需以 2023 版正文/上市规则风险警示章节复核，
     不得仅凭旧配置推断）。
   - SZSE 创业板普通/ST ±20%：引用交易规则/创业板交易特别规定。
   - 上市初期/无涨跌幅规则：仅样本实际 IPO 日需要（2015–2019，窗口外）。
4. 完成双人复核后执行：
   `python run_pipeline.py stage8-rules-build --as-of-date 2026-07-27 --validate-only`
5. 校验 PASS 后再执行 `stage8-status-build --validate-only`、`stage8-preflight`；
   全部 PASS 后才允许重建 Stage8、重跑 Stage15 与 S15-14。

在 2023 版交易规则正文补齐并完成来源链/复核之前，不得：

- 运行 `stage8-rules-build`（含 `--validate-only`）；
- 运行 `stage8-status-build`、`stage8-rebuild`、`stage15-rerun`、`stage15-s14-reverify`；
- 进入 Stage16。

## 8. 当前门禁状态

```text
规则文件审计：PARTIAL
真实A级规则数据：BLOCKED
可运行stage8-rules-build --validate-only：NO
可正式发布规则数据：NO
可执行Stage8重建：NO
可重跑S15-14：NO
可进入Stage16：NO
```

## 9. 输出文件

```text
docs/stage8_rule_source_audit.md                                  （本报告）
reports/stage8_rule_source_audit/<run_id>/file_inventory.csv
reports/stage8_rule_source_audit/<run_id>/file_validation.json
reports/stage8_rule_source_audit/<run_id>/date_coverage.json
reports/stage8_rule_source_audit/<run_id>/required_versions.json
reports/stage8_rule_source_audit/<run_id>/missing_files.csv
reports/stage8_rule_source_audit/<run_id>/audit_summary.json
reports/stage8_rule_source_audit/<run_id>/extracted_text/          （PDF/DOCX 提取文本）
reports/stage8_rule_source_audit/<run_id>/render/                  （PDF 首页/末页渲染）
reports/stage8_rule_source_audit/<run_id>/tools/                   （本次审计临时工具，不入库）
```

本轮未暂存、未提交任何文件；阶段0冻结文件哈希经复验与
`docs/stage0_4_final_acceptance.md` 记录一致。
