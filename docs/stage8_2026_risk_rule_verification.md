# Stage8 2026版风险警示涨跌幅记录专项权威核验

> 核验日期：2026-08-06
> 分支：`feature/stage15-authoritative-sources`
> run_id：`f41fa319-6b7e-4b19-940e-1e677513232c`
> as_of_date：`2026-07-27`
> 本项目仅用于研究与测试，不构成投资建议。

## 1. 结论

```text
深交所主板风险警示10%：VERIFIED
深交所创业板风险警示20%：VERIFIED
上交所主板风险警示10%：VERIFIED
来源链：INCOMPLETE
可进入人工双人复核：NO
可将review_status改为approved：NO
可运行stage8-rules-build --validate-only：NO
```

三条记录的最终比例均获本地正式正文与正式修订说明共同支持。来源链仍不完整：
上交所精确官方附件 URL 缺失，且所有文件均无真实下载/取得时间记录，`retrieved_at`
已按要求全部留空，因此暂不能进入人工双人复核或批准。

## 2. 核验记录

### 2.1 draft-szse-main-st-2026

| 项目 | 内容 |
| --- | --- |
| expected_ratio | 0.10 |
| verified_ratio | 0.10 |
| primary_source_file | sources/szse_trading_rules_2026.pdf |
| supporting_source_file | sources/szse_trading_rules_2026_explanation.pdf、sources/szse_trading_rules_2026_notice.pdf |
| article_number | 3.3.13、4.5.1、修订说明（五） |
| article_summary | 3.3.13 主板股票涨跌幅限制比例为 10%；4.5 风险警示板章节未单独设风险警示比例；修订说明明确主板风险警示股票价格涨跌幅限制比例由 5% 调整为 10%，与主板其他股票保持一致 |
| effective_from | 2026-07-06 |
| special_rule_found | false |
| deferred_rule_impact | none |
| verification_status | VERIFIED |
| blocking_reason | 无 |

### 2.2 draft-szse-growth-st-2026

| 项目 | 内容 |
| --- | --- |
| expected_ratio | 0.20 |
| verified_ratio | 0.20 |
| primary_source_file | sources/szse_trading_rules_2026.pdf |
| supporting_source_file | sources/szse_trading_rules_2026_explanation.pdf、sources/szse_trading_rules_2026_notice.pdf |
| article_number | 3.3.13、4.5.1、修订说明（五） |
| article_summary | 3.3.13 创业板股票涨跌幅限制比例为 20%；4.5 风险警示板章节未单独设风险警示比例；修订说明将风险警示股票比例与同板块普通股票保持一致，故创业板风险警示股票适用 20% |
| effective_from | 2026-07-06 |
| special_rule_found | false |
| deferred_rule_impact | none |
| verification_status | VERIFIED |
| blocking_reason | 无 |

### 2.3 draft-sse-main-st-2026

| 项目 | 内容 |
| --- | --- |
| expected_ratio | 0.10 |
| verified_ratio | 0.10 |
| primary_source_file | sources/sse_trading_rules_2026.docx |
| supporting_source_file | sources/sse_trading_rules_2026_explanation.docx、sources/sse_trading_rules_2026_deferred_articles.docx |
| article_number | 3.3.13、4.4.1、起草说明（三） |
| article_summary | 3.3.13 股票涨跌幅限制比例为 10%；4.4.1 风险警示板本节未作规定的适用本规则；起草说明明确主板风险警示股票价格涨跌幅限制比例由 5% 调整为 10% |
| effective_from | 2026-07-06 |
| special_rule_found | false |
| deferred_rule_impact | none（暂缓实施条文仅涉及 3.6.2/3.6.3/3.6.4/3.6.9/3.6.10 大宗交易条款） |
| verification_status | VERIFIED |
| blocking_reason | 无 |

## 3. 条款证据

### 3.1 深交所 2026 版

- 正文 `szse_trading_rules_2026.pdf`：
  - 3.3.13：主板股票价格涨跌幅限制比例为 10%，创业板股票为 20%。
  - 3.3.19：计算结果按四舍五入原则取至申报价格最小变动单位。
  - 4.5.1-4.5.7：风险警示股票在风险警示板交易，但未单独规定风险警示涨跌幅比例。
- 修订说明 `szse_trading_rules_2026_explanation.pdf`：
  - 明确“将主板风险警示股票价格涨跌幅限制比例由 5% 调整为 10%，与主板其他股票保持一致”。
- 通知 `szse_trading_rules_2026_notice.pdf`：
  - 文号深证上〔2026〕551号，2026-07-06 施行并废止 2023 版。

### 3.2 上交所 2026 版

- 正文 `sse_trading_rules_2026.docx`：
  - 3.3.13：股票、基金交易实行价格涨跌幅限制，比例为 10%。
  - 3.3.17：计算结果按四舍五入原则取至申报价格最小变动单位。
  - 4.4.1：风险警示股票在风险警示板交易，本节未作规定的适用本规则及其他有关规定；4.4 未再单列风险警示股票 5% 比例。
- 起草说明 `sse_trading_rules_2026_explanation.docx`：
  - 明确“将主板风险警示股票价格涨跌幅限制比例由 5% 调整为 10%，与主板其他股票保持一致”。
- 暂缓实施条文 `sse_trading_rules_2026_deferred_articles.docx`：
  - 仅涉及 3.6.2/3.6.3/3.6.4/3.6.9/3.6.10 大宗交易条款，不影响风险警示股票涨跌幅比例。

## 4. 来源链

`source_registry.yml` 已更新为 6 条 2026 版相关来源：

| source_key | local_file | 文件角色 | 官方页面/附件 | retrieved_at | SHA-256 前缀 |
| --- | --- | --- | --- | --- | --- |
| szse-trading-rules-2026 | sources/szse_trading_rules_2026.pdf | 规则正文（正式） | 页面+附件已登记 | 空 | 9b66f8b0 |
| szse-trading-rules-2026-explanation | sources/szse_trading_rules_2026_explanation.pdf | 修订说明（正式辅助） | 页面+附件已登记 | 空 | 3a309bf5 |
| szse-trading-rules-2026-notice | sources/szse_trading_rules_2026_notice.pdf | 发布通知（辅助） | 页面+附件已登记 | 空 | 998f785a |
| sse-trading-rules-2026 | sources/sse_trading_rules_2026.docx | 规则正文（正式） | 仅目录页，精确附件 URL 待补 | 空 | fc922c43 |
| sse-trading-rules-2026-explanation | sources/sse_trading_rules_2026_explanation.docx | 起草说明（正式辅助） | 仅目录页，精确附件 URL 待补 | 空 | 6c0ffbb1 |
| sse-trading-rules-2026-deferred-articles | sources/sse_trading_rules_2026_deferred_articles.docx | 暂缓实施条文（正式辅助） | 仅目录页，精确附件 URL 待补 | 空 | f4a0d097 |

`retrieved_at` 无真实下载或文件取得记录，已按要求全部留空，未填写推测时间。
同时已清除 `authoritative_limit_rules.csv` 与 `limit_rules.csv` 中的
`2026-08-06T00:00:00+08:00` 占位值。

## 5. 门禁状态

```text
深交所主板风险警示10%：VERIFIED
深交所创业板风险警示20%：VERIFIED
上交所主板风险警示10%：VERIFIED
来源链：INCOMPLETE
可进入人工双人复核：NO
可将review_status改为approved：NO
可运行stage8-rules-build --validate-only：NO
```

阻塞原因：

- `retrieved_at` 缺失，来源链不完整。
- 上交所精确官方附件 URL 缺失。
- 人工双人复核未完成；`review_status` 保持 `pending`，`reviewer` 未填写。

## 6. 输出文件

```text
docs/stage8_2026_risk_rule_verification.md
reports/stage8_2026_risk_rule_verification/f41fa319-6b7e-4b19-940e-1e677513232c/verification.csv
reports/stage8_2026_risk_rule_verification/f41fa319-6b7e-4b19-940e-1e677513232c/source_chain.json
reports/stage8_2026_risk_rule_verification/f41fa319-6b7e-4b19-940e-1e677513232c/audit_summary.json
```

本轮未执行 `git add`、`git commit`、正式发布或 Stage8 重建。
