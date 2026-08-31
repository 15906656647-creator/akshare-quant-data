# Stage8 证券状态历史数据集需求与来源缺口审计

> run_id：`4ab65fc0-3806-48a3-8b0c-9ea5119253f5`
> 分支：`feature/stage15-authoritative-sources`
> as_of_date：`2026-07-27`
> 本轮只审计，不生成或批准真实 security_status 数据。

## 1. 实现契约结论

- 真实 CSV 文件名（实现要求）：`security_status_history.csv`
- 本地实际存在的候选 CSV：`authoritative_security_status_history.csv`
- 必填列：`symbol/exchange/board/status_type/status_value/effective_from/effective_to/announcement_date/source_name/source_document_id/source_reference/retrieved_at/raw_file/source_sha256/review_status/notes`
- 可选列：`record_id/listing_date/delisting_date/status_version/reviewer/review_mode/waiver_reason/waiver_approver/waiver_at/waiver_document`
- `status_type`：`ST` / `LISTING`
- `ST.status_value`：`NON_ST` / `ST` / `*ST` / `OTHER`
- `LISTING.status_value`：`LISTED` / `SUSPENDED` / `DELISTED`
- 区间：闭区间 `[effective_from, effective_to]`，空 `effective_to` 表示仍在生效
- 覆盖要求：窗口内每只股票每天必须恰好一条 ST 与一条 LISTING，无缺口、无重叠
- 实际要求覆盖区间：`2025-07-27` 至 `2026-07-27`
- 是否要求 2023-07-27 起：否
- 是否只要求正式事件窗口：是，`2025-07-27` 至 `2026-07-27`
- `approved_with_waiver` 已完整适用于 security_status：是（Schema、校验器、示例和测试均支持）
- 构建/校验命令：`run_pipeline.py stage8-status-build --as-of-date 2026-07-27 --dataset-dir data\manual\stage8\security_status --validate-only`

## 2. 本地文件盘点

`data/manual/stage8/security_status/` 仅包含虚构样例、Schema、模板和来源 README。
- 来源文件数：0，且仅 `sources/README.md`，不是权威状态来源。
- 现有 `authoritative_security_status_history.csv` 是虚构样例，不是实现要求的 `security_status_history.csv`。
- 现有 `dataset.yml` 是虚构样例清单，不是真实 manifest。
- Grade A 来源数量：0。

完整清单见 `local_source_inventory.csv`。

## 3. 16 只股票覆盖矩阵

所有 16 只股票均无正式来源、无真实状态区间，readiness 全部为 `BLOCKED`。
对无 ST 事件的股票，项目不允许仅凭“未发现公告”判定长期 `NON_ST`；必须由交易所正式风险警示/简称变更公告、上市/暂停/恢复/终止上市公告等具有生效日期的正式证据支撑。
现有探测中的官方当前列表、名称变更历史、空公告检索分别只能作为 B/C 级辅助，不能单独构成 Grade A 状态历史。

## 4. 000100 重点核查

- 历史资料中记载的 `*ST` 区间为 `2007-05-08` 至 `2008-03-28`，来自既有审计文档中的深交所简称变更记录。
- 该区间不在所需窗口 `2025-07-27` 至 `2026-07-27` 内，**不需要纳入当前 security_status 数据集**。
- 该历史记录不能用于证明 2025—2026 年普通状态；2025—2026 年仍需独立的正式状态证据。
- 本地 `security_status/sources/` 中没有该公告的原始文件，且当前严格分级下名称变更历史为 B 级辅助，不是 Grade A。

## 5. 来源等级

Grade A 候选仅限交易所正式状态公告/附件、正式证券简称或风险警示公告、正式上市/暂停/恢复/终止上市公告，以及监管机构直接发布且可确定生效时间的正式文件。
财经网站、搜索结果摘要、行情软件截图、当前证券简称、AKShare 接口结果、测试配置、已有 CSV 和未注明来源的人工结论均不能单独作为 Grade A。
当前 `status_probe` 保留 `official_status_history` 作为唯一可评为 A 的来源类型，现有探测集合中没有任何此类来源。

## 6. 缺口与门禁

- 来源链完整股票数：0/16
- 日期覆盖完整股票数：0/16
- 冲突股票数：0（当前无真实状态记录可冲突）
- 缺失来源股票数：16/16
- 可开始构建 security_status 草稿：NO
- 可运行 `stage8-status-build --validate-only`：NO
- 可执行 Stage8 正式重建：NO

## 7. 输出文件

```text
docs/stage8_security_status_source_audit.md
reports/stage8_security_status_source_audit/4ab65fc0-3806-48a3-8b0c-9ea5119253f5/required_schema.json
reports/stage8_security_status_source_audit/4ab65fc0-3806-48a3-8b0c-9ea5119253f5/symbol_coverage_matrix.csv
reports/stage8_security_status_source_audit/4ab65fc0-3806-48a3-8b0c-9ea5119253f5/local_source_inventory.csv
reports/stage8_security_status_source_audit/4ab65fc0-3806-48a3-8b0c-9ea5119253f5/source_gap_list.csv
reports/stage8_security_status_source_audit/4ab65fc0-3806-48a3-8b0c-9ea5119253f5/audit_summary.json
```
