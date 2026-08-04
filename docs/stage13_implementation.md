# Stage 13：测试数据呈现、数据库展示与可复现报告

## 生产入口

```powershell
python run_pipeline.py present-stage13 `
  --as-of-date 2026-07-27 `
  --config config/stage13.yml `
  --input-database database/akshare_data_test_stage5_repaired.duckdb `
  --reports-dir reports/stage13 `
  --run-id stage13-20260727-reverify-remediation
```

入口只读本地 Stage 5、Stage 6、Stage 7 DuckDB，不调用网络。`--dry-run` 验证配置、可见输入身份、数据库和输出约束，但不创建或修改报告。正式修复重建使用配置中显式的 `overwrite: true`；同一 run ID 与不同配置、可见输入、截止日或证券集合的冲突仍在覆盖判断之前被阻断。

## 可复现身份

- `config_sha256`：当前配置文件原始字节哈希。
- `visible_input_sha256`：所有截止日可见输入表的规范化内容哈希，包含 Stage 6 事件权威 `raw_close`。
- `canonical_sha256`：配置、可见输入、资产 manifest、截止日数据库清单和 SQL 元数据的规范哈希。
- `run_identity_sha256`：配置、可见输入、截止日、证券集合与 run_id 的运行身份。

DuckDB 物理文件哈希只用于单次运行读前/读后不变性检查，不参与发布身份，也不写入发布文件。

## Schema-aware database inventory

inventory 从 `information_schema.columns` 同时读取列名和 DuckDB 类型：

- `DATE` 使用显式 DATE 比较并包含截止日。
- `TIMESTAMP` 和 `TIMESTAMP WITH TIME ZONE` 使用相应显式类型及次日零点的排他上界，完整包含截止日。
- 具有业务可见日期语义的 `VARCHAR` 使用 `TRY_CAST(... AS TIMESTAMP)`；非空解析失败值计入 `parse_failure_count`，该行标为 PARTIAL，不让单个坏值使整表失败。
- 无业务日期列的静态表使用 `NOT_APPLICABLE`。
- `feature_lineage.created_at` 是 lineage 创建审计时间，不代表业务数据可见日期，因此记录实际类型 `VARCHAR`，但 `date_filter_mode=NOT_APPLICABLE`。

每行保留 `date_filter_column`、`date_column_type`、`date_filter_mode`、`parse_failure_count`、`status` 和 `error`。发布前统一计算 `inventory_blocked_count`；大于零时运行状态为 BLOCKED、退出码非零、质量检查 FAIL，并保留已有正式报告。没有旧报告的故障 fixture 会原子发布最小 BLOCKED 诊断目录，供自动化核对失败质量记录。

## 事件价格合同

- 涨跌停只读取 Stage 6 `feat_limit_event` 的 confirmed 记录，不使用固定 ±10% 重算。
- `event_price` 权威来源为 `feat_limit_event.raw_close`，`event_price_source` 固定记录该字段来源。
- `limit_events.csv` 保留 `symbol,trade_date,limit_direction,limit_status,event_price,event_price_source,detection_confidence,uncertainty_reason,as_of_date`。
- 事件图纵轴直接使用同一 CSV `event_price`；不再用方向占位值作为事件点价格。
- confirmed 事件价格缺失、非有限或非正数时不填 0；事件与次日收益资产降为 PARTIAL，并记录原因。
- 次日开盘收益保持 `next_trade_day_open / event_day_close - 1`，其中 `event_day_close` 与权威 `event_price` 相同；截止日后价格不参与补齐。
- 源存在但零 confirmed 事件时，仍输出带完整价格 schema 的空 CSV 和合法无事件图。

## 资产语义与发布

- 价格与成交量均线直接读取 Stage 6 正式特征。
- 活跃度保留 Stage 7 分数，只新增稳定横截面排名、百分位、完整度和原因码。
- 财务只展示 `announcement_date <= as_of_date` 的点时可见累计值。
- 估值只展示截止日前真实快照，不回填历史。
- 资金流只使用 as-of-safe 视图；相关解释只能称为**疑似主力行为特征**。

所有图、表、SQL、manifest 和报告先写入同级临时目录，完整校验后原子替换正式目录；失败时保留上一版。PNG 使用 Agg、固定 DPI、固定尺寸和受控元数据，并显式关闭 figure。项目仅用于研究和数据链路测试，不构成投资建议。

## S13-REVERIFY 修复证据

| 问题 | 根因 | 修复 | 故障注入与测试 | 状态 |
|---|---|---|---|---|
| S13-REVERIFY-001 | 将 VARCHAR `created_at` 与 DATE 直接比较，且 inventory BLOCKED 未传播 | schema-aware 过滤；lineage 审计字段 NOT_APPLICABLE；发布前统一阻断门禁 | 类型矩阵、三个正式数据库、真实报错 view、质量 CSV、旧报告保留 | CLOSED |
| S13-REVERIFY-002 | confirmed 事件导出丢弃 Stage 6 `raw_close` | 新增 event_price/source/as_of，图表和收益共用权威价格 | 两个已知事件逐行源/CSV/图表对账；六类非法价格；零事件 schema | CLOSED |
| S13-REVERIFY-003 | 测试只覆盖 Stage 5 inventory 且未断言事件价格 | 扩展为真实数据库、完整报告和黑盒发布测试 | 定向 26 项；Stage 13 共 68 项；完整回归 799 项 | CLOSED |
