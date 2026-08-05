# 阶段15：质量控制和风险验证实现

## 目标

对应《AKShare数据抓取测试_分阶段操作步骤.md》第15章：

- 15.1 每日质量检查：行数异常下降、最新交易日更新、字段集合变化、样本股票缺失、
  OHLC 逻辑关系、主键重复、非法负成交量/金额、PE/PB 缺失率异常、财报关键字段缺失、
  接口执行耗时突增。
- 15.2 交叉验证：对 2～3 只股票生成最近 5 个交易日收盘价/成交量、最近一期营业收入
  和归母净利润、最新 PE/PB、最近一个涨停日及次日开盘价的核对快照，供人工确认数量级
  和字段解释。
- 15.3 风险日志：输出 `risk_id, detected_at, category, interface_name, symbol,
  severity, description, impact, mitigation, status` 十个字段的结构化风险记录。

## 范围

阶段15只实现质量控制与风险验证，不重做阶段1—14，不修改阶段0冻结文件，不新增网络
调用。全部执行离线读取既有 Stage 5 DuckDB、Stage 10 财务字段映射配置以及 Stage 2/4
生成的耗时报告。

## 架构

```text
CLI quality-control
  -> src/akshare_data_test/stage15_config.py   配置加载与严格校验
  -> src/akshare_data_test/stage15_build.py    只读预检、编排、输出发布
  -> src/akshare_data_test/quality/stage15_checks.py
        每日质量检查 / 交叉验证快照 / 风险日志
  -> reports/stage15/<run_id>/*                报告产物
  -> database/stage15/<run_id>/stage15_quality.duckdb
        质量结果、风险日志、交叉验证、运行审计表
```

阶段14的 `quality-check` 命令保持不变（仍映射到 `validate-stage5`），阶段15新增
独立命令 `quality-control`，不破坏阶段14自动化入口。

## 输入

- Stage 5 DuckDB（默认 `database/akshare_data_test_stage5_repaired.duckdb`），只读。
- Stage 10 财务映射 `config/stage10.yml`（只读引用，不修改）。
- 可选 Stage 8 DuckDB（`--stage8-database`），用于交叉验证中的正式涨停事件。
- 可选基线 JSON（`--baseline`），用于行数、字段集合和接口耗时对比。
- 耗时证据：`reports/interface_smoke_test.csv` 与
  `reports/stage4_financial_coverage.csv`。

## 输出

每次运行使用唯一 UUID `run_id`：

```text
reports/stage15/<run_id>/quality_check_results.csv
reports/stage15/<run_id>/quality_summary.json
reports/stage15/<run_id>/cross_validation.csv
reports/stage15/<run_id>/cross_validation.md
reports/stage15/<run_id>/risk_log.csv
reports/stage15/<run_id>/risk_log.json
database/stage15/<run_id>/stage15_quality.duckdb
```

DuckDB 表：

- `quality.check_result(run_id, check_name, category, severity, status,
  observed_value, expected_value, interface_name, message, checked_at)`
- `quality.risk_log(risk_id, run_id, detected_at, category, interface_name,
  symbol, severity, description, impact, mitigation, status)`
- `quality.cross_validation(run_id, symbol, check_item, observed_value,
  source_table, as_of_date, verification_status, note)`
- `audit.stage15_run(...)`

## 配置

`config/stage15.yml` 定义：

- 输入输出目录。
- 最新交易日容差（10 个自然日，与阶段14对齐）。
- 行数异常下降比例（30%）和每表最小行数。
- PE/PB 缺失率阈值（50%）。
- 财报关键字段覆盖率阈值（80%），字段来自 Stage 10 映射。
- 交叉验证股票（`002067`、`600763`、`300274`）和核对项。
- 接口耗时基线倍数（3 倍）与各接口最大秒数。
- Stage 8 阻塞码与 `block_whole_run: false` 策略。
- 风险分类、严重级别和状态枚举。

配置加载器对未知键、缺失键、绝对路径、`..`、保护目录、非 16 只股票、非法枚举和
非有限数值执行 fail-closed 校验，并返回可复现的配置 SHA-256。

## 命令

```powershell
# 只读预检，不写任何输出
python run_pipeline.py quality-control --as-of-date 2026-07-27 --validate-only

# 显示执行计划，不写任何输出
python run_pipeline.py quality-control --as-of-date 2026-07-27 --dry-run

# 正式运行（自动生成 run_id）
python run_pipeline.py quality-control --as-of-date 2026-07-27

# 指定 run_id / 输出路径 / 交叉验证股票
python run_pipeline.py quality-control --as-of-date 2026-07-27 `
  --run-id <uuid> --reports-dir reports/stage15 `
  --output-database database/stage15/<uuid>/stage15_quality.duckdb `
  --cross-validation-symbols 002067 600763

# 提供上一轮 quality_summary.json 作为基线
python run_pipeline.py quality-control --as-of-date 2026-07-27 `
  --baseline reports/stage15/<previous_run>/quality_summary.json
```

## 退出码与错误处理

- `0`：PASS、WARN 或 PASS_WITH_UNAVAILABLE_ITEMS。
  - `PASS`：每日质量检查全部通过，且没有不可用交叉验证项或 BLOCKED 风险。
  - `PASS_WITH_UNAVAILABLE_ITEMS`：每日质量检查通过，但交叉验证仍有
    `UNAVAILABLE` 项或风险日志仍有 `blocked` 记录（例如 Stage 8 权威数据缺失），
    整体状态不会伪装成全部完成。
  - `WARN`：警告级检查失败，不阻断运行。
- `1`：任一 ERROR 级检查 FAIL。
- `2`：输入预检 BLOCKED（数据库缺失、表/字段缺失、无 PASS `etl_run`、输出路径
  受保护或与 `quality` schema 同名等）。

空结果、接口失败和真实无数据严格区分。交叉验证中 Stage 8 涨停项在正式事件不可用
时标记 `UNAVAILABLE` 并写入风险日志，不填充 0，不伪造正式事件。

## 幂等策略

- 每次运行生成唯一 `run_id`（UUID）。
- Raw 层保持阶段1—14的追加与不可覆盖原则，阶段15不写 Raw。
- DuckDB 写入使用主键 `INSERT OR REPLACE`；同一 `run_id` 重跑不会产生重复主键。
- 报告目录已属于其他 `run_id` 时拒绝覆盖。
- 数据库文件名默认 `stage15_quality.duckdb`，避免与 DuckDB `quality` schema
  同名导致目录解析歧义；校验器同时拒绝 stem 为 `quality` 的输出文件。

## 与阶段1—14的衔接

- 输入契约来自 Stage 5（事实表、`etl_run`、`dim_security`）和 Stage 10 财务字段映射。
- 耗时检查复用 Stage 2 冒烟报告与 Stage 4 财务抓取报告。
- 不修改阶段0冻结文件；不修改阶段14 `quality-check` 映射和 11 步顺序。
- 新增模块沿用仓库既有表名拼接写法，保持阶段1目录边界测试通过。

## Stage 8 风险处理

阶段15的每日质量检查和风险日志不依赖 Stage 8 实际产物；只有交叉验证中的
“最近一个涨停日及次日开盘价”两项依赖 Stage 8 正式涨停事件。当前 Stage 8 因
`no_authoritative_limit_rules` 与 `no_authoritative_security_status_history`
保持 BLOCKED，因此：

- 对应交叉验证项输出 `UNAVAILABLE`，不解释为正常空数据；
- 风险日志记录两条 `blocked_input` 状态为 `blocked` 的风险；
- 按配置 `block_whole_run: false`，不阻断阶段15的每日质量检查、风险日志和其余
  交叉验证项；
- 整体状态为 `PASS_WITH_UNAVAILABLE_ITEMS`，不会把 S15-14 未完成伪装为 `PASS`；
- 后续需单独数据治理补齐权威涨跌停规则与证券状态历史后重跑，将 S15-14 从
  `UNAVAILABLE` 转为实际可核对数据后，才能判定阶段15完全通过。

## 使用说明

阶段15用于每日/定时质量监控。建议先 `--validate-only` 预检，正式运行后以
`quality_summary.json` 作为下一次运行的基线，形成行数、字段和耗时的连续对比。
交叉验证 Markdown 表格供人工核对数量级和字段解释。项目仅用于研究测试，
不构成投资建议。
