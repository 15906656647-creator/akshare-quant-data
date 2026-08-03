# 阶段 11：ETHUSDT 验证与加密资产适配

## 边界

本阶段验证工程架构对非股票资产的支持，不建立交易策略、不预测价格、不输出投资建议。
业务截止日必须由 `--as-of-date` 显式传入。Stage 7–10 数据库、标签和报告不作为
Stage 11 输出目标，也不被改写。

## 资产与数据来源

统一资产接口除兼容字段外，强制同时保存 `requested_instrument`、`raw_instrument`、
`normalized_instrument`、`data_provider`、`raw_exchange`、`normalized_exchange`、
`instrument_type` 和 `bar_interval`。原始身份必须在任何标准化赋值前完成验证；缺失值
不会用配置默认值补齐。股票使用交易所会话日历；ETHUSDT 使用
`crypto / continuous_24_7`。错误地给 crypto 分配股票日历会直接失败。

AKShare `crypto_js_spot` 只用于实时能力探针，必须精确匹配 `ETHUSDT`；ETHUSD 或其他
ETH 交易品种只能记为 `partial_success`，不能改名。历史 OHLCV 由独立交易所适配器
提供，来源字段不得写成 AKShare。本次验证中 Binance 公共端点返回 HTTP 451，正式
数据改用 OKX 公共历史 K 线接口的精确 `ETH-USDT` 现货品种，来源记录为
`okx_public_api`。

## 时间与指标

标准时间为 UTC，同时保存 Asia/Shanghai 展示时间、UTC 日界线和本地日界线。小时线
连续性按一小时检查，日线按 UTC 自然日切分；周末和每天 24 根小时线是预期数据，
不使用 A 股交易日历。

Stage 9 的指标定义按加密口径迁移：波动率、ATR、布林带、趋势、箱体、假突破。
股票专属 `qfq`、换手率和 252 交易日年化因子不迁移。加密日线年化因子为 365，
小时线为 8760。所有结果仅为描述性统计；假突破取决于窗口和确认期，不是价格预测。

## 隔离、数据库与质量门禁

`fundamental_analysis` 显式拒绝 `asset_type=crypto`，状态为 `not_applicable`。
Stage 11 独立数据库包含：

- `raw.crypto_market_data`
- `clean.crypto_price_fact`
- `feature.crypto_indicator`
- `analysis.crypto_profile`
- `quality.stage11_quality_result`
- `audit.stage11_run`

写入按 run 和业务主键 upsert，同 run 重跑幂等，跨 run 保留历史。Repository 在事务
开始前再次校验身份不变量，SQL 对精确身份增加非空和检查约束。旧版 Stage 11 数据库
缺少原始身份列，严格验证会拒绝，必须从可信 Raw 证据重建，不能静默迁移为可信。

每个历史数据 run 的 Raw 目录包含 `request.json`、`response.json`、`metadata.json` 和
`manifest.json`。manifest 记录请求、身份、抓取时间、行数、schema hash、响应内容哈希
以及证据文件哈希。AKShare 探针保存完整未筛选响应并独立标注 `unsupported`。

质量检查覆盖严格输入顺序、整点、逐小时连续、配置起止范围、数学期望数量、UTC/本地
往返、原始及标准身份、完成K线、有限数值、OHLC、非负成交量、run_id、周末和 24 小时。
CSV/JSON/DuckDB 一致性只在实际写入并完成全量 canonical 对账后记录结果。

## CLI

```powershell
python run_pipeline.py validate-crypto --as-of-date 2026-07-27 --run-id RUN_ID --raw-evidence-dir path/to/raw --validate-only
python run_pipeline.py validate-crypto --as-of-date 2026-07-27 --input-csv path/to/eth.csv --raw-evidence-dir path/to/raw --run-id RUN_ID --interval 1h --dry-run
python run_pipeline.py validate-crypto --as-of-date 2026-07-27 --fetch-live --provider okx --probe-akshare
```

自动化测试默认阻断真实网络；只有显式 `--fetch-live` 和 `--probe-akshare` 才访问公共
只读接口。`validate-only` 不访问网络、不创建或修复文件，只读取指定 run 的 Raw、CSV、
JSON 和 DuckDB；任何哈希、主键、身份、时间或逐行值差异均返回非零退出码。系统仅用于
数据能力研究和统计特征验证，未形成投资结论。
