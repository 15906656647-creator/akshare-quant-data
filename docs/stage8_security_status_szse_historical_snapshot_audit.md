# Stage8 深交所历史证券状态快照专项审计

> run_id：`20260806_154939`
> 分支：`feature/stage15-authoritative-sources`
> 审计类型：深交所历史证券状态快照专项检索
> retrieved_at：`2026-08-06T15:49:39+08:00`

本轮目标是寻找深交所官方 2025-07-25 起点与 2026-07-27 终点的历史风险警示名单、
历史证券列表或带业务日期的证券状态快照，并纠正此前把普通公司公告 PDF 作为边界证据
的问题。

## 1. 结论

```text
发现可用历史风险警示名单：NO
发现可用历史证券列表：NO
发现订阅或授权数据产品：YES
2025-07-25起点完整股票数：0/8
2026-07-27终点完整股票数：0/8
深市来源链完整股票数：0/8
全部16只股票来源链完整数：0/16
普通公告误用检查：PASS
可开始生成security_status_history.csv草稿：NO
```

深交所公开网页中，风险警示板、A 股列表、暂停/终止上市列表均为 `CURRENT_ONLY`。
名称变更接口支持日期范围，但只返回变更事件；统计月报中的证券停牌情况表提供精确事件
区间，但不能证明未列示证券的历史状态。深圳证券信息有限公司提供包含“证券信息、证券
状态”的历史增强行情数据，但属于授权订阅产品，本轮未取得数据。

## 2. 已有深交所来源重评估

`existing_source_reassessment.csv` 已逐项重评估原审计目录中的 90 个深交所相关文件：

| 来源类型 | 数量 | 重评估结果 |
| --- | ---: | --- |
| `company_announcement_pdf` | 16 | `INVALID_FOR_BOUNDARY`，剔除 |
| `announcement_search_result` | 65 | `EVENT_SEARCH_ONLY`，仅事件检索 |
| `exchange_stock_list` | 8 | `CURRENT_ONLY`，不能映射历史边界 |
| `risk_warning_plate` | 1 | `CURRENT_ONLY`，仅第1页且无历史参数 |

## 3. 官方接口核验

`official_endpoint_inventory.csv` 登记了 11 个官方端点或数据入口。关键结论：

1. 风险警示板报表接口 `CATALOGID=fxjsb`：无日期条件，仅当前名单。
2. A 股列表报表接口 `CATALOGID=1110`：无日期条件，仅当前列表。
3. 全部产品列表报表接口 `CATALOGID=1105`：无日期条件，主要含基金列表。
4. 名称变更报表接口 `CATALOGID=SSGSGMXX`：支持 `txtKsrq/txtZzrq` 日期范围，
   但只返回变更事件，属于 `EVENT_SEARCH_ONLY`。
5. 暂停/终止上市报表接口 `CATALOGID=1793_ssgs`：仅 `selectModule` 条件，
   当前名单为空，无历史日期参数。
6. 公告检索接口 `annList`：支持 `seDate` 日期范围，但只能用于事件检索。
7. 统计月报“证券停牌情况”：公开静态 HTML，含精确停牌/风险警示事件区间。
8. 深圳证券信息有限公司增强行情历史数据：官方说明自 2008-01-01 提供，数据类型包含
   “证券信息、证券状态”，属授权订阅产品。
9. 巨潮数据库与深交所英文数据服务：均属商业/授权数据服务。
10. 深交所技术通知中的 `cashsecurityclosemd_YYYYMMDD.xml`：按日收盘行情文件经
    文件网关下发，不是公开网页下载。

## 4. 本轮核验结果

### 当前风险警示板完整核验

原本地文件只保存了 `fxjsb` 第 1 页，共 20 条。本轮补充拉取全部 7 页，确认当前名单
共 123 条，8 只目标深市股票均不在名单。该结果属于 `CURRENT_ONLY`，不能反推历史状态。

### 名称变更事件检索

通过官方名称变更接口查询 8 只目标股票在 2025-07-25 至 2026-07-27 窗口内的变更
记录，结果均为 0。零变更记录不能证明无风险警示。

### 月度停牌/风险警示事件表

2025 年 7 月官方月报“证券停牌情况”共 27 条事件记录，2026 年 7 月共 22 条，8 只
目标股票均未出现。零事件记录不能证明历史 NON_ST，仍需要真实历史状态快照。

## 5. 边界证据映射

`boundary_evidence_mapping.csv` 为 8 只深市股票分别建立 `baseline_2025-07-25` 和
`endpoint_2026-07-27` 两条记录。每条记录的 `listing_status` 为
`CURRENT_LISTED_ONLY`，`risk_warning_status` 为 `CURRENT_ABSENT_ONLY`，
`evidence_business_date` 为空，`evidence_grade` 为 `CURRENT_ONLY`，
`validation_status` 为 `PARTIAL`。

`remaining_source_gap_list.csv` 共 16 条缺口记录，全部为
`MISSING_HISTORICAL_STATUS_SNAPSHOT`。

## 6. 剩余风险

- 8 只目标深市股票缺少 2025-07-25 历史风险警示名单或历史证券列表。
- 8 只目标深市股票缺少 2026-07-27 历史风险警示名单或历史证券列表。
- 官方历史“证券信息/证券状态”数据需通过深圳证券信息有限公司授权获取，本轮未取得。
- 不得用当前风险警示板、当前A股列表、零公告结果、零事件月报或普通公告 PDF 推断历史
  边界状态。

## 7. 输出文件

```text
reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/existing_source_reassessment.csv
reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/official_endpoint_inventory.csv
reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/historical_query_attempts.csv
reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/historical_file_inventory.csv
reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/boundary_evidence_mapping.csv
reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/remaining_source_gap_list.csv
reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/audit_summary.json
reports/stage8_security_status_szse_historical_snapshot_audit/20260806_154939/szse_audit_download_manifest.csv
```

本轮未生成 `security_status_history.csv`，未生成真实 `dataset.yml`，未运行
`stage8-status-build`，未修改业务代码或测试，未使用第三方数据补齐，未将数据设为
approved 或 approved_with_waiver，未执行 `git add/commit/push`。
