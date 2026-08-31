# Stage 15 / Stage 8 证券状态历史根因分析报告

> 审计日期：2026-08-08
> 基线日期 / as_of_date：2026-07-27
> 分析窗口：2025-07-27 至 2026-07-27
> 本次只做代码审计、数据口径审计和数据来源核验；除本报告与问题清单外不修改业务代码。

## 1. Executive Summary

- Stage 15 当前确实被 Stage 8 阻塞，但阻塞形式是“完整通过被阻塞”，不是每日质量检查失败：`quality-control` 可运行并返回 `PASS_WITH_UNAVAILABLE_ITEMS`，其中 S15-14 最近涨停日及次日开盘价两项交叉验证全部为 `UNAVAILABLE`。
- 阻塞点与沪深交易所证券状态历史直接相关：项目没有可发布、可审计的 `security_status_history` 数据，`data/manual/stage8/security_status/security_status_history.csv` 不存在，现有 `dataset.yml` 是虚构样例。
- 规则历史已基本就绪：12 条涨跌停规则草稿通过 `stage8-rules-build --validate-only`（`READY`），但采用 `approved_with_waiver`，尚未完成双人复核，也未正式发布合并配置。
- 严重等级：critical。一年涨跌停统计、跌停统计、事件后收益、连板统计均不能标记为“已验证”，当前没有任何可正式发布的 Stage 8 全年统计结果。
- 结论：`The pipeline runs, but the result is not auditable / historically reliable.` 在证券状态历史问题解决前，Stage 15 不能判为完全通过。

## 2. Stage Mapping

| Stage 15 失败项 | 调用/依赖 | Stage 8 函数 | 数据库表 | 字段 | 当前来源 | 缺失/不可验证 |
| --- | --- | --- | --- | --- | --- | --- |
| S15-14 `recent_limit_up_day` | `build_cross_validation`（[stage15_checks.py](src/akshare_data_test/quality/stage15_checks.py:861)） | `_read_limit_events`（[stage15_build.py](src/akshare_data_test/stage15_build.py:293)） | `analysis.v_latest_formal_limit_event` | `event_type, trade_date, next_open` | 无正式 Stage 8 输出 | 无正式事件 → `UNAVAILABLE` |
| S15-14 `next_day_open_after_limit_up` | 同上 | `_stage8_blocker_codes`（[stage15_build.py](src/akshare_data_test/stage15_build.py:340)） | 同上 | 同上 | 无正式 Stage 8 输出 | 无正式事件 → `UNAVAILABLE` |
| Stage 8 正式事件 | `detect_limit_events`（[limit_event_detection.py](src/akshare_data_test/limit_event_detection.py:247)） | `resolve_security_status`（[limit_rules.py](src/akshare_data_test/limit_rules.py:461)） | `reference.security_status_history`（[stage8_schema.sql](sql/stage8_schema.sql)） | `symbol, effective_start, effective_end, exchange, board, is_st, listing_status, source_reference, status_version` | 无真实记录 | `missing_security_status` |
| 证券状态数据集 | `validate_manual_dataset`（[stage8_manual.py](src/akshare_data_test/stage8_manual.py:1014)） | `build_status_manifest`（[stage8_authoritative.py](src/akshare_data_test/stage8_authoritative.py:435)） | 无表级数据文件 | `security_status_history.csv` 全字段 | `dataset.yml` 为虚构样例 | `records_csv_empty`、`records_file_missing` |
| 数据来源 | 官方历史状态快照/公告事件 | `status_probe`（[status_probe.py](src/akshare_data_test/adapters/status_probe.py:37)） | 不适用 | 不适用 | 沪深公开接口均为 `CURRENT_ONLY`；历史状态为订阅产品 | 无 A 级历史状态来源 |

## 3. Actual Failure

实际执行结果如下：

```text
command: stage8-preflight --as-of-date 2026-07-27
exit_code: 1
status: FAILED
rules component: READY（12 条记录，校验通过）
security_status_history component: FAILED
errors:
  - records_csv_empty
  - records_file_missing:security_status_history.csv
```

```text
command: stage8-status-build --as-of-date 2026-07-27 --validate-only
exit_code: 1
status: FAILED
blocking_reasons: [dataset_validation_failed]
errors:
  - records_csv_empty
  - records_file_missing:security_status_history.csv
```

```text
command: stage8-rules-build --as-of-date 2026-07-27 --validate-only
exit_code: 0
status: READY
rule_count: 12
verified_rule_count: 12
```

```text
command: quality-control --as-of-date 2026-07-27
status: PASS_WITH_UNAVAILABLE_ITEMS
checks: 58 pass, 0 warn, 0 fail
cross_validation_rows: 21
unavailable_items: 6
blocked_risks: 2
stage8_blockers: no_authoritative_limit_rules; no_authoritative_security_status_history
```

`PASS_WITH_UNAVAILABLE_ITEMS` 不是程序崩溃，而是 Stage 15 的 fail-closed 表达：每日质量检查通过，但涨停交叉验证无法完成，风险日志记录两条 `blocked_input` 风险（[stage15_checks.py](src/akshare_data_test/quality/stage15_checks.py:970)）。因此：

> The pipeline runs, but the result is not auditable / historically reliable.

## 4. Current Implementation

当前实现已经具备正确的 fail-closed 骨架，但没有真实状态数据：

- 默认配置中 `rule_records` 和 `security_status_records` 均为空（[config/stage8.yml](config/stage8.yml:13)）。
- 证券状态模型 `SecurityStatus` 要求 `exchange, board, listing_status, source_reference, status_version` 等字段，`resolve_security_status` 按 `symbol + trade_date` 做闭区间 temporal join，并要求每天恰好一条 ST 与一条 LISTING 记录（[limit_rules.py](src/akshare_data_test/limit_rules.py:461)）。
- 涨跌停规则 `resolve_limit_rule` 按 `status.exchange/board/is_st` 和时间区间匹配规则（[limit_rules.py](src/akshare_data_test/limit_rules.py:490)）；不存在固定 ±10% 硬编码。
- 理论限价用 `Decimal` 计算并按 `tick_size`、`half_up/half_even` 舍入（[limit_rules.py](src/akshare_data_test/limit_rules.py:523)），匹配容差为半个 tick（[limit_rules.py](src/akshare_data_test/limit_rules.py:540)）。
- 若证券状态缺失，`detect_limit_events` 把该行写成 `event_type=unresolved`、`quality_status=failed`、`resolution_reason=missing_security_status`（[limit_event_detection.py](src/akshare_data_test/limit_event_detection.py:374)），不会把“无数据”解释为“非涨停”。
- 当前手动数据集校验要求来源等级必须为 A（[stage8_manual.py](src/akshare_data_test/stage8_manual.py:383)），记录文件缺失或为空时直接 `records_csv_empty` / `records_file_missing`（[stage8_manual.py](src/akshare_data_test/stage8_manual.py:246)、[stage8_manual.py](src/akshare_data_test/stage8_manual.py:1093)）。
- `build_status_manifest` 在没有任何 `evidence_status=verified` 状态时返回 `no_authoritative_security_status_history`（[stage8_authoritative.py](src/akshare_data_test/stage8_authoritative.py:490)）。

## 5. Expected Implementation

设计文档要求（[stage0_scope.md](docs/stage0_scope.md) 第 2.7 节、[分阶段操作步骤.md](AKShare数据抓取测试_分阶段操作步骤.md) 第 8.2/8.3 节）：

```text
status = get_security_status(symbol, trade_date)
rule = get_limit_rule(exchange, board, special_treatment, trade_date)
limit_up_price = calculate_limit_up_price(prev_close, rule.limit_up_ratio, tick_size)
limit_down_price = calculate_limit_down_price(prev_close, rule.limit_down_ratio, tick_size)
is_limit_up = abs(close - limit_up_price) <= tick_size / 2
```

同时要求：不复权价格、昨日真实收盘、按交易日 temporal join、处理停牌/无涨跌幅限制/上市初期/ST/*ST/板块规则/价格舍入，保存 `rule_version` 与 `source_reference`，并把“无数据”和“非涨停”严格区分。

## 6. Root Cause

### 6.1 分类结论

| 类别 | 结论 |
| --- | --- |
| Code issue | 未识别为阻塞根因。fail-closed 计算链、temporal join、舍入与门禁逻辑正确。次要问题：`_stage8_blocker_codes` 在无正式事件时固定返回配置中的两个 blocker code（[stage15_build.py](src/akshare_data_test/stage15_build.py:340)），即使规则数据集已 READY，也会继续报 `no_authoritative_limit_rules`，口径上不够精确。 |
| Schema issue | 表结构已支持所需字段，但 `security_status_history` 没有有效数据；建议补充 `evidence_level / security_name / raw_source_id / status_event` 等审计字段。不是当前阻塞根因。 |
| Data issue | 根因之一。真实 `security_status_history.csv` 不存在；`dataset.yml` 仍是虚构演示；旧 S15-14 修复产生的 17 条状态记录因来源等级收紧已被判定无效。 |
| Source issue | 根因之一。上交所与深交所公开风险警示板、A 股列表均为 `CURRENT_ONLY`；官方历史“证券信息/证券状态”数据属于订阅产品，本轮未取得授权与数据。 |
| Rule issue | 非当前阻塞根因，但存在治理风险：规则草稿通过 `approved_with_waiver` 被放行，`verified_by_dual_review=false`；2026 版沪深 ST 比例按一般条款推断，需人工复核确认。 |
| Testing issue | 根因之一。测试使用合成状态/规则，能验证代码逻辑，但不能验证“真实官方状态历史已就绪”；上一轮无效 S15-14 修复因此一度被测试和报告接受，后来才由来源探测修复推翻。 |
| Documentation issue | 根因之一。旧 `stage15_s14_fix_report.md` 曾宣布阶段 15 通过，后已被修订为 `BLOCKED`；`status_probe` 与快照审计明确当前没有任何 A 级历史状态来源。 |

### 6.2 对照用户给出的 A-O 清单

| 情形 | 是否命中 | 证据 |
| --- | --- | --- |
| A 完全没有表 | 否 | `reference.security_status_history` 已建表。 |
| B 表存在但没有数据 | 是 | 真实 CSV 缺失，数据集校验报 `records_csv_empty`。 |
| C 只有当前状态没有历史 | 是 | 沪深公开接口均为 `CURRENT_ONLY`。 |
| D 用当前名称 ST 反推历史 | 是（旧实现，已作废） | 旧 S15-14 状态记录用当前名单+零公告反推非 ST；当前代码明确拒绝。 |
| E 用当前 AKShare spot 反推历史 | 是（旧实现，已作废） | 旧状态记录使用官方当前列表/风险警示板与公告检索零结果；被快照审计判定为 `CURRENT_ONLY`，不能证明历史。 |
| F board 按代码静态推导 | 是 | 当前没有历史板块事实来源；16 只样本的板块只能由代码前缀或状态记录提供。 |
| G 规则表缺 source_reference | 否 | 规则草稿 12 条均有官方 `source_reference` 与 SHA-256。 |
| H 状态表 effective_start/end 无可信依据 | 是 | 当前无真实状态记录；旧记录来源等级无效。 |
| I 数据存在但未做 temporal join | 否 | `resolve_security_status` 已按 `symbol + trade_date` 闭区间 join。 |
| J off-by-one/边界日错误 | 否 | 区间为包含式 `<=`，未发现错误。 |
| K ST 切换当天生效日期错误 | 未识别 | 无真实状态切换数据可判定。 |
| L 上市首日/前若干日规则未处理 | 未命中窗口 | 样本窗口内无 IPO 首日事件；规则草稿未写 IPO 规则，但不影响当前窗口校验。 |
| M 仍硬编码 ±10% | 否 | 规则来自规则表。 |
| N 舍入/最小报价单位错误 | 否 | `Decimal` + tick + `half_up/half_even` 已实现并有测试。 |
| O 其他根因 | 是 | 官方历史状态数据源不可公开获取；旧修复误把“能算出事件”当作“历史正确”。 |

## 7. SSE Evidence

| evidence | official source | historical? | structured? | sufficient? | notes |
| --- | --- | ---: | ---: | ---: | --- |
| 《上海证券交易所交易规则（2023年修订）》DOCX | [sse.com.cn](https://www.sse.com.cn/lawandrules/sselawsrules2025/repeal/rules/c/c_20250612_10824490.shtml) | 是（规则历史） | 是 | 规则足够，状态不够 | 上证发〔2023〕32号；本地 SHA-256 `7aa2319f...` |
| 《上海证券交易所交易规则（2026年修订）》DOCX | [sse.com.cn](https://www.sse.com.cn/lawandrules/sselawsrules2025/trade/universal/c/c_20260424_10816492.shtml) | 是（规则历史） | 是 | 规则足够，状态不够 | 上证发〔2026〕41号；本地 SHA-256 `fc922c43...` |
| 风险警示板 JSONP `PL_SSGSXX_FXJSBGPLB` | 上交所官方接口 | 否（当前名单） | 是 | 否 | 无历史日期参数 |
| A 股列表 JSONP `COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L` | 上交所官方接口 | 否（当前列表） | 是 | 否 | 无历史日期参数 |
| 公司公告检索 `queryCompanyBulletinNew.do` | 上交所官方接口 | 仅事件检索 | 是 | 否 | 零结果不能证明历史 NON_ST |
| SSEINFO 历史行情/证券基本信息文件 | 上证所信息公司 | 是（订阅） | 是 | 未取得 | 未获得授权下载，`SUBSCRIPTION_ONLY` |

2026-08-08 实测：上述上交所规则通知页返回 HTTP 200。公开风险警示板/证券列表只提供当前状态，不能证明历史状态。

## 8. SZSE Evidence

| evidence | official source | historical? | structured? | sufficient? | notes |
| --- | --- | ---: | ---: | ---: | --- |
| 《深圳证券交易所交易规则（2023年修订）》PDF | [szse.cn](https://www.szse.cn/lawrules/rule/repeal/rules/t20230217_598773.html) | 是（规则历史） | 是 | 规则足够，状态不够 | 深证上〔2023〕98号；本地 SHA-256 `7018114a...` |
| 《深圳证券交易所交易规则（2026年修订）》PDF | [szse.cn](https://www.szse.cn/lawrules/rule/allrules/bussiness/t20260424_620190.html) | 是（规则历史） | 是 | 规则足够，状态不够 | 深证上〔2026〕551号；本地 SHA-256 `9b66f8b0...` |
| 风险警示板报表 `CATALOGID=fxjsb` | 深交所官方接口 | 否（当前名单） | 是 | 否 | 全 7 页 123 条当前名单，无历史参数 |
| A 股列表报表 `CATALOGID=1110` | 深交所官方接口 | 否（当前列表） | 是 | 否 | 无历史日期参数 |
| 名称变更报表 `CATALOGID=SSGSGMXX` | 深交所官方接口 | 事件历史 | 是 | 否 | 只返回变更事件，不能证明无事件区间的状态 |
| 统计月报“证券停牌情况” | 深交所官网 | 月度事件 | 部分 | 否 | 无事件不等于 NON_ST |
| 公告检索 `annList` | 深交所官方接口 | 事件检索 | 是 | 否 | 仅事件检索 |
| 深圳证券信息有限公司历史增强行情（证券信息/证券状态） | 授权订阅 | 是 | 是 | 未取得 | 自 2008-01-01 起，需授权 |

2026-08-08 实测：深交所规则页与风险警示板接口均返回 HTTP 200。公开接口只有当前快照，不能证明历史状态。

## 9. Rule History vs Security Status History

- Rule History：基本具备。`data/manual/stage8/limit_rules/` 有 12 条覆盖 2025-07-27 至 2026-07-27 的规则草稿，来源、条款、SHA-256 已登记，`stage8-rules-build --validate-only` 返回 `READY`。但 `review_status=approved_with_waiver`、`verified_by_dual_review=false`，且未正式发布合并配置。
- Security Status History：缺失。`security_status_history.csv` 不存在，`dataset.yml` 是虚构样例，0 条有效记录；16 只样本在窗口内没有任何可验证的 ST/LISTING 状态区间。

> 因此本项目同时存在“规则历史未完成人工复核”和“证券状态历史完全缺失”两层问题；阻塞 Stage 15 的是后者。

## 10. Sample Reconstruction

### 10.1 SZSE：002067 @ 2026-07-03

```text
symbol: 002067
trade_date: 2026-07-03
prev_close: 3.82（2026-07-02 真实收盘）
actual_close: 4.20

current system status: UNVERIFIED（无 security_status_history）
current system limit ratio: 无法确定（NON_ST=10%，ST=5%，取决于状态）
current system calculated limit price:
  若 NON_ST：round(3.82 * 1.10) = 4.20
  若 ST：round(3.82 * 1.05) = 4.01
current system event result: unresolved / missing_security_status（无正式事件）

correct historical status: UNVERIFIED
correct rule: UNVERIFIED
correct limit price: UNVERIFIED
correct event result: UNVERIFIED

difference:
  4.20 恰好等于 NON_ST 的 10% 涨停价；若按旧修复误判为 NON_ST，会被记为涨停。
  4.20 又大于 ST 的 5% 涨停价 4.01，说明状态是决定事件的关键，不能猜测。

root cause: 无真实证券状态历史，无法判定当日是否 ST/*ST。
official evidence: 深交所当前 A 股列表、当前风险警示板、公告检索；均不能证明 2026-07-03 的历史状态。
```

### 10.2 SSE：600763 @ 2026-06-29

```text
symbol: 600763
trade_date: 2026-06-29
prev_close: 33.33（2026-06-26 真实收盘）
actual_close: 35.03

current system status: UNVERIFIED（无 security_status_history）
current system limit ratio: 无法确定（NON_ST=10%，ST=5%）
current system calculated limit price:
  若 NON_ST：round(33.33 * 1.10) = 36.66，当日非涨停
  若 ST：round(33.33 * 1.05) = 35.00，当日收盘 35.03 超过涨停价，状态/数据不可解释
current system event result: unresolved / missing_security_status

correct historical status: UNVERIFIED
correct rule: UNVERIFIED
correct limit price: UNVERIFIED
correct event result: UNVERIFIED

root cause: 上交所无公开历史风险警示名单/历史证券列表；SSEINFO 历史状态数据为订阅产品，未取得。
official evidence: 上交所当前风险警示板、当前 A 股列表、公告检索；均为 CURRENT_ONLY，不能证明历史 NON_ST。
```

## 11. Impact Assessment

| 输出 | 状态 | 说明 |
| --- | --- | --- |
| 涨停次数 | BLOCKED | 无正式事件可发布 |
| 跌停次数 | BLOCKED | 无正式事件可发布 |
| 次日收益（开盘/收盘） | BLOCKED | 依赖正式涨停事件 |
| 连板统计 | BLOCKED | 依赖正式事件序列 |
| 活跃度 | DEGRADED | 事件频率组成分依赖涨跌停/跳空事件，正式口径不可用 |
| 风格分析 | DEGRADED | 可独立使用 qfq，但事件辅助字段不完整 |
| Stage 13 图表 | BLOCKED | 涨跌停相关图表无法标注“已验证” |
| Stage 15 质量验证 | BLOCKED | S15-14 保持 `UNAVAILABLE` |
| 最终报告 | BLOCKED | 一年涨跌停统计不能作为正式结论 |

## 12. Recommended Solution

### Plan A：官方结构化历史数据直接重建

- 可信度：高（若取得授权数据）。
- 自动化程度：高（导入后走现有 `stage8-status-build`）。
- 工作量：中等，主要前置工作是授权、下载、登记与人工复核。
- 覆盖范围：可覆盖全市场/全部 16 只样本。
- 风险：订阅成本、授权周期、数据口径需要人工核验；仍必须完成双人复核。

### Plan B：官方公告事件重建

- 可信度：中高。
- 自动化程度：中（公告下载、解析、事件表、区间生成）。
- 工作量：高（需覆盖实施/撤销风险警示、简称变更、暂停/恢复/终止上市公告）。
- 覆盖范围：按事件覆盖；无事件区间的 NON_ST 仍需官方历史快照或等价证据。
- 风险：公告缺失、生效日解析错误、无事件区间无法证明；不得把零事件当 NON_ST。

### Plan C：受控 fallback（仅当官方历史不可获得）

- 可信度：低；只能标记为 `INFERRED` / `UNVERIFIED`。
- 自动化程度：高。
- 工作量：低。
- 覆盖范围：仅能支撑“候选/探索”口径。
- 风险：禁止写入正式事件；禁止把候选统计标记为已验证；Stage 15 仍保持 `UNAVAILABLE`。

## 13. Proposed Schema

现有 `reference.security_status_history` 已支持核心字段，建议在正式数据落地前补齐：

```text
symbol, exchange, board, security_name, status_type, status_value,
effective_start, effective_end, is_st, st_type/special_treatment_type,
listing_status, listing_date, delisting_date, no_limit_reason,
announcement_date, evidence_level, raw_source_id, source_type,
source_reference, source_hash, status_version, fetched_at, reviewer
```

`limit_rule` 建议保持现有字段，并强制校验：

```text
exchange + board + special_treatment + effective interval
```

同一维度不允许重叠冲突区间。

## 14. Proposed Pipeline

```text
Exchange official source / licensed historical data
        ↓
Raw evidence archive（PDF/JSON/JSONP，保留 URL、retrieved_at、SHA-256）
        ↓
status event parser / status snapshot loader
        ↓
security_status_history
        ↓
temporal join（symbol + trade_date）
        ↓
limit_rule_history
        ↓
limit event calculation（raw price, Decimal, tick rounding）
        ↓
validation（覆盖、冲突、来源、双人复核）
```

## 15. Required Code Changes

当前阻塞不需要立即改代码；最小且安全的变更如下：

| file | function | change | reason |
| --- | --- | --- | --- |
| `data/manual/stage8/security_status/security_status_history.csv` | 不适用（数据） | 创建真实记录文件 | 当前缺失，`records_file_missing` |
| `data/manual/stage8/security_status/dataset.yml` | 不适用（数据） | 用真实 manifest 替换虚构样例 | 当前为 demo 数据 |
| `src/akshare_data_test/adapters/status_probe.py` | `SOURCE_KINDS` / `_grade_probe` | 取得官方历史状态源后登记为 `official_status_history` | 当前没有任何可评为 A 的历史状态来源 |
| `src/akshare_data_test/stage15_build.py` | `_stage8_blocker_codes` | 区分“规则缺失”与“状态历史缺失” | 避免规则已 READY 仍报 `no_authoritative_limit_rules` 的陈旧口径 |
| `src/akshare_data_test/quality/stage15_checks.py` | `build_cross_validation` | 无需修改 | 已正确输出 `UNAVAILABLE` |
| `tests/` | 新增端到端门禁测试 | 要求正式发布前必须有真实状态历史与双人复核 | 防止无效修复再次“通过” |

## 16. Tests Required

- 普通主板（沪深各 1 只）；
- ST / *ST 区间与切换边界日；
- 创业板与科创板规则；
- 上市初期/无涨跌幅限制日；
- 停牌与零成交行；
- 无价格限制规则；
- 舍入边界（tick 一半处）；
- 无状态历史时 fail-closed；
- 官方来源缺失时 `UNVERIFIED`，不得把未知当普通；
- 双人复核未完成时禁止发布。

## 17. Go / No-Go Recommendation

```text
Stage 15 verdict: NO-GO（完整通过）
```

在证券状态历史问题解决以前，Stage 15 不能被认定为通过：当前只能算 `PASS_WITH_UNAVAILABLE_ITEMS`，S15-14 保持 `UNAVAILABLE`，正式全年涨跌停统计保持 `BLOCKED`。