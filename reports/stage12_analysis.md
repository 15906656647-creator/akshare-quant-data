# Stage 12：量化分析示例与结果验证

## 分析目标与范围

- 截止日期：`2026-07-27`
- run_id：`stage12-fixture-20260727`
- 状态：**READY**
- 输出类型：`implementation_validation_fixture`
- 价格口径：前复权 `qfq`；成交量为股、成交额为人民币元、换手率为小数。
- 数据边界：所有价格和基本面记录均在计算前按显式截止日期过滤。

## 指标定义

- 活跃度：120 个有效交易日内成交量、成交额和换手率横截面分位数的配置化加权分数。
- 成交量突破：观察日成交量相对此前 20 个交易日均值、中位数及总体标准差；观察日不进入基线。
- 区间震荡：40 日高低区间、相对宽度、log 收盘价归一化斜率、R² 和内部分位区间外比例联合判断。
- 基本面与价量：只使用可用日期不晚于截止日的财务子分数，并与活跃度、突破、区间和近期动量透明加权。
- 缺失子分数：不填零；按可用权重重新归一化，并保存完整度。

## 结果与质量

- 输入行数：`{'price_visible': 250, 'price_future_excluded': 1, 'fundamental_visible': 2, 'fundamental_future_excluded': 1}`
- 输出行数：`{'active': 2, 'breakouts': 2, 'ranges': 2, 'combined': 2, 'quality': 17}`
- 规范化结果 SHA-256：`4f755345be7b778ed46610b58abefaac691cc4acec19f908d46a9c8ce5838543`
- 阻塞项：
- 无
- 警告：
- future_fundamental_rows_excluded:1
- future_price_rows_excluded:1

## 无未来数据保证

价格仅使用 `trade_date <= as_of_date`；基本面仅使用公告日或可用日不晚于截止日的记录。
未来记录数量单独审计，不参与排名、阈值、历史基线、区间或综合评分。

## 测试与 Git 证据

运行时分析不会伪造测试通过结论。真实专项测试、完整回归、稳定导出复跑、事务故障注入、
冻结文件哈希和 `stage11-complete` 祖先检查记录在 `docs/stage12_acceptance.md`。

## 已知限制与复现

- 组合分数是描述性、可解释的研究指标，不是交易信号或投资建议。
- 缺少可靠基本面可用日期时拒绝输入，不使用报告期替代公告日期。
- 复现需使用相同输入、`config/stage12.yml`、截止日期和 run_id 调用 `analyze-stage12`。
- 本项目仅用于研究和数据能力测试，不构成投资建议。
