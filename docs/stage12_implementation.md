# Stage 12：量化分析示例与结果验证

## 边界与状态

Stage 12 是完全离线、显式截止日期、research-only 的分析层。正式入口只接受调用者
传入的价格表和可选基本面表，不调用 AKShare、HTTP 客户端或现有抓取器，不修改
Stage 0 冻结配置，也不读写 Stage 11 Raw、DuckDB、报告或标签。

正常数据仅在全部 ERROR 质量门禁通过时返回 `READY`。警告、阻塞项和未来被排除记录
分别保存，不把未知值解释为零。本阶段所有组合结果均为描述性统计，不构成投资建议。

配置加载采用封闭且逐字段的范围校验：窗口必须为非布尔整数，阈值、比例、权重和输出
精度必须有限且处于各自合法范围，CSV 编码必须能由 Python 编码注册表解析。非法基本面
评分输入在任何裁剪或加权前阻断，并以 `BLOCKED`、非零退出码和字段级
`blocking_reasons` 返回；阻断运行不创建数据库或报告。

## 实际复用与新增

复用的既有口径：

- Stage 7：前复权日线、成交量/成交额/换手率及横截面平均秩分位数。
- Stage 9：直接共享 `compute_range_width` 和 `compute_log_trend`，统一箱体宽度、
  log 收盘价 OLS 斜率、归一化日斜率及 R²。
- Stage 10：基本面可用日期约束、盈利能力和财务健康分数兼容字段。
- Stage 9/10 repository：独立数据库、run 维度主键、事务替换和 latest 成功视图模式。
- Stage 9/10 质量框架：ERROR/WARNING 分离、稳定排序及跨产物规范化思想。

新增 `stage12_config.py`、`analysis/` 下四类分析模块、统一
`stage12_analysis.py`、`quality/stage12_checks.py`、
`storage/stage12_repository.py`、`sql/stage12_schema.sql` 及 CLI 子命令。

没有直接调用 Stage 7 的旧活跃度函数，因为冻结的 Stage 7 分数还包含波动率、跳空代理
等 Stage 12 输出契约以外成分，并且字段名不同；Stage 12 复用其横截面排名定义，按本阶段
明确的成交量、成交额和换手率合同重新组合。没有直接读取 Stage 9/10 正式结果，因为当前
仓库的两阶段报告明确标记为尚未正式运行，Stage 10 还缺少已验证 Stage 5 manifest。

## 指标口径

### 活跃股票

- 默认窗口：120 个交易日；最少 90 个正成交量日。
- 正成交量日计算平均成交量、成交额和换手率；零成交日单独计算比例。
- 三个横截面分位数按 0.30、0.40、0.30 加权。
- 缺失换手率不填 0，分数保持 NULL 并标记 `turnover_missing`。
- `activity_score >= 0.70` 为配置化、含边界的筛选条件。

### 成交量突破

- 观察日为截止日前最近可见交易日。
- 历史基线为观察日前 20 个交易日，明确排除观察日；至少 15 日。
- 同时满足相对均值倍数、中位数倍数、总体标准差 Z-score 和最小成交量条件。
- 零方差时 Z-score 保持 NULL，标记原因且不误报。

### 区间震荡

- 默认使用最近 40 个有效交易日。
- 绝对区间宽度为 `max(high)-min(low)`；相对宽度严格复用 Stage 9 权威公式
  `max(high)/min(low)-1`。
- 对 `log(close)` 按交易日序号 OLS；归一化斜率为 `exp(slope)-1`。
- 同时检查区间宽度、斜率绝对值、R² 和收盘价位于 10%～90% 分位带外的比例。
- 常数价格的斜率和归一化斜率在浮点容差内为 0，R² 按 Stage 9 约定为 1，
  区间位置定义为 0.5。

### 基本面结合价量

- 仅使用 `available_date`、`announcement_date` 或
  `fundamental_as_of_date <= as_of_date` 的最近记录。
- 兼容 Stage 10 的 `profitability_score`、`financial_health_score`、
  `revenue_growth` 和 `profit_growth`；缺失估值或子评分不填零。
- 所有直接子评分与原始增长率在回退、裁剪和加权前统一验证为可转换的有限数值；
  `revenue_growth`、`profit_growth` 的合法有限正负值仍沿用既定映射，NaN、Infinity、
  -Infinity 和非法字符串均结构化阻断。
- 基本面分数和最终组合分数均按可用权重重新归一化，同时保存完整度。
- 标签为 `strong_characteristics`、`moderate_characteristics`、
  `limited_characteristics` 或 `insufficient_data`，不是买卖建议。

## 存储、哈希与幂等

独立 DuckDB 包含四张 `analysis.stage12_*` 表、
`quality.stage12_quality_result` 和 `audit.stage12_run`。所有业务主键均包含
`run_id, instrument, as_of_date`。同 run、相同输入和配置可重复运行；同 run 对应不同
输入或配置时拒绝覆盖。删除旧 run、插入新结果和审计行在同一事务内执行，故障回滚不会
破坏原结果。

输入哈希只覆盖截止日期可见记录，因此修改未来记录不会改变输入哈希或任何输出。
每类输出显式稳定排序并生成 SHA-256，再组合为 `canonical_sha256`。相同输入、配置、
截止日和 run_id 的 JSON、CSV 和 Markdown 内容保持一致。

## CLI 与复现

```powershell
python run_pipeline.py analyze-stage12 `
  --as-of-date 2026-07-27 `
  --config config/stage12.yml `
  --price-input path/to/prices.csv `
  --fundamental-input path/to/fundamentals.csv `
  --reports-dir reports `
  --output-database database/akshare_stage12.duckdb `
  --run-id example-run
```

`--dry-run` 只在内存计算，不创建报告目录或数据库。stdout 仅输出单个 JSON 对象，
诊断写入 stderr。自动化测试通过全局 socket 阻断证明核心分析不访问网络。

## 报告与限制

Stage 12 固定报告包括 run JSON、Markdown、四张分析 CSV 和质量 CSV。仓库内如保存
实现验证样例，必须明确标记 `implementation_validation_fixture`；它只证明算法、
事务、导出和对账能力，不冒充未经验证的真实基本面结果。

当前设计不计算策略盈亏比，也不推断确定性“主力”行为。任何相关扩展必须使用术语
“疑似主力行为特征”，同时提供证据、置信度和解释。
