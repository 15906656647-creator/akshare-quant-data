# Stage 8 权威数据源审计与构建说明

> **修订（2026-08-05）**：本文档最初将深交所简称/全称变更、官方列表与巨潮检索评为
> A 级。经 `stage8-source-probe` 探测修复复核，A 级判定标准收紧，当前分级改为：
> 简称/全称变更与官方当前列表为 B 级（仅辅助），巨潮空检索结果为 C 级
> （空结果不能单独证明无历史），东财两个快照接口探测失败为 C 级；当前没有 A 级
> 正式状态历史来源。正式结论以
> [stage8_source_probe_fix_report.md](stage8_source_probe_fix_report.md) 为准。
>
> 文档日期：2026-08-05
> 对应任务：S15-14 修复闭环中的“权威涨跌停规则历史”与“权威证券状态历史”。
> 数据源探测 run_id：`6b7c8d9e-0f1a-4b2c-9d3e-4f5a6b7c8d9e`
> AKShare 版本：`1.18.80`

## 1. 探测结论摘要

候选接口与补充官方来源的审计结果如下：

| 来源 | 状态 | 行数 | 快照/历史 | 交易所覆盖 | 股票覆盖 | 状态起止日期 | 等级 | 结论 |
| --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| `stock_info_sz_change_name`（简称变更） | success | 7454 | 历史 | SZSE | 深市全市场 | 有（变更日期） | A | 可作正式状态历史输入 |
| `stock_info_sz_change_name`（全称变更） | success | 1756 | 历史 | SZSE | 深市全市场 | 有（变更日期） | A | 可作正式状态历史输入 |
| `stock_info_sh_name_code` | success | 1698 | 当前列表 | SSE | 沪市全市场 | 无（上市日期静态） | A | 官方当前证券列表，配合公告检索使用 |
| `stock_info_sz_name_code` | success | 2894 | 当前列表 | SZSE | 深市全市场 | 无（上市日期静态） | A | 官方当前证券列表，配合变更记录使用 |
| `cninfo_risk_warning` | success | 0 | 公告检索 | 沪深京 | 全市场 | 无直接字段 | A | 巨潮官方公告检索；窗口内零记录为权威“无状态变更”证据 |
| `cninfo_special_treatment` | success | 0 | 公告检索 | 沪深京 | 全市场 | 无直接字段 | A | 巨潮“特别处理和退市”分类检索；窗口内零记录 |
| `stock_individual_info_em` | failed | 0 | 当前快照 | 沪深 | 单只 | 无 | B | 静态上市日期可辅助，ST 状态不能回填 |
| `stock_zh_a_st_em` | failed | 0 | 当前快照 | 沪深 | 全市场 | 无 | B | 当前风险警示板，仅可辅助当前状态校验 |
| `stock_info_change_name` | success | 19 | 曾用名（无日期） | 沪深 | 单只 | 无 | C | 无生效日期，不得单独推断状态区间 |

探测时东财两个快照接口（`stock_individual_info_em`、`stock_zh_a_st_em`）在本环境返回
连接中断，已如实记录为 `failed`；其字段与快照语义依据安装版本源码确认，因此等级判定
仍为 B（当前快照，不可回填历史），不把“接口存在”等同于“权威历史已补齐”。

## 2. 等级定义

- **A级（正式权威输入）**：交易所官方简称/全称变更记录（含生效日期）、交易所官方证券
  列表、证监会指定信息披露平台巨潮资讯的官方公告检索结果。
- **B级（仅辅助校验）**：东财当前个股信息快照、东财当前风险警示板快照；只用于当前状态
  交叉校验，禁止回填历史。
- **C级（不可使用）**：新浪曾用名列表，因为没有生效日期，无法确定状态区间。

状态历史构建不使用“当前 ST 快照回填”，也不仅凭曾用名或名称中的 ST 推断：ST/*ST 区间
以交易所官方简称变更记录中的“变更日期”为生效日期；2020-01-01 至 2026-07-27 的非 ST
区间由“交易所官方证券列表当前简称 + 巨潮官方公告检索零风险警示/零特别处理记录 +
深交所官方变更记录无 ST 变更”共同支持。

## 3. 证据文件与哈希

探测证据保存在 `reports/stage15_s14_fix/source_probe/6b7c8d9e-0f1a-4b2c-9d3e-4f5a6b7c8d9e/`
（该目录已被 `.gitignore` 忽略，作为运行时证据保留）。关键原始文件 SHA-256：

| 文件 | 大小 | SHA-256 |
| --- | ---: | --- |
| `stock_info_sz_change_name_short.csv` | 401101 | `4f9b2a1dc05951b9eebc76f4cb91b9e45a4b5e74071f331833bc073aebc8f59d` |
| `stock_info_sz_change_name_full.csv` | 193326 | `9657aeebc024e42d8843d6dc488de76aeb596d772035f8e866f3c71f45d4d203` |
| `stock_info_sh_name_code.csv` | 162054 | `d6c98f5912f441aed5f06e1ee230a7b626f87b0daa608cb1706292618d6ed086` |
| `stock_info_sz_name_code.csv` | 235601 | `6aea095e9129b5369f5c9f3ed1a0d7e6006fdd49c49ab94d4351ca4df720f415` |
| `stock_info_change_name.csv` | 445 | `ce662da8a8371a8024bad7a46428b6d2bbffb53d6540af6b320e6fbad60f511b` |
| `cninfo_risk_warning.csv` | 0 | 空文件（零公告证据） |
| `cninfo_special_treatment.csv` | 0 | 空文件（零公告证据） |

完整清单见同一目录 `probe_manifest.json` 与 `source_feasibility_report.json/.csv/.md`。

## 4. 权威规则历史

`config/stage8_authoritative_rules.yml` 定义 15 条 `verified` 规则：

- 沪深主板：普通股票 ±10%（1996-12-16 起）；风险警示股票 ±5%（1998-04-22 起）。
- 创业板：注册制改革前（2009-10-30 至 2020-08-23）普通 ±10%、ST ±5%；
  改革后（2020-08-24 起）普通与 ST 均 ±20%。
- 科创板：±20%（2019-07-22 起），风险警示股票仍 ±20%。
- 北交所：±30%（2021-11-15 起）。
- 上市初期特殊规则：2013-12-13 后上市股票首日有效申报价 +44%/-36%，按个股生效日期
  记录（本仓库 16 只样本中仅 `601500`、`603259`、`300433` 命中）。

每条规则均含 `exchange/board/is_st/symbol/security_type`、生效起止日期、涨跌停比例、
最小报价单位、价格精度、舍入规则、来源、来源发布日期、原始来源哈希、数据版本、验证时间。
模型为现有 `LimitRule`，未新建平行模型；`resolve_limit_rule` 支持个股规则优先、板块规则
兜底，缺口或多重匹配仍 fail-closed。

### 来源哈希方法

交易所规则页面未提供可稳定下载的单一原文文件，且上交所“名称变更”查询接口在本环境未定位
到可用 sqlId。为保持可审计性，规则记录的 `source_hash` 取“官方来源摘要”的 SHA-256，
即对 `{source_name, source_reference, published_at, clause}` 规范化 JSON 计算；状态记录
的 `source_hash` 取“官方证据包”的 SHA-256，即对上述交易所原始抓取文件哈希清单的规范化
JSON 计算。该方法是本报告的明确口径，未声称对交易所完整 PDF 全文做了哈希。

## 5. 权威证券状态历史

`config/stage8_authoritative_status.yml` 定义 17 条 `verified` 状态记录：

- 16 只样本股票各一条非 ST 区间（2020-01-01 至 2026-07-27，`listed`）。
- `000100` 历史 `*ST` 区间（2007-05-08 至 2008-03-28），来自深交所官方简称变更记录，
  用于验证 ST/*ST 历史支持。

每条记录含 `symbol/exchange/board/listing_date/delisting_date/is_st/
special_treatment_type/listing_status/生效起止日期/来源/来源哈希/数据版本`。
区间校验复用 `validate_status_intervals`：重叠拒绝、未知不默认非 ST、每日唯一状态，
无法确定时 Stage 8 保持 BLOCKED。

## 6. 已知限制

1. 东财 `stock_individual_info_em` 与 `stock_zh_a_st_em` 在探测环境中不可达，已记录
   `failed`；当前状态校验以官方列表与巨潮公告为准。
2. 上交所官方名称变更历史未能通过公开查询接口定位，沪市非 ST 区间以“官方当前列表 +
   巨潮公告零变更”为证据，未伪造沪市 ST 历史。
3. 规则 `source_hash` 覆盖官方来源摘要而非交易所 PDF 全文，方法已在第 4 节说明。
