# Stage 18.2 基本面正式全量 Raw 采集实施记录

## 阶段范围

本阶段仅实现 16 只 A 股和 7 只港股的正式基本面 Raw 全量采集。唯一证券主数据上游为
Stage 17 run `4a5599fb-9e60-4013-9c0c-69fcc25a98b2`，入口授权来自
Stage 18.1 run `4915ea1b-2e00-4a34-a743-d35dfcb66fe2`。

Stage 18.1 的接口审计 Raw 没有被复制或转化。Stage 18.2 没有创建 Clean、正式
Fact 表、Feature、Stage 19 或前端资产。

## 配置与执行入口

- `config/stage18_2.yml` 冻结两个上游 run、基准日 `2026-07-27`、23 只证券范围、
  Provider 矩阵、超时及最多三次尝试规则。
- CLI 命令为 `stage18-fundamental-collect`；日期和 Stage 18.1 run 必须显式传入
  或与配置一致。
- 运行前生成 175 行闭合 `fundamental_collection_plan.csv`，运行后每个
  `dataset_id` 必须恰有一个终态。

正式矩阵包含 A 股五类历史财务接口、A 股两项组合估值接口，以及港股财务指标和
三大报表的年度/报告期变体、港股估值接口。网络调用全部通过 adapter 执行，业务层
仅编排、分类、校验和生成报告；自动化测试使用 mock adapter，默认不访问网络。

## Raw 与时间治理

正式 Raw 使用以下 append-only 分区：

`data/raw/stage18/<category>/run_id=<run_id>/market=<market>/symbol=<symbol>/variant=<variant>/`

成功请求保存 `data.parquet` 和 `metadata.json`；空响应、调用失败或语义失败只允许保存
`metadata.json`。metadata 保留请求参数、尝试记录、Provider、AKShare 版本、时间、
Schema、报告/公告/更新日期字段、币种、身份结果和 SHA-256。

当前估值保存真实 `snapshot_time`，并固定
`eligible_for_as_of_date_analysis=false`；它不能代表基准日 `2026-07-27`。历史财务
Raw 不推断缺失公告日，也不在本阶段做 PIT 标准化。

## 运行中发现并修复的问题

首次正式 run `28bd7632-1fcd-4c68-987f-06b693815fe7` 保持为 append-only
`BLOCKED` 证据。其 48 个 FAIL 均来自 A 股三大报表的身份误判：Provider 返回
`SECUCODE=000100.SZ` 一类后缀代码，而规范化逻辑只处理了交易所前缀。

修复后身份规范化同时支持 `SH/SZ/BJ/HK` 前缀与 `.SH/.SZ/.BJ/.HK` 后缀；并增加
回归测试，保证语义失败时不写 `data.parquet`。没有修改或覆盖首次 run。

本项目仅用于数据能力研究与测试，不构成投资建议。
