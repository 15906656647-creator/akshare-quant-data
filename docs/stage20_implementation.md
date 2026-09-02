# Stage 20 受限范围实施记录

## 1. 阶段边界与入口合同

本次只实施 Stage 20 `RESTRICTED/NON_EVENT_ONLY`。入口证据为
`reports/stage19/conditional_closure/stage20_restricted_downstream_contract.json`，并与
`reports/stage19/conditional_closure/stage19_conditional_closure.json` 交叉校验。入口验证要求
Stage 19 管理状态 `CONDITIONALLY_CLOSED`、正式事件发布 `BLOCKED`、受限入口授权、完整入口
未授权、范围为 `NON_EVENT_ONLY`，任何缺失、解析失败、引用不一致或状态冲突均 fail closed。

`CapabilityGate` 将允许/禁止能力变成运行时一等概念。只有合同 `allowed_capabilities` 中且不在
`blocked_capabilities` 中的能力可进入 read/export 层；未知能力默认拒绝。事件查询、事件统计、
事件排名、事件筛选和 candidate-as-official 无法通过数据层能力门。

## 2. 数据架构与正式 Lineage

数据流为：

```text
Stage 19 restricted downstream contract
  ├─ Stage 17 PASS manifest → hash 校验 → OHLCV/周聚合/MA → 分片 JSON
  ├─ Stage 18 PASS contract → hash 校验 → PIT features → 分标的 JSON
  └─ Stage 19 formal availability → BLOCKED/NULL 占位
                                              ↓
                            React + Vite + Plotly 静态站
```

- 行情只由 Stage 17 正式 PASS run `4a5599fb-9e60-4013-9c0c-69fcc25a98b2` manifest 路由；
  不扫描 `data/raw` 选取看似存在的文件。
- 基本面只由 Stage 18 最终 PASS contract 路由，feature run 为
  `1bc599a7-17eb-4cc8-a543-8c0baaa7c3b8`；DuckDB 和 Parquet 均在读取前复算正式哈希。
- Stage 19 只传播管理、发布、availability 和 blocker，不读取 candidate 作为业务数据。
- public 层不包含 DuckDB、内部质量表、绝对路径或全量内部数据库。

## 3. Read model 与性能边界

`src/akshare_data_test/stage20.py` 生成 `web/stage20/public/data`：

- `metadata.json`：证券、市场、周期、复权、状态、lineage 和轻量筛选摘要；
- `series/{market}/{symbol}/{interval}/{adjustment}.json`：按市场、标的、周期和复权分片；
- `fundamentals/{market}/{symbol}.json`：按标的分片的 PIT feature 与状态；
- 首页只请求 `metadata.json`；选择标的后才请求相应序列；比较页只请求两个被选标的；
- Plotly 使用动态 import，production 首屏 JS 为 159.86 kB，4.31 MB 图表库独立按需加载；
- 169 个 public 数据文件共 174,601,815 bytes，大体积来自正式历史序列，不进入 JS bundle。

## 4. 行情、K 线和复权

- A 股：16 只，raw/qfq/hfq 全部可用；qfq 汇总 64,676 行，整体日期范围
  1996-10-30 至 2026-08-24（各标的从自身正式上市覆盖起点开始）。
- 港股：7 只，raw/qfq/hfq 全部可用；qfq 汇总 11,662 行，整体日期范围
  2017-05-26 至 2026-08-24。
- ETHUSDT：OKX `ETH-USDT`，1m/3m/5m/15m/1h/1d 均为正式 PASS；1d 为 3,148 行，
  日期范围 2018-01-11 至 2026-08-24。
- 日 K 直接使用正式日线。周 K 按 `W-FRI` 聚合交易序列：open=first、high=max、low=min、
  close=last、volume/amount/turnover=sum，不补自然日空行。
- 同一 payload 的 K 线与 MA 由同一 adjustment 数据计算；页面明确显示 adjustment。
- A/H 股票分钟探针 0/10，不属于正式出口，因此 1m/3m/5m 均显示 `UNAVAILABLE`；不进行临时
  resample。ETH 的六个正式周期按 manifest 原样提供。

## 5. MA 与非事件量价指标

统一实现 MA3、MA5、MA7、MA10、MA13、MA20、MA21。每个标的、周期、复权分别排序计算，
窗口不足保持 `NULL`，不跨标的、不以 0 填充。行情按真实字段提供 OHLC、volume、amount；
A/H 正式数据存在 turnover，ETH 不制造股票换手率。

## 6. 基本面与时间语义

Stage 18 共 12 个正式 feature：revenue、net_profit、roe、roa、net_margin、debt_to_asset、
revenue_yoy、net_profit_yoy、operating_cash_flow、ocf_to_net_profit、total_assets、total_equity。
A 股 public feature 单元 192 个，其中 `AVAILABLE` 170、`UNAVAILABLE` 22。输出保留
report_period、announcement_date、effective_date、source_run_ids；构建时拒绝公告日期晚于
2026-07-27 的记录，避免 look-ahead。

Stage 18 已明确当前估值 snapshot 不可用于基准日历史分析，故 PE、PB、PS、总市值、流通市值
全部保持 `value=NULL / availability=UNAVAILABLE`，不制造数值。港股按 Stage 18 结论传播
`UNAVAILABLE`；ETH 股票基本面为 `NOT_APPLICABLE`。

## 7. 页面与交互

- 总览：基准日、更新时间、A/H/ETH 标的数、基本面、分钟状态及 Stage 19 BLOCKED 卡片；
- 证券详情：市场/标的/周期/复权选择，K 线、Volume、MA toggle、基本面和 lineage；
- 比较：两个正式标的的归一化区间收益，保留 CNY/HKD/USDT 口径，不直接混合名义金额；
- 非事件筛选：market、symbol、price、volume、turnover；amount 作为正式结果列展示；不可用估值控件禁用；
- 数据状态：区分 `AVAILABLE`、`UNAVAILABLE`、`BLOCKED`、`NOT_APPLICABLE` 和 `NULL`。

切换 symbol 时同时重置 interval/adjustment，异步请求使用生命周期取消标志，避免前一个标的
残留；加载失败和空状态均有明确提示。

## 8. 事件隔离与 public 安全

事件模块只显示 `formal_event_release=BLOCKED`、`availability_status=BLOCKED`、`value=NULL`
及中文 blocker。前端没有固定 5%/10%/20%、`pct_change`、previous_close 或名称推断逻辑。

`scan_public_assets` 和验收 finalizer 同时扫描 public 与 dist，检查 candidate 标识、开发机路径、
credential 线索和内部数据库。最终 candidate data leak count 为 0；public/dist 均无 DuckDB、fixture、
secret 或开发机路径。

## 9. Build、部署与 Stage 21 边界

前端采用 React 18 + Vite 5 + Plotly，样式为项目内轻量 CSS；没有并存第二套展示技术栈。
`netlify.toml` 提供可重复 build、publish 路径和 SPA refresh redirect。真实 build 命令为：

```text
cd web/stage20
pnpm run build
```

build 已 PASS。当前环境没有正式 Netlify 授权或连接，故部署状态准确记录为
`READY_NOT_DEPLOYED`，没有 URL。

本阶段未创建 scheduler、cron、自动抓数、自动增量 ETL、自动 public refresh、rebuild hook 或
GitHub Actions。Stage 21 保持 `NOT_STARTED`。
