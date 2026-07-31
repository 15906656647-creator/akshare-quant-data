# 阶段 7 每日特征与活跃度评分验证

- 执行时间（UTC）：2026-07-30T08:51:25.338633+00:00
- run_id：`3252ae5d-f0b9-42ad-a27e-f20cc8128718`
- 数据来源表：`main.fact_stock_daily`
- 源数据库：`database/akshare_data_test_stage5_repaired.duckdb`
- 结果数据库：`database/akshare_features_stage7.duckdb`
- as_of_date：2026-07-27
- 复权口径：`qfq`
- 活跃度窗口：最近 120 个有效交易日
- 数据日期范围：2023-07-27 至 2026-07-27
- 股票覆盖：16/16
- 缺失股票：无
- 输入/每日特征/活跃度行数：11602/11602/16
- 评分版本：`activity_v1_pre_limit_event`

## 评分口径

`activity_score = 0.25 × amount_percentile + 0.20 × turnover_percentile
+ 0.20 × volatility_percentile + 0.15 × volume_spike_percentile
+ 0.10 × large_move_percentile + 0.10 × event_frequency_percentile`。

放量和大幅波动频率的分母分别为最近窗口内对应布尔指标非空的有效交易日；
跳空频率的分母为 `gap_return` 非空的有效交易日。当前完整样本中各股票三个
频率分母均为 120。

横截面分位数仅在 `config/universe.yml` 配置的 16 只目标股票之间计算；
构建会排除额外证券，并由正式数据库质量检查验证目标代码集合。

## 每日特征缺失率

| 字段 | 缺失率 |
|---|---:|
| ma_3 | 0.002758 |
| ma_5 | 0.005516 |
| ma_7 | 0.008274 |
| ma_10 | 0.012412 |
| ma_13 | 0.016549 |
| ma_20 | 0.026202 |
| ma_21 | 0.027581 |
| return_1d | 0.001379 |
| volume_ratio_20 | 0.026202 |
| intraday_range | 0.001379 |
| gap_return | 0.001379 |
| volatility_20 | 0.027581 |

## 活跃度排名

| 股票 | activity_score | observation_count | score_status |
|---|---:|---:|---|
| 002361 | 0.907812 | 120 | scored |
| 300274 | 0.817188 | 120 | scored |
| 300433 | 0.754688 | 120 | scored |
| 002129 | 0.721875 | 120 | scored |
| 000100 | 0.709375 | 120 | scored |
| 601636 | 0.656250 | 120 | scored |
| 002600 | 0.612500 | 120 | scored |
| 603799 | 0.604687 | 120 | scored |
| 002067 | 0.564063 | 120 | scored |
| 603259 | 0.514062 | 120 | scored |
| 601012 | 0.384375 | 120 | scored |
| 600438 | 0.357812 | 120 | scored |
| 002230 | 0.295313 | 120 | scored |
| 600231 | 0.265625 | 120 | scored |
| 600763 | 0.212500 | 120 | scored |
| 601500 | 0.121875 | 120 | scored |

## 数据质量

| 检查 | 状态 | 严重级别 | 说明 |
|---|---|---|---|
| input_primary_key_unique | PASS | ERROR | - |
| output_primary_key_unique | PASS | ERROR | - |
| input_output_row_count_equal | PASS | ERROR | - |
| qfq_only | PASS | ERROR | - |
| dates_monotonic_by_symbol | PASS | ERROR | - |
| all_ma_columns_present | PASS | ERROR | - |
| ma_3_full_window | PASS | ERROR | - |
| ma_5_full_window | PASS | ERROR | - |
| ma_7_full_window | PASS | ERROR | - |
| ma_10_full_window | PASS | ERROR | - |
| ma_13_full_window | PASS | ERROR | - |
| ma_20_full_window | PASS | ERROR | - |
| ma_21_full_window | PASS | ERROR | - |
| no_cross_symbol_shift | PASS | ERROR | - |
| no_infinite_features | PASS | ERROR | - |
| volume_ratio_nonnegative | PASS | ERROR | - |
| scores_in_unit_interval | PASS | ERROR | - |
| scored_rows_complete | PASS | ERROR | - |
| activity_business_key_unique | PASS | ERROR | - |
| activity_score_decomposition | PASS | ERROR | - |
| score_metadata_present | PASS | ERROR | - |
| no_extra_symbols | PASS | ERROR | extra= |
| target_symbol_coverage | PASS | WARNING | missing= |
| minimum_activity_observations | PASS | WARNING | symbols= |
| no_extra_activity_symbols | PASS | ERROR | extra= |
| activity_as_of_matches_latest_trade | PASS | ERROR | - |
| database_feature_run_id_current | PASS | ERROR | formal DuckDB post-write verification |
| database_activity_run_id_current | PASS | ERROR | formal DuckDB post-write verification |
| database_activity_row_count | PASS | ERROR | formal DuckDB post-write verification |

通过检查：29/29；
失败检查：0；警告：0。

## 事件代理指标说明

`event_frequency_percentile` 使用跳空频率 `gap_frequency` 的横截面分位数，
`event_component_source='gap_proxy'`。它不是正式涨停或跌停统计，也不是市场操纵
或任何“主力行为”的证据。下一阶段完成基于不复权行情和证券状态历史的真实涨跌停
事件表后，必须升级评分版本。

## 已知限制

- 最近 120 个有效交易日不足时使用实际交易日并保留 `observation_count`。
- 少于配置的最小观察数时标记 `insufficient_observations`，不将缺失分项填为 0。
- 本阶段仅使用前复权日线，不抓取网络数据，不实施正式涨跌停、横盘风格或基本面分析。
