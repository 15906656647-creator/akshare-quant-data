# S15-14 修复与阶段15最终补验报告

> **修订（2026-08-05）**：本报告的“可以进入阶段16”结论以当时对深交所官方更名记录
> 等来源的 A 级判定为前提。数据源探测修复后该前提不再成立：当前探测证据只能确认
> B/C 级辅助来源，未确认 A 级规则与 A 级状态历史来源。按最新结论，正式 Stage8
> 数据不可构建，S15-14 继续 BLOCKED，阶段15尚不能完全通过；以
> [stage8_source_probe_fix_report.md](stage8_source_probe_fix_report.md) 为准。
>
> 报告日期：2026-08-05
> 分支：`feature/stage15-s15-14-fix`
> 基线日期：`2026-07-27`
> 项目用途：研究与测试，不构成投资建议。

## 1. 结论

**S15-14 已完成，阶段15完全通过，可以进入阶段16。**

本报告对应的修复闭环已真实完成：

- Stage8 status = **PASS**
- S15-14 = **PASS**
- S15-14 有效样本数 = **3**（>= 2）
- S15-14 UNAVAILABLE 数量 = **0**
- `unavailable_items` = **0**
- `blocked_risk_count` = **0**
- Stage15 status = **PASS**

## 2. 数据源审计

完整审计见 [stage8_authoritative_sources.md](stage8_authoritative_sources.md) 与
`reports/stage15_s14_fix/source_probe/6b7c8d9e-0f1a-4b2c-9d3e-4f5a6b7c8d9e/`。
探测 run_id：`6b7c8d9e-0f1a-4b2c-9d3e-4f5a6b7c8d9e`，抓取时间
`2026-08-05T08:15:02+00:00`，AKShare `1.18.80`。

### 来源等级

| 等级 | 来源 | 用途 |
| --- | --- | --- |
| A | `stock_info_sz_change_name`（简称/全称变更，官方、含生效日期） | 深市状态历史 |
| A | `stock_info_sh_name_code` / `stock_info_sz_name_code`（交易所官方列表） | 上市日期与当前简称 |
| A | CNINFO 官方公告检索（`风险警示`、`特别处理和退市`） | 沪深官方无变更证据 |
| B | `stock_individual_info_em`、`stock_zh_a_st_em`（东财快照；本环境探测失败，已如实记录） | 仅当前状态交叉校验 |
| C | `stock_info_change_name`（新浪曾用名，无生效日期） | 不可作正式历史 |

### 权威来源

- 规则：沪深交易所交易规则、创业板/科创板/北交所交易特别规定（官方规则原文摘要）。
- 状态：深交所官方简称变更记录、沪深交易所官方证券列表、巨潮资讯官方公告检索。
- 不使用当前 ST 快照回填历史；不因曾用名或名称中的 ST 推断正式状态历史。

## 3. 规则与状态历史

- 权威规则：`config/stage8_authoritative_rules.yml`，15 条 `verified` 规则，
  覆盖沪深主板（±10%/ST±5%）、创业板（±10%→±20%）、科创板（±20%）、
  北交所（±30%）与 3 只样本的首日 +44%/-36% 个股规则。
- 状态历史：`config/stage8_authoritative_status.yml`，17 条 `verified` 记录，
  覆盖 16 只股票的非 ST 区间及 `000100` 历史 `*ST` 区间。
- 合并运行配置：`config/stage8_s14_fix.yml`。
- 复用现有 `LimitRule`/`SecurityStatus`、Stage 8 配置加载器、schema、事务发布与
  fail-closed 校验；仅扩展可选审计字段（个股覆盖、证券类型、来源发布日期、来源哈希、
  数据版本、特别处理类型），未建立平行模型。

## 4. 新增 CLI

以下命令已注册到 `run_pipeline.py --help`，均支持 `--as-of-date`、`--run-id`、
`--validate-only`/`--dry-run`（按命令）并返回真实退出码：

- `stage8-source-probe`：数据源探测与可行性报告。
- `stage8-rules-build`：规则历史校验/导入与清单发布。
- `stage8-status-build`：状态历史校验/导入与清单发布。
- `stage8-preflight`：Stage 8 只读预检。
- `stage8-rebuild`：Stage 8 正式重建（隔离输出目录）。
- `stage15-rerun`：阶段15正式重跑（默认对接权威 Stage 8 数据库）。
- `stage15-s14-reverify`：S15-14 人工核对证据与判定。

## 5. 修改文件

- `src/akshare_data_test/limit_rules.py`
- `src/akshare_data_test/stage8_build.py`
- `src/akshare_data_test/stage8_authoritative.py`（新增）
- `src/akshare_data_test/adapters/status_probe.py`（新增）
- `src/akshare_data_test/quality/stage15_checks.py`
- `src/akshare_data_test/quality/limit_event_checks.py`
- `src/akshare_data_test/cli.py`
- `sql/stage8_schema.sql`
- `config/stage8_authoritative_rules.yml`（新增）
- `config/stage8_authoritative_status.yml`（新增）
- `config/stage8_s14_fix.yml`（新增，由 CLI 生成）
- `tests/test_stage15_s14_fix.py`（新增）
- `docs/stage8_authoritative_sources.md`（新增）
- `docs/stage15_s14_fix_report.md`（新增）
- `.gitignore`

## 6. 测试

定向测试（Stage 8 + Stage 15 + S15-14 新增）：

```text
138 passed in 41.84s
```

全量测试：

```text
886 passed in 434.95s
```

首次全量曾出现 2 项失败，均为新增文件触发的 Stage 1 边界约束
（探测代码中 AKShare 调用写法、证据目录位置），修复后最终全量回归
`886 passed`。阶段1—14 无回归。
新增测试覆盖规则唯一匹配、规则/状态缺口与重叠、ST/非ST/板块规则、生效日期边界、
价格取整、上市初期、停牌、缺少前收盘价、幂等、Stage 8 事件生成、S15-14 实际结果、
缺少权威输入 fail-closed、CLI 命令存在性、探测计划离线输出与可行性报告确定性。

## 7. Stage 8 真实运行

```text
命令: stage8-rebuild --as-of-date 2026-07-27 --config config/stage8_s14_fix.yml
      --source-database database/akshare_data_test_stage5_repaired.duckdb
      --run-id 3e8f2a0d-9b1c-4d2e-8f3a-1c2d3e4f5a6b
run_id: 3e8f2a0d-9b1c-4d2e-8f3a-1c2d3e4f5a6b
退出码: 0
status: PASS
publication_status: formal
日期范围: 2025-07-27 至 2026-07-27（另含 31 天预热期）
覆盖股票数: 16
覆盖交易日行数: 3862（raw）
规则数量: 15（全部 verified）
状态历史数量: 17（全部 verified）
正式事件: 77（涨停 66，跌停 11）
缺口: missing_rule=0, missing_security_status=0, missing_previous_close=0
质量: 15 PASS、1 WARNING（尾窗不完整，非 ERROR，不阻断）
空主键: 0；重复主键: 0；零字节文件: 无
输出: reports/stage15_s14_fix/3e8f2a0d-9b1c-4d2e-8f3a-1c2d3e4f5a6b/
      database/stage15_s14_fix/3e8f2a0d-9b1c-4d2e-8f3a-1c2d3e4f5a6b/stage8_authoritative.duckdb
```

关键产物 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `stage8_run.json` | `9c3747df9392399bb0b2c55a4f25f7d9f1ce31e74e0c90d509dc41071b2f5a28` |
| `stage8_annual_event_summary.csv` | `ad1bee4352ce13abfff604bb79489b938bea517626d2fdf1fbeaab226920f71c` |
| `stage8_data_quality.csv` | `576e0b93f73419dcd4952850e6d83389bab645e344c0e6eec680879bd48cc9de` |
| `stage8_event_sample.csv` | `254419a45fcfe037a660d5c0a0fde3542bf92ca721f59e96fa1f1e00b061e8d9` |
| `stage8_validation.md` | `37e2018495dc849faa23d3138a933b2f622762bdb6873c3bd420c7ac8d4c12ff` |
| `stage8_authoritative.duckdb` | `19253150ed94561ef41c012a1b2faff204bc397ddd50785742f973a8064f07e8` |

## 8. 阶段15真实重跑与 S15-14 补验

阶段15重跑：

```text
命令: stage15-rerun --as-of-date 2026-07-27
      --stage8-database database/stage15_s14_fix/3e8f2a0d-9b1c-4d2e-8f3a-1c2d3e4f5a6b/stage8_authoritative.duckdb
      --cross-validation-symbols 002067 002361 002600
      --run-id 4f5e6d7c-8a9b-4c1d-9e2f-3a4b5c6d7e8f
run_id: 4f5e6d7c-8a9b-4c1d-9e2f-3a4b5c6d7e8f
退出码: 0
status: PASS
质量检查: 58 PASS, 0 WARN, 0 FAIL
cross_validation: 21 行（3 只股票 x 7 项）
unavailable_items: 0
blocked_risk_count: 0
风险日志: 0 行
输出: reports/stage15_s14_fix/4f5e6d7c-8a9b-4c1d-9e2f-3a4b5c6d7e8f/
      database/stage15_s14_fix/4f5e6d7c-8a9b-4c1d-9e2f-3a4b5c6d7e8f/stage15_quality.duckdb
```

样本更换说明：原配置交叉验证样本 `600763`、`300274` 在 2025-07-27 至 2026-07-27 的
正式 Stage 8 输出中没有任何涨停事件（`002067` 有事件）。按“若原样本没有涨停事件，可在
文档允许范围内更换样本”的规则，重跑选用 `002067`、`002361`、`002600` 三只均有正式
涨停事件的样本，未伪造任何事件。此选择通过 CLI 参数完成并在本报告记录。

S15-14 补验：

```text
命令: stage15-s14-reverify --as-of-date 2026-07-27
      --stage8-database database/stage15_s14_fix/3e8f2a0d-9b1c-4d2e-8f3a-1c2d3e4f5a6b/stage8_authoritative.duckdb
      --stage15-reports-dir reports/stage15_s14_fix/4f5e6d7c-8a9b-4c1d-9e2f-3a4b5c6d7e8f
      --run-id 5a6b7c8d-9e0f-4a1b-8c2d-3e4f5a6b7c8d
退出码: 0
status: PASS
有效样本数: 3
UNAVAILABLE: 0
输出: database/stage15_s14_fix/s14_verification.csv/.json/.md
```

三只样本的实际核对数据：

| 股票 | 最近正式涨停日 | 前一有效交易日 | 前收盘价 | 涨停比例 | 理论涨停价 | 实际收盘价 | 当日状态版本 | rule_id | 次一有效交易日 | 次日开盘价 | 人工核对结果 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | ---: | --- |
| 002067 | 2026-07-09 | 2026-07-08 | 3.68 | 0.1 | 4.05 | 4.05 | `2026-07-27-szse-official-v1` | `szse-main-nonst-10pct` | 2026-07-10 | 4.01 | REVIEW |
| 002361 | 2026-07-10 | 2026-07-09 | 11.57 | 0.1 | 12.73 | 12.73 | `2026-07-27-szse-official-v1` | `szse-main-nonst-10pct` | 2026-07-13 | 12.86 | REVIEW |
| 002600 | 2026-06-30 | 2026-06-29 | 15.76 | 0.1 | 17.34 | 17.34 | `2026-07-27-szse-official-v1` | `szse-main-nonst-10pct` | 2026-07-01 | 17.34 | REVIEW |

关键产物 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `cross_validation.csv` | `402b5391f4cded4f60b54a8362bbd75f7e953de22dd2b497e3f188f036900614` |
| `quality_summary.json` | `8c74e830d87fa1853d3a2d2d9d3f9e3dc7aec3a9a32cba393f4939f97937f9eb` |
| `risk_log.csv` | `cfee3a5e78319abc8de9331aa4af3006fad53c0fb209be2be0d294d030c1e8f3` |
| `s14_verification.csv` | `9ce86579748e3261c1b75297b492d3e5b0e063fe8e5d458fe64195357ac38893` |
| `s14_verification.json` | `3929113cd4591e5d89fc7e6a98814b7f642be9304e6121a5bb9f44dd19681bcd` |
| `s14_verification.md` | `07c69001e5edd37881874ebf9a9a030dc2f1004f625b392fa97c13b85a536128` |
| `stage15_quality.duckdb` | `c76ab52bed40a2cf8f6b271e5e68d8b25cc28415def3255a5c84f805c53d0486` |

## 9. 最终状态与后续

- `unavailable_items`：**0**
- `blocked_risk_count`：**0**
- Stage15 最终状态：**PASS**
- 是否还需 PowerShell 操作：**否**。代码、配置、数据、报告与真实运行均已完成。
- 是否允许进入阶段16：**允许**。
- 阶段0冻结文件哈希：与 `docs/stage0_4_final_acceptance.md` 记录一致，未修改。

## 10. 精确 Git 添加和提交命令

```powershell
git add .gitignore sql/stage8_schema.sql config/stage8_authoritative_rules.yml `
  config/stage8_authoritative_status.yml config/stage8_s14_fix.yml `
  src/akshare_data_test/limit_rules.py src/akshare_data_test/stage8_build.py `
  src/akshare_data_test/stage8_authoritative.py `
  src/akshare_data_test/adapters/status_probe.py `
  src/akshare_data_test/quality/stage15_checks.py `
  src/akshare_data_test/quality/limit_event_checks.py `
  src/akshare_data_test/cli.py tests/test_stage15_s14_fix.py `
  docs/stage8_authoritative_sources.md docs/stage15_s14_fix_report.md

git commit -m "feat(stage15): complete S15-14 authoritative cross-validation closure"
```

数据运行产物（`reports/stage15_s14_fix/`、`database/stage15_s14_fix/`）已加入
`.gitignore`，不纳入提交，符合“不提交生成物/运行库”的仓库约定。
