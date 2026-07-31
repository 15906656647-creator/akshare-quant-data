# 阶段 8：涨跌停统计与事件研究

## 实施状态

阶段 8 的离线计算、数据库、CLI、质量检查和测试已经实现。正式全年统计仍为
**BLOCKED**：仓库尚未提供可审计的完整历史涨跌停规则及证券状态历史。

## 输入和边界

- 只读取阶段 5 `fact_stock_daily` 中 `adjust_type='raw'` 的不复权行情。
- 实际分析查询只选择 `raw/unadjusted`；仅有 `qfq` 或 `hfq` 时直接失败。
- 不重新运行阶段 7 `build-features`，不读写阶段 7 正式数据库。
- 不访问网络；近期涨跌停池只允许作为后续交叉校验依据。
- `gap_proxy` 不是正式涨停或跌停事件。

## 规则和状态

`config/stage8.yml` 默认不包含规则或证券状态记录。这是有意的 fail-closed
设计：不得依据价格走势猜测板块、ST 状态、规则比例或生效日期。

规则记录支持交易所、板块、ST 状态、生效区间、涨跌幅、无价格限制标志、
tick size、价格精度、舍入规则、版本及来源审计字段。证券状态记录支持按
证券和交易日选择，并保存上市状态、板块、ST 状态和来源版本。两类记录均拒绝
重叠区间和缺失来源。

## 计算口径

- 仅当来源名称、引用、版本、证据状态、验证时间、证券、日期、tick 和价格关系
  均通过门禁时，才优先使用当日官方涨跌停价格。
- 来源名称、引用和版本同时拒绝 Python/pandas 缺失值、空白以及
  `nan`、`none`、`null`、`NaT` 等缺失语义字符串（不区分大小写）。
- 否则以昨日真实收盘价和当日规则，用 `Decimal` 计算理论限价。
- 支持 `half_up` 和 `half_even`，再按 tick size 定点舍入。
- 匹配容差为 `abs(close - limit_price) <= tick_size / 2`。
- 后续收益按每只证券排序后的有效交易行计算，不使用自然日偏移。
- 尾部不足 3、5、10 个交易日时保留 NULL 并标记样本状态。
- 年度正式汇总分别保存涨停后的次日开盘、次日收盘及未来 3、5、10 个交易日
  平均收益；blocked 运行的所有正式数量、收益和比例统一为 NULL。

## 数据库

独立输出数据库包含：

- `reference.limit_rule`
- `reference.security_status_history`
- `analysis.fact_limit_event`
- `analysis.v_formal_limit_event`
- `analysis.v_latest_limit_event`
- `analysis.v_latest_formal_limit_event`
- `analysis.limit_event_annual_summary`
- `quality.stage8_quality_result`
- `audit.stage8_run`

事件和汇总主键均包含 `run_id`，同 run 重跑幂等、不同 run 保留历史；latest
视图只指向最新成功 run。业务表通过事务化写入保证失败完整回滚。未解决记录保留在事件
观察事实表中，但只有 `event_type` 为涨停/跌停、证据为 `verified` 且质量为
`pass` 的记录进入正式视图和汇总。

写后 `database_report_consistent` 会实际读取并交叉核对 DuckDB、
`stage8_run.json`、年度汇总 CSV、质量 CSV 和 Markdown。数据库 NULL、JSON
null 与 CSV 空值等价，但数值 0 不与 null 等价；任一产物的 run_id、发布状态、
正式数量、收益、比例、时间窗口、阻塞原因或质量计数不一致都会以 ERROR 阻断发布。

## CLI

```powershell
python run_pipeline.py analyze-limit-events --help
python run_pipeline.py analyze-limit-events `
  --as-of-date 2026-07-27 `
  --validate-only
```

当前默认配置的 `--validate-only` 返回 `BLOCKED`（退出码 2），阻塞项为缺少
权威规则和证券状态历史。它会以只读方式实际打开 DuckDB，并检查表、字段、
raw 口径、类型、日期覆盖和重复键；该模式不创建数据库、目录或报告。用户输入
错误返回简洁信息，只有显式 `--debug` 才显示 traceback。

## 发布结论

机制验证通过不等于正式数据通过。在权威规则和证券状态历史补齐、审核并达到
完整覆盖前，不具备发布正式全年涨跌停统计的条件。无数据、未解决或阻塞状态
不能解释为零次涨停或跌停。本项目仅用于研究和测试，不构成投资建议。
