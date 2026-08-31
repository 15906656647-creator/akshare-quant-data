# 阶段16：最终历史数据存在性报告

## 范围

阶段16只汇总冻结样本中的16只A股与ETHUSDT，基准日固定为 `2026-07-27`。港股被明确
排除，不审查、不抓取、不分析，也不修改阶段0范围。

## 命令

```powershell
python run_pipeline.py final-report --as-of-date 2026-07-27 --validate-only
python run_pipeline.py final-report --as-of-date 2026-07-27 --dry-run
python run_pipeline.py final-report --as-of-date 2026-07-27 --run-id <uuid>
```

## 输入与输出

命令只读 Stage 5、Stage 6、Stage 7 和 Stage 11 DuckDB，不访问网络。正式运行输出：

- `stock_coverage.csv`：16只A股逐代码覆盖、均线、财务、估值、活跃度、风格及阻塞项。
- `crypto_coverage.csv`：ETHUSDT来源、周期、时间范围、行数和特征覆盖。
- `availability_matrix.csv`：按完整、部分存在、缺失、制度上不适用、不可正式发布分类。
- `final_report.md`：面向交付的最终检查报告。
- `stage16_run.json`：输入哈希、范围、状态、输出清单及零网络调用证据。

## 发布规则

- 晚于基准日的PE/PB只记录为未来快照，禁止回填历史。
- 没有权威证券状态与每日适用阈值时，涨跌停次数及次日开盘表现保持不可发布。
- 600438和601500的行情缺口在缺少历史证券状态时只标记待核验，不武断认定为停牌。
- 相关行为分析统一称为“疑似主力行为特征”，必须保留证据、置信度和解释。
- ETHUSDT明确标记为OKX公共接口数据，不描述为AKShare来源。
- 输出仅用于研究和数据工程验证，不构成投资建议。