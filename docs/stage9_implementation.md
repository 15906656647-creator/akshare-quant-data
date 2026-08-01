# 阶段 9：横盘震荡与疑似洗盘风格分析

## 边界与状态

阶段 9 是离线、research-only 的量价风格工程。核心分析读取 qfq OHLC、成交量、
成交额和换手率，不访问网络，不运行阶段 7，不运行阶段 8 正式发布，也不覆盖阶段
7/8 数据库或报告。所有运行必须显式传入 `as_of_date`。

阶段 8 是可选辅助输入。其 `publication_status` 不是 `formal` 时，正式事件频率
保持 NULL；candidate、proxy、gap_proxy 和 unresolved 分列保存，不能混入正式字段。

## 有效交易行与无未来数据

- 仅接受 `adjust_type=qfq`，按 `symbol, trade_date` 稳定排序。
- 价格必须为正，OHLC 关系必须成立，成交量必须大于 0；停牌和零成交行不占窗口。
- 输入在计算前截断至 `trade_date <= as_of_date`。
- 20/40/60 日均指每只证券的有效交易行，样本不足输出 `insufficient_history`。
- 假突破边界只使用突破日前 20 个有效交易日；1～3 个后续有效交易日内返回原箱体
  才确认。确认数据不足时记为 pending，不计入确认次数。

## 特征定义

- 箱体：`high=max(high)`、`low=min(low)`、`box_width=high/low-1`；价格位置为
  `(close-low)/(high-low)`。边界触碰容差取最小相对距离、箱体宽度比例及 ATR 比例
  三者最大值，阈值均来自 `config/stage9.yml`。
- 趋势：对 `log(close)` 和有效交易日序号做 OLS；`normalized_slope=exp(slope)-1`，
  表示可跨价格水平比较的日对数趋势率。常数序列的 R² 定义为 1。
- 波动：日收益率标准差、252 日年化波动率、TR 均值 ATR、ATR/close、布林带宽、
  滚动最大回撤、恢复天数和大波动频率，比例统一使用小数。
- 量价：成交量/成交额均值和归一化趋势斜率、阶段 7 同口径的 20 日量比、放量频率、
  换手率、价量相关、上涨/下跌日成交量占比。
- K 线：上下影、实体、振幅及方向交替均按配置阈值统计。
- 假突破：保存上下突破、确认假突破、pending、伴随放量次数、回箱天数和失败频率。

## 分类与解释

支持温和箱体型、高波动震荡型、放量冲击型、低活跃盘整型、趋势型、数据不足和
未分类或混合型。连续得分来自斜率、R²、箱体、ATR、量价冲击、假突破和流动性；
置信度结合非线性强度、数据覆盖和第一/第二风格分差，最大为 0.95，不解释为概率。
分数接近时输出混合型。解释包含真实箱体、斜率、R²、ATR、放量和假突破数值。
评分权重、尺度、置信度组成和数值容差全部来自 `config/stage9.yml`；模型版本为
`stage9_style_rules_v2`，配置版本为 `1.1.0`，配置文件哈希随 run 保存。

所有结果仅描述横盘震荡风格、疑似洗盘特征、量价行为特征和疑似主力行为特征；
不是确定的主力行为事实，也不构成投资建议。

## 数据库与 CLI

独立输出包含 `feature.stage9_style_feature`、`analysis.stage9_style_profile`、
`quality.stage9_quality_result`、`audit.stage9_run` 和两个 latest 成功视图。主键均含
`run_id`；同 run 重跑替换该快照，不同 run 保留历史；所有写入在事务中完成。
写后门禁以 `1e-12` 浮点绝对容差规范化比较 DuckDB、完整特征 CSV、风格档案 CSV、
质量 CSV、分布 CSV、run JSON 和规范化生成的 Markdown。NULL、JSON null、pandas NA
统一为未知值；发布关键字段、风险声明或 run 谱系任一不一致均以 ERROR 失败并阻断。

```powershell
python run_pipeline.py analyze-style --help
python run_pipeline.py analyze-style --as-of-date 2026-07-27 --validate-only
python run_pipeline.py analyze-style --as-of-date 2026-07-27 --dry-run
```

`validate-only` 以 DuckDB 只读模式核对文件、表、字段、qfq 口径和主键，不创建输出。
`dry-run` 计算内存结果和质量门禁，但不写数据库或报告。
