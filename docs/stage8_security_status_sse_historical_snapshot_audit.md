# Stage8 上交所历史证券状态快照专项审计

> run_id：`20260806_153639`
> 分支：`feature/stage15-authoritative-sources`
> 审计类型：上交所历史证券状态快照专项检索
> retrieved_at：`2026-08-06T15:36:39+08:00`

本轮目标是纠正 Stage8 security_status 边界证据标准：不再把普通上市公司公告 PDF
当作 2025-07-25 起点或 2026-07-27 终点状态证据，改为专项确认上交所是否提供可复验的
历史风险警示名单、历史证券列表或带业务日期的官方状态快照。

## 1. 结论

```text
发现可用历史风险警示名单：NO
发现可用历史证券列表：NO
2025-07-25起点完整股票数：0/8
2026-07-27终点完整股票数：0/8
沪市来源链完整股票数：0/8
全部16只股票来源链完整数：0/16
普通公告误用检查：PASS
可开始生成security_status_history.csv草稿：NO
```

上交所风险警示板和 A 股列表接口均为 `CURRENT_ONLY`。上交所历史数据及证券基本信息文件
由上证所信息公司作为订阅产品提供，本轮未取得公开按日下载入口，因此 8 只目标沪市股票的
2025-07-25 起点与 2026-07-27 终点历史状态均未证明。

按纠正后的证据标准重估原审计目录：深市 8 只股票原边界证据中的普通公告 PDF 同样失效，
全部 16 只股票的历史快照来源链均不完整。

## 2. 原142个文件重评估

`existing_source_reassessment.csv` 已逐项重评估原审计目录的 142 个文件：

| 来源类型 | 数量 | 重评估结果 |
| --- | ---: | --- |
| `company_announcement_pdf` | 16 | `INVALID_FOR_BOUNDARY`，剔除 |
| `announcement_search_result` | 108 | `EVENT_SEARCH_ONLY`，仅事件检索 |
| `exchange_stock_list` | 16 | `CURRENT_ONLY`，不能映射历史边界 |
| `risk_warning_plate` | 2 | `CURRENT_ONLY`，不能映射历史边界 |

现有 8 只沪市股票的 `baseline` 与 `endpoint` 记录均为普通公告或当前快照，不能作为
2025-07-25 / 2026-07-27 边界状态证据。

## 3. 上交所官方接口核验

`official_endpoint_inventory.csv` 登记了 10 个官方端点或官方数据入口。关键结论：

1. 风险警示板 JSONP：`commonSoaQuery.do?sqlId=PL_SSGSXX_FXJSBGPLB`，官方 JS 仅传
   `domesticIndicator` 和 `productType`，无任何历史日期参数。
2. 科创板风险警示 JSONP：`sqlId=SSE_PL_SSGSXX_KCBFXTS_L`，同样仅传 `type`。
3. A 股列表 JSONP：`COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L`，官方 JS 仅传 `STOCK_CODE`、
   `COMPANY_STATUS` 和分页参数，无历史日期参数。
4. 公司公告检索 JSONP：`queryCompanyBulletinNew.do` 支持 `START_DATE/END_DATE`，但
   这些日期只约束公告发布日期，属于 `EVENT_SEARCH_ONLY`，不能单独证明历史 NON_ST。
5. SSEINFO 行情历史数据产品：官方页面明确历史数据、证券基本信息文件属于订阅服务，
   本轮未获得授权，标记为 `SUBSCRIPTION_ONLY`。
6. 上交所对外公示数据目录：只提供当前股票列表、风险警示板、暂停/终止上市公司栏目，
   未发现历史状态快照下载入口。

## 4. 历史查询尝试

`historical_query_attempts.csv` 记录了本轮 21 次查询尝试，包括页面、官方 JS、当前
JSONP 快照、精确日期公告检索、SSEINFO 产品文档和 404 接口规范尝试。

重要结果：

- 风险警示板当前响应 `queryDate=''`、`searchDate=null`，无业务日期。
- A 股列表当前响应 `queryDate=''`、`pageHelp.startDate/endDate=null`，无业务日期。
- 600231 在 2025-07-25 当天仅有董事、高管辞职等普通公告，不能证明状态。
- 600231 在 2026-07-27 当天公告检索为 0，零公告同样不能解释为 NON_ST。
- 上交所数据文件交换接口规范直接 URL 与搜索结果中的官方镜像 URL 均返回 404，
  未获得按日历史文件公开下载入口。

## 5. 边界证据映射

`boundary_evidence_mapping.csv` 为 8 只沪市股票分别建立 `baseline_2025-07-25` 和
`endpoint_2026-07-27` 两条记录。每条记录的 `status_value` 均为 `UNKNOWN`，
`listing_status` 为 `CURRENT_LISTED_ONLY`，`risk_warning_flag` 为
`CURRENT_ABSENT_ONLY`，`validation_status` 为 `PARTIAL`。

`remaining_source_gap_list.csv` 共 16 条缺口记录，全部为
`MISSING_HISTORICAL_STATUS_SNAPSHOT`。

## 6. 剩余风险

- 8 只目标沪市股票缺少上交所 2025-07-25 历史风险警示名单或历史证券列表。
- 8 只目标沪市股票缺少上交所 2026-07-27 历史风险警示名单或历史证券列表。
- 官方历史数据若仅通过 SSEINFO 订阅交付，需要另行取得授权和下载证据后才能继续。
- 不得用当前证券简称、当前风险警示板、零公告结果或普通公告 PDF 推断历史边界状态。

## 7. 输出文件

```text
reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/existing_source_reassessment.csv
reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/official_endpoint_inventory.csv
reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/historical_query_attempts.csv
reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/boundary_evidence_mapping.csv
reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/remaining_source_gap_list.csv
reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/audit_summary.json
reports/stage8_security_status_sse_historical_snapshot_audit/20260806_153639/sse_audit_download_manifest.csv
```

本轮未生成 `security_status_history.csv`，未生成真实 `dataset.yml`，未运行
`stage8-status-build`，未修改业务代码或测试，未使用第三方数据补齐，未执行
`git add/commit/push`。
