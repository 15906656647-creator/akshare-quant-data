# Stage8 证券状态历史数据集官方来源收集报告

> run_id：`20260806_143005`
> 分支：`feature/stage15-authoritative-sources`
> as_of_date：`2026-07-27`
> retrieved_at：`2026-08-06T14:35:53+08:00`
> 本轮只收集、校验和登记来源，不生成正式 `security_status_history.csv`，不批准数据集。

## 1. 本轮结论

```text
起点官方状态证据完整股票数：8/16
终点官方状态证据完整股票数：8/16
区间官方事件检索完成股票数：16/16
上市状态证据完整股票数：16/16
来源链完整股票数：8/16
状态冲突股票数：0
READY股票数：8
PARTIAL股票数：8
BLOCKED股票数：0
Grade-A候选来源文件数：18
可开始生成security_status_history.csv草稿：NO
可运行stage8-status-build --validate-only：NO
可执行Stage8正式重建：NO
```

8 只沪市股票因上交所静态附件使用 JavaScript 反爬挑战，未能下载官方 PDF 附件，因此起点和终点附件证据标记为 `PARTIAL`。公告检索 JSON、股票列表和风险警示板名单均已成功保存，未将“检索不到公告”推断为 `NON_ST`。

## 2. 收集范围

- 覆盖区间：`2025-07-27` 至 `2026-07-27`
- 起点检索日：`2025-07-25`
- 终点检索日：`2026-07-27`
- 股票数量：16
- 下载文件数：142
- 官方检索日志条数：80
- 来源注册表条目数：142

## 3. 官方来源与文件

主要来源：

| 来源类型 | 说明 | 本地位置 |
| --- | --- | --- |
| 深交所A股列表 | `api/report/ShowReport/data` 按代码查询 | `sources/SZ/<symbol>/` |
| 上交所A股列表 | `commonQuery.do` 按代码查询 | `sources/SH/<symbol>/` |
| 深交所风险警示板 | `CATALOGID=fxjsb` 官方名单 | `sources/SZ/szse_risk_warning_plate_2026-08-06.json` |
| 上交所风险警示板 | `PL_SSGSXX_FXJSBGPLB` 官方名单 | `sources/SH/sse_risk_warning_plate_2026-08-06.json` |
| 公告检索原始响应 | 每只股票全部公告及关键词检索 | `sources/<SZ|SH>/<symbol>/` |
| 公告附件PDF | 仅深交所8只股票成功下载 | `sources/SZ/<symbol>/` |

`source_registry.yml` 已更新为草稿登记：

- `exchange_stock_list` 和 `risk_warning_plate` 登记为 Grade A；
- `announcement_search_result` 和 `company_announcement_pdf` 登记为 Grade B；
- 所有登记均保留原始 URL、`retrieved_at`、SHA-256、文件大小和说明。

## 4. 事件检索结果

对每只股票执行了五类官方检索：

1. 全量公告检索；
2. `风险警示`；
3. `证券简称变更`；
4. `撤销风险警示`；
5. `退市`。

16 只股票在窗口内的官方关键词检索结果均为 0 条。本地全量公告过滤发现 `600438` 有 4 条与资产重组相关的“一般风险提示/停牌/复牌”公告，不属于 ST 状态变更，不构成冲突。

## 5. 状态证据

每只股票均具备：

- 官方股票列表查询记录，显示当前为 `LISTED`；
- 官方风险警示板名单，16 只股票均不在名单内；
- 官方公告检索原始记录，窗口内无风险警示、证券简称变更、撤销风险警示或退市事件。

深交所 8 只股票另有成功下载的基线/终点官方公告附件 PDF。上交所 8 只股票的公告附件 PDF 被 `static.sse.com.cn` 的 JavaScript 反爬挑战拦截，未下载成功，标记为 `PARTIAL`，未推断补齐。

## 6. 000100 重点核查

- 000100 早期 `*ST` 记录为 `2007-05-08` 至 `2008-03-28`，不在本轮所需窗口 `2025-07-27` 至 `2026-07-27` 内；
- 本轮未纳入该历史记录；
- 000100 当前官方列表与风险警示板记录显示不在风险警示名单；
- 窗口内官方关键词检索无风险警示事件。

## 7. 校验结果

`collection_validation.json` 校验：

- 142 个下载文件哈希全部匹配；
- PDF 魔数、JSON/JSONP 可解析性全部通过；
- 16 只股票均不在交易所风险警示板名单；
- 16 只股票官方股票列表查询均有效；
- 16 只股票全量公告检索结果均非空；
- 冲突股票数：0。

## 8. 缺口

`source_gap_list.csv` 中的缺口：

- 8 只沪市股票缺少基线/终点公告附件 PDF，阻塞原因为上交所 PDF 反爬挑战；
- 16 只股票尚未取得交易所针对该股在窗口内实施/撤销风险警示的正式决定附件；当前证据为官方列表、风险警示板和公告检索记录。

下一步应先补齐 8 只沪市股票的官方 PDF 或等价官方状态证据，再评估 `source_chain_complete`。

## 9. 输出文件

```text
data/manual/stage8/security_status/source_registry.yml
data/manual/stage8/security_status/sources/
docs/stage8_security_status_source_collection_report.md
reports/stage8_security_status_source_collection/20260806_143005/download_manifest.csv
reports/stage8_security_status_source_collection/20260806_143005/download_manifest.json
reports/stage8_security_status_source_collection/20260806_143005/official_search_log.csv
reports/stage8_security_status_source_collection/20260806_143005/baseline_evidence_matrix.csv
reports/stage8_security_status_source_collection/20260806_143005/event_evidence_matrix.csv
reports/stage8_security_status_source_collection/20260806_143005/symbol_status_evidence_matrix.csv
reports/stage8_security_status_source_collection/20260806_143005/source_hashes.csv
reports/stage8_security_status_source_collection/20260806_143005/source_gap_list.csv
reports/stage8_security_status_source_collection/20260806_143005/audit_summary.json
reports/stage8_security_status_source_collection/20260806_143005/collection_validation.json
```

本轮未生成 `security_status_history.csv`，未生成真实 `dataset.yml`，未运行 `stage8-status-build`，未运行 Stage8 正式重建、Stage15 或 S15-14。
