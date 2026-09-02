# Stage 20 受限范围正式验收

## 1. 验收结论

验收 run：`d2f02a9d-901f-4e99-9f4f-20b6d17c77ef`。

- Stage 20 受限范围：`PASS`；
- Stage 20 完整范围：`NOT_AUTHORIZED`；
- Stage 20 事件范围：`BLOCKED`；
- Stage 19 管理状态：`CONDITIONALLY_CLOSED`；
- Stage 19 正式事件发布：`BLOCKED`；
- Stage 19 remediation：`OPEN`；
- Stage 21：`NOT_STARTED`；
- Netlify：`READY_NOT_DEPLOYED`。

该结论只接受合同授权的非事件范围，不代表 Stage 20 full PASS，也不解除 Stage 19 门禁。

## 2. 入口与能力验收

正式入口合同及其 conditional closure reference 均通过 schema、状态和证据一致性校验。
`restricted_entry_authorized=true`、`full_entry_authorized=false`、授权模式为
`RESTRICTED/NON_EVENT_ONLY`。缺失/非法/越权/引用冲突合同均在自动测试中 fail closed。

所有正式功能先通过 machine-readable capability gate；allowed 可访问，blocked 和未知能力拒绝。
事件能力不能查询、导出、筛选、排名或评分。

## 3. 数据与功能验收

- 16 只 A 股、7 只港股、ETHUSDT 的正式行情均可路由；
- A/H raw/qfq/hfq、日 K、周 K、七组 MA 通过；K/MA adjustment 一致；
- ETH 1m/3m/5m/15m/1h/1d 可用；A/H 股票分钟周期保持 `UNAVAILABLE`；
- volume、amount 及真实存在的 turnover 正常；缺失不变为 0；
- Stage 18 PIT feature 正常，170 AVAILABLE、106 项 Stage 18 全阶段 UNAVAILABLE 事实未改写；
  public A 股单元为 170 AVAILABLE、22 UNAVAILABLE，港股 84 UNAVAILABLE 以标的级状态传播；
- PE/PB/PS/市值因基准日不可用保持 `NULL/UNAVAILABLE`；
- 多证券比较使用归一化收益，跨币种名义金额不直接混合；
- 非事件筛选可用，事件与 candidate 字段不进入筛选；
- 五个页面及 loading/empty/unavailable/blocked 状态具备 smoke 覆盖。

## 4. Stage 19 隔离与安全验收

Stage 19 `formal_event_release` 仍为 `BLOCKED`，事件 `value=NULL`，没有显示“0 次涨停/跌停”。
public export candidate 泄漏为 0；production dist candidate 泄漏为 0。前端不存在用涨跌幅、固定
阈值、当前名称或 previous close 推断正式事件的逻辑。Stage 19 candidate 资产没有进入 public。

public build 不包含正式开发机路径、secret、cookie、API token、fixture 或内部 DuckDB 全量副本。

## 5. Build 与部署验收

真实 production build：

```text
cd web/stage20
pnpm run build
```

结果：Vite 5.4.14，47 modules transformed，build `PASS`。主入口 JS 159.86 kB（gzip 51.46 kB）；
Plotly 独立 lazy chunk 4,305.82 kB（gzip 1,332.65 kB）。完整历史数据不进入 JS bundle。

部署 artifact 已 READY；没有正式 Netlify 授权/连接，因此未实际部署、没有 URL，状态为
`READY_NOT_DEPLOYED`。

## 6. 自动测试与回归

- Stage 20 定向：`.venv\\Scripts\\python.exe -m pytest tests/test_stage20_restricted.py -q`
  → `26 passed in 4.27s`；
- Stage 0 冻结：`.venv\\Scripts\\python.exe tests/test_stage0_config.py`
  → `35/35 checks passed`；
- 全仓回归：`.venv\\Scripts\\python.exe -m pytest -q`
  → `1111 passed in 297.20s`，0 failed。

## 7. 上游不可变性

- Stage 0：冻结配置检查 PASS；
- Stage 17：正式 manifest 路由、正式文件 SHA-256 逐项验证，只读，未回写；
- Stage 18：downstream contract 指定的 DuckDB/feature SHA-256 验证，只读，未回写；
- Stage 19：管理状态、BLOCKED gate、0 official event、NULL 语义和 remediation OPEN 均保留；
- Stage 21：没有创建任何调度或自动刷新产物。

## 8. 机器证据

- `reports/stage20/d2f02a9d-901f-4e99-9f4f-20b6d17c77ef/entry_evidence.json`
- `reports/stage20/d2f02a9d-901f-4e99-9f4f-20b6d17c77ef/stage20_manifest.json`
- `reports/stage20/d2f02a9d-901f-4e99-9f4f-20b6d17c77ef/public_export_safety.json`
- `reports/stage20/d2f02a9d-901f-4e99-9f4f-20b6d17c77ef/build_deployment_evidence.json`
- `reports/stage20/d2f02a9d-901f-4e99-9f4f-20b6d17c77ef/stage20_acceptance.json`

Stage 20 受限范围完成并通过验收。是否进入 Stage 21 仍须遵循正式治理规则；本验收不启动
Stage 21，也不自动授予 Stage 20 完整或事件范围。
