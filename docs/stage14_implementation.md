# 阶段 14：自动化运行实现

## 范围与复用

本阶段只新增编排，不改变 Stage 0 冻结口径，也不实现 Stage 15 的新增质量规则。
实现复用现有 `argparse` CLI、Stage 2 冒烟测试、Stage 3/4 collectors、Stage 5
Clean + DuckDB、Stage 7 特征、Stage 8/9 分析、Stage 5 数据库验证和 Stage 13
展示入口。网络仍只可能发生在既有 adapter/collector 中，自动化单元测试不访问
网络。

## 运行契约

- `run-all` 固定执行 `config/stage14.yml` 中的 11 步依赖顺序。
- `fetch-market` 的 `--start` 与 `--end` 必须成对提供；只传其中一个会返回
  非零退出码，避免单个日期参数被静默忽略。
- `fetch-market` 的起始日允许为休市日；只要首个交易日落在起始日后的10个
  自然日内，就不会误报 `historical_window_not_covered`。
- 全部子任务共享同一 UUID `run_id`；未指定时自动生成。
- 子任务真实退出码非零即停止，Stage 8 的 `BLOCKED` 也不会被伪装为成功。
- 每个状态包含开始/结束时间、耗时、参数、日期范围、版本、Git commit 和错误摘要。
- 日志写入 `logs/<run_id>/pipeline.log`，状态以临时文件 + 原子替换写入
  `logs/<run_id>/task_status.json`。
- 异常含 traceback；失败项另存为
  `reports/run_status/<run_id>_failed_items.csv`。
- `--dry-run` 只打印计划，不启动任何阶段，也不创建数据、数据库或日志。
- 所有 `git rev-parse` 子进程读取均显式使用 UTF-8 与 `errors="replace"`，
  避免 Windows 中文路径/非 ASCII 输出触发子进程读取线程解码异常。

## 组合步骤说明

仓库的 Stage 4 原生入口一次发布财务与资金流共 96 个不可变 Raw 文件。为避免
同一个 `run_id` 再次写入相同分区，`run-all` 在 `fetch-financial` 完成该组合
入口后，将 `fetch-event-and-fund-flow` 记录为 `skipped`，并保存覆盖原因。若单独
执行该命令，则真实调用 Stage 4 的 `individual_fund_flow` 接口，便于故障恢复。

Stage 5 原生入口将 Clean 生成与 DuckDB 事务发布视为一个原子步骤，且拒绝覆盖
已有数据库。因此 `clean` 运行原生组合入口，随后的 `load-database` 记录为已由
前一步覆盖。若单独执行 `load-database`，则真实复用 Stage 5 原子构建入口。这个
适配保留了既有 Stage 5 的原子性，而没有复制一套清洗/加载逻辑。

## 幂等与安全

- Raw：既有 `RawStore` 使用 `run_id` 分区、临时 Parquet、`os.replace` 原子发布，
  空表不写正式文件，已存在路径直接拒绝。
- Database：既有业务表和分析表继续使用事务及主键 upsert；Stage 14 每个 run
  使用隔离数据库目录，避免覆盖历史批次。
- Clean/Feature/Analysis：沿用阶段实现的排序、窗口和质量门禁；不清空共享正式库。
- Report：调用既有 Stage 13 离线、只读、原子发布流程；报告 manifest 带 `run_id`。

## 已知边界

Stage 8 因权威历史涨跌停规则与证券状态历史缺失，可能按既有 fail-closed 规则返回
`BLOCKED`；`run-all` 会据实失败并停止。Stage 5 正式构建契约要求完整的 16 股
Stage 3/4 manifest，因此 `--only-symbol` 可用于抓取命令的故障定位，但不能把单股
manifest 冒充完整 Stage 5 正式输入。
