# 阶段 11 ETHUSDT 验证与加密资产适配

- run_id：`stage11-ethusdt-20260727`
- run_status：**PASS**
- publication_status：`descriptive_statistics`
- 数据来源：`okx_public_api`；AKShare `crypto_js_spot` 仅用于精确交易对能力探针，不替代历史 K 线来源
- AKShare 精确交易对能力：`unsupported`（exact_match=False）
- 资产：`ETHUSDT` / `OKX` / `crypto`
- 时间口径：UTC 为标准时间，Asia/Shanghai 为展示转换；`1h` K 线；24/7 连续交易，不使用股票交易日历
- 截止日期：2026-07-27
- K 线：960 行；指标：960 行

## 指标适配

波动率、ATR、布林带、趋势、箱体和假突破均可迁移为描述性统计。年化因子按连续交易调整为日线 365、小时线 8760；成交量来自交易所且不等同于股票换手率。箱体和假突破依赖窗口与数据源，不能解释为价格预测。

## 质量门禁

- PASS：11
- FAIL：0
- 阻塞项：
- 无

## 隔离与限制

- `fundamental_analysis` 对 `asset_type=crypto` 返回 `not_applicable`，ETHUSDT 不进入股票财务分析。
- AKShare 历史 ETHUSDT K 线能力未被伪造；若使用 Binance 公共接口，来源明确标为 `binance_public_api`。
- 本阶段只输出统计特征，未形成价格预测、交易策略或投资结论。
