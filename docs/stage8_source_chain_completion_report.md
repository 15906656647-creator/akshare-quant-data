# Stage8 来源链补全与一致性复审报告

> 报告日期：2026-08-06
> 分支：`feature/stage15-authoritative-sources`
> run_id：`3f473604-2f99-4cbc-aa4f-7af15d9d2413`
> as_of_date：`2026-07-27`
> 本项目仅用于研究与测试，不构成投资建议。

## 1. 结论

```text
上交所精确附件URL：COMPLETE
深交所精确附件URL：COMPLETE
真实retrieved_at：COMPLETE
来源文件重新下载校验：PASS
来源哈希一致性：PASS
source_registry一致性：PASS
两个规则CSV一致性：PASS
规则矩阵未被修改：PASS
来源链：COMPLETE
可进入人工双人复核：YES
可将review_status改为approved：NO
可运行stage8-rules-build --validate-only：NO
```

9 个实际使用附件全部从官方 URL 重新下载，格式有效且 SHA-256 与正式文件一致；
4 个官方通知页均成功获取。来源链现已完整，但人工双人复核未完成，`review_status`
保持 `pending`，不得自动批准。

## 2. 重新下载附件校验

| 来源 | 本地文件 | 官方页面 | 官方附件 | 原哈希 | 重新下载哈希 | 一致 | 真实retrieved_at | 角色 | A级候选 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sse-trading-rules-2023 | sources/sse_trading_rules_2023.docx | [通知页](https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/c_20250612_10824490.shtml) | dcbe58ed...docx | 7aa2319f...fded40 | 7aa2319f...fded40 | 是 | 2026-08-06T11:07:01+08:00 | 规则正文 | A |
| sse-trading-rules-2023-explanation | sources/sse_trading_rules_2023_explanation.docx | 同上 | 0e769c59...docx | b0f4242c...8f42a | b0f4242c...8f42a | 是 | 2026-08-06T11:07:01+08:00 | 起草说明 | A |
| sse-trading-rules-2023-deferred-articles | sources/sse_trading_rules_2023_deferred_articles.docx | 同上 | 3f0cc77b...8e0.docx | 13cd6f14...bf4e2 | 13cd6f14...bf4e2 | 是 | 2026-08-06T11:07:01+08:00 | 暂缓实施条文 | A |
| sse-trading-rules-2026 | sources/sse_trading_rules_2026.docx | [通知页](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml) | 70420472...4791.docx | fc922c43...ff8888 | fc922c43...ff8888 | 是 | 2026-08-06T11:07:02+08:00 | 规则正文 | A |
| sse-trading-rules-2026-explanation | sources/sse_trading_rules_2026_explanation.docx | 同上 | 92435c67...2012b.docx | 6c0ffbb1...98aa1 | 6c0ffbb1...98aa1 | 是 | 2026-08-06T11:07:02+08:00 | 起草说明 | A |
| sse-trading-rules-2026-deferred-articles | sources/sse_trading_rules_2026_deferred_articles.docx | 同上 | 2ebdf02d...1456.docx | f4a0d097...9958c5 | f4a0d097...9958c5 | 是 | 2026-08-06T11:07:03+08:00 | 暂缓实施条文 | A |
| szse-trading-rules-2023 | sources/szse_trading_rules_2023.pdf | [通知页](https://www.szse.cn/lawrules/rule/repeal/rules/t20230217_598773.html) | W020230217564423808793.pdf | 7018114a...67222 | 7018114a...67222 | 是 | 2026-08-06T11:07:03+08:00 | 规则正文 | A |
| szse-trading-rules-2026 | sources/szse_trading_rules_2026.pdf | [通知页](https://www.szse.cn/lawrules/rule/allrules/bussiness/t20260424_620190.html) | W020260424690713155663.pdf | 9b66f8b0...3c586 | 9b66f8b0...3c586 | 是 | 2026-08-06T11:07:03+08:00 | 规则正文 | A |
| szse-trading-rules-2026-explanation | sources/szse_trading_rules_2026_explanation.pdf | 同上 | W020260424690713346617.pdf | 3a309bf5...727a | 3a309bf5...727a | 是 | 2026-08-06T11:07:03+08:00 | 修订说明 | A |

注意：`szse-trading-rules-2023` 原先登记的附件 URL
`/www/lawrules/rule/trade/W020230217564423808793.pdf` 返回 404；官方通知页内附件链接为
`/www/lawrules/rule/repeal/rules/W020230217564423808793.pdf`，使用该官方链接重新下载后哈希一致。

## 3. 官方通知页获取

| 来源 | official_page_url | page_retrieved_at | HTTP | 内容类型 | 角色 |
| --- | --- | --- | --- | --- | --- |
| sse-trading-rules-2023-notice | 上交所2023通知页 | 2026-08-06T11:07:04+08:00 | 200 | text/html | notice，非规则正文 |
| sse-trading-rules-2026-notice | 上交所2026通知页 | 2026-08-06T11:07:04+08:00 | 200 | text/html | notice，非规则正文 |
| szse-trading-rules-2023-notice | 深交所2023通知页 | 2026-08-06T11:07:05+08:00 | 200 | text/html | notice，非规则正文 |
| szse-trading-rules-2026-notice | 深交所2026通知页 | 2026-08-06T11:07:06+08:00 | 200 | text/html | notice，非规则正文 |

通知页只用于证明发布信息与附件关系，`authoritative_rule_body=false`，不进行附件哈希替代。

## 4. 已同步文件

- `source_registry.yml`：13 条来源登记，包含精确官方页面/附件 URL、真实 `retrieved_at`、SHA-256、文件角色与格式说明。
- `dataset.yml`：4 个正式正文来源的 `reference` 与 `retrieved_at` 已同步。
- `authoritative_limit_rules.csv` 与 `limit_rules.csv`：12 条记录的 `source_reference`、`retrieved_at`、`notes` 已同步，两份文件 SHA-256 完全一致。
- `review_checklist.md`：来源链核验项已更新；签名与双人复核仍留空。

## 5. 一致性复审结果

```text
两个规则CSV SHA-256一致：PASS
12条记录：PASS（6组，每组2条）
日期覆盖无缺口、无重叠：PASS
所有raw_file存在：PASS
所有source_sha256匹配：PASS
所有source_reference为官方精确地址：PASS
所有实际使用来源有真实retrieved_at：PASS
不存在占位时间：PASS
不存在第三方URL：PASS
review_status全部pending：PASS
reviewer与verified_at全部为空：PASS
三条2026风险警示比例未被修改：PASS
```

## 6. 未完成项

- 人工双人复核尚未完成。
- `reviewer`、`reviewed_at` 仍留空。
- `review_status` 仍为 `pending`。
- 在双人复核完成前，不得运行正式发布、Stage8 重建或 Stage15 重跑。

## 7. 输出文件

```text
docs/stage8_source_chain_completion_report.md
reports/stage8_source_chain_completion/3f473604-2f99-4cbc-aa4f-7af15d9d2413/retrieval_manifest.csv
reports/stage8_source_chain_completion/3f473604-2f99-4cbc-aa4f-7af15d9d2413/retrieval_manifest.json
reports/stage8_source_chain_completion/3f473604-2f99-4cbc-aa4f-7af15d9d2413/hash_comparison.csv
reports/stage8_source_chain_completion/3f473604-2f99-4cbc-aa4f-7af15d9d2413/source_chain_summary.json
reports/stage8_source_chain_completion/3f473604-2f99-4cbc-aa4f-7af15d9d2413/audit_summary.json
reports/stage8_source_chain_completion/3f473604-2f99-4cbc-aa4f-7af15d9d2413/consistency_check.json
reports/stage8_source_chain_completion/3f473604-2f99-4cbc-aa4f-7af15d9d2413/downloads/
```

本轮未执行 `git add`、`git commit`、`git push`，未覆盖任何原始规则文件，未执行正式发布、Stage8 重建或 Stage15 重跑。
