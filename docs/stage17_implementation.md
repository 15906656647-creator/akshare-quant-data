# Stage 17 多市场原始数据采集实施记录

## 阶段边界

- 业务基准日：`2026-08-24`。
- 入口依据：Stage 15治理状态为 `CONDITIONALLY_CLOSED`，且该决定只直接授权Stage 17。
- Stage 16仅作为既有离线覆盖基线，本阶段未重跑Stage 16。
- 本阶段只扩展A股、港股和OKX `ETH-USDT`现货行情Raw资产。
- 未启动Stage 18，未采集财务报表，未生成或修改Stage 19涨跌停事件。

## 固化范围

- A股：原任务16只证券。
- 港股：`02180.HK、08365.HK、08462.HK、02076.HK、06100.HK、06919.HK、09669.HK`。
- A/H股日线：未复权、前复权、后复权，共69个正式数据集。
- ETHUSDT：仅使用OKX `ETH-USDT`现货，周期为`1m、3m、5m、15m、1h、1d`。
- A/H股分钟验证：A股`002067、300274、600763`，港股`02180.HK、08365.HK`；直接验证`1m/5m`。
- A/H股`3m`只允许从`1m`在报告层演示聚合，不保存为Raw，不宣称上游直接支持。

唯一配置来源为`config/stage17.yml`。加载器拒绝未知字段、日期漂移、标的漂移、交易所替换和周期替换。

## 实施结构

- `collect-stage17`提供`--validate-only`、`--dry-run`和正式采集模式。
- 网络调用集中在`src/akshare_data_test/adapters/`；业务编排不直接调用AKShare或HTTP。
- A股上市日期证据使用AKShare巨潮公司概况接口；港股保存证券档案，并严格记录档案不能提供上市日期的情况。
- OKX适配器执行完整分页、最多三次指数退避、请求间限速及`confirm=1`过滤，不静默切换提供商。
- Raw写入`data/raw/stage17/`，按`dataset/run_id/market/symbol/adjust或interval`分区。
- 每个成功数据集包含`data.parquet`和`metadata.json`；空结果和失败只进入清单，不伪造成功Raw。
- 每次正式运行生成封闭世界Raw清单、逐文件SHA-256、日线覆盖、加密覆盖、分钟可行性和质量报告。

## 严格出口规则

- 69个A/H股日线数据集和6个ETH周期必须全部成功且通过质量检查。
- 上市日期必须有来源证据；最早行情明显晚于上市日时记录`provider_history_shorter_than_listing`。
- 上市日期不可获得时记录`listing_date_unavailable`，不得宣称上市以来完整覆盖。
- 正式数据集失败或质量失败时状态为`BLOCKED`。
- 正式数据集通过但存在严格上市覆盖不可用项时状态为`PASS_WITH_UNAVAILABLE_ITEMS`。
- 只有`PASS`才授权Stage 18；其他结果必须停在Stage 17，本任务不建立Stage 17条件封板。

## 命令

```powershell
python run_pipeline.py collect-stage17 --as-of-date 2026-08-24 --validate-only
python run_pipeline.py collect-stage17 --as-of-date 2026-08-24 --dry-run
python run_pipeline.py collect-stage17 --as-of-date 2026-08-24 --run-id <UUID>
```

验证和dry-run均不访问网络、不创建Raw或报告目录。正式运行的实际结果和出口状态见对应
`reports/stage17/<run_id>/stage17_run.json`及`docs/stage17_acceptance.md`。
## 重新审计修复（2026-08-24）

- `config/stage17.yml`升级为Schema `1.1.0`、模型`stage17_multimarket_raw_v2`，固定
  A股东方财富主源/新浪备用源和港股东方财富主源/新浪备用审计源；禁止静默换源。
- A股新浪代码由冻结交易所映射为`sh/sz + 六位代码`；支持的主接口显式接收20秒超时，
  其余AKShare调用由适配器临时注入默认HTTP超时并在调用结束后恢复。
- AKShare连接类失败采用最多3次、有8秒上限的指数退避；参数和确定性数据错误不重试。
- 备用源仅在配置允许的失败类型触发。港股主源OHLC异常也会触发备用候选，但候选只有
  同时通过OHLC、日期、上市覆盖等严格检查才可进入正式69项集合。
- 每个成功来源写入`source=<eastmoney|sina>`分区。未选候选、失败尝试、触发原因、接口、
  尝试次数和选择理由均进入manifest；不修改或覆盖上游Raw值。
- 运行结果新增`daily_nonempty_count`、`daily_quality_pass_count`和
  `daily_expected_count`；`daily_success`仅作为非空Raw数的兼容别名。
- 重新审计期间的中断批次和最新正式批次均使用独立`run_id`；未复用前三批Raw，未启动
  Stage 18或创建任何Stage 18/19产物。
## Stage 17.7 Provider Registry与正式重跑

- `config/stage17.yml`升级为Schema `1.2.0`、模型`stage17_multimarket_raw_v3_registry`，逐标的、逐复权固定港股Provider顺序。
- 新增`HkProviderRegistry`，只有候选同时通过响应、身份、OHLC、日期、上市覆盖和复权语义门禁后才设置`selected_provider`；失败候选、接口、尝试次数和拒绝原因完整进入Manifest。
- 港股普通路径优先腾讯，再尝试东方财富和新浪。`08462.HK qfq/hfq`在标准腾讯边界失败后走腾讯兼容直连；`09669.HK qfq/hfq`直接走腾讯兼容直连。
- 腾讯兼容适配器按上市日至基准日生成非重叠两年请求块，优先读取`qfqday/hfqday`，仅在调整端点实际返回`day`时显式回退；保留请求参数、响应字段、HTTP状态、重试次数和SHA-256，不修改OHLC。
- 分钟可行性探针增加外层硬超时，并在首次`timeout/connection_error`后对剩余项生成明确的skipped失败记录，防止非阻塞探针重复拖住正式批次；Stage 17日线和ETH门禁未改变。
- 正式完整批次`4a5599fb-9e60-4013-9c0c-69fcc25a98b2`独立重采69项日线、23份证券档案和6个ETH周期，最终`69/69 + 6/6 PASS`，Raw闭集及SHA-256校验通过。
- 重新执行期间产生的中断或`BLOCKED`批次均按Raw不可变原则保留，未复用、未拼接、未覆盖。
- Stage 17已达到`PASS`并按阶段衔接规则授权Stage 18入口；本次任务停在Stage 17，没有开始Stage 18。
