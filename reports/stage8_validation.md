# 阶段 8 涨跌停统计与事件研究验证

- 工程修复自测：**PASS（待重新独立验收）**
- 正式全年统计：**BLOCKED**
- run_id：`aa8ca663-351c-441e-91fe-f056189fdf1e`
- 输出类型：`validation`（不是正式结果）
- 价格口径：`raw`
- 统计窗口：2025-07-27 至 2026-07-27
- 正式事件数：未计算（不是 0）
- candidate/unresolved：未计算
- 规则与证券状态覆盖：0/0，未具备权威历史资料

## 正式发布阻塞项

- `no_authoritative_limit_rules`
- `no_authoritative_security_status_history`

## 验证结果

- 阶段 8：134 passed
- 阶段 7 回归：22 passed
- 完整套件：356 passed，0 failed，0 skipped，0 xfailed
- 冻结配置：相对阶段 7 标签无差异（`git diff --exit-code` 为 0）
- 默认只读预检：BLOCKED，退出码 2；raw 3,862 行，输出数据库前后均不存在

当前没有运行正式全年阶段 8 分析，也没有生成正式阶段 8 数据库。缺少权威
规则、ST/板块/上市状态历史时，系统必须 fail-closed；`gap_proxy`、candidate、
proxy 和 unresolved 均不得进入正式年度统计。

本报告仅用于工程验证，不构成投资建议。
