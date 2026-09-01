# Stage 17 分钟级数据可行性报告

- 运行批次：`78cddc46-4b2a-4ebe-9065-1e54e3dff522`
- 业务基准日：`2026-08-24`
- A/H股仅为代表性可行性验证，不构成正式全市场分钟数据资产。
- AKShare无直接3分钟接口；3分钟仅可由1分钟数据在报告层演示聚合，未写入Raw。

| 标的 | 市场 | 周期 | 状态 | 行数 | 限制/错误 |
|---|---|---|---|---:|---|
| 002067 | A | 1m | failed | 0 | HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/trends2/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6%2Cf7%2Cf8%2Cf9%2Cf10%2Cf11%2Cf12%2Cf13&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf5 |
| 002067 | A | 5m | failed | 0 | HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/kline/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58%2Cf59%2Cf60%2Cf61&ut=7eea3edcaed7 |
| 300274 | A | 1m | failed | 0 | HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/trends2/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6%2Cf7%2Cf8%2Cf9%2Cf10%2Cf11%2Cf12%2Cf13&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf5 |
| 300274 | A | 5m | failed | 0 | HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/kline/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58%2Cf59%2Cf60%2Cf61&ut=7eea3edcaed7 |
| 600763 | A | 1m | failed | 0 | HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/trends2/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6%2Cf7%2Cf8%2Cf9%2Cf10%2Cf11%2Cf12%2Cf13&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf5 |
| 600763 | A | 5m | failed | 0 | HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/kline/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58%2Cf59%2Cf60%2Cf61&ut=7eea3edcaed7 |
| 02180.HK | HK | 1m | success | 1655 | - |
| 02180.HK | HK | 3m | report_only_derived | 560 | 由1分钟样本按3分钟分桶演示聚合；未写入Raw，不代表上游直接支持 |
| 02180.HK | HK | 5m | failed | 0 | HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/kline/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58%2Cf59%2Cf60%2Cf61&ut=bd1d9ddb0408 |
| 08365.HK | HK | 1m | failed | 0 | HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/trends2/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6%2Cf7%2Cf8%2Cf9%2Cf10%2Cf11%2Cf12%2Cf13&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf5 |
| 08365.HK | HK | 5m | failed | 0 | HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/kline/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58%2Cf59%2Cf60%2Cf61&ut=bd1d9ddb0408 |
