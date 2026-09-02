# Stage 20 受限范围部署收口记录

## 1. 收口边界

本任务只验证并尝试完成 Stage 20 `RESTRICTED/NON_EVENT_ONLY` 的 Netlify 部署闭环，
不启动 Stage 21，不改变 Stage 20 full/event scope，也不改变 Stage 19 Gate 或 remediation。

部署入口复核通过：Stage 20 restricted scope=`PASS`、production build=`PASS`、full scope=
`NOT_AUTHORIZED`、event scope=`BLOCKED`、Stage 21=`NOT_STARTED`。

## 2. Production artifact 与配置复核

正式 artifact 为 `web/stage20/dist`，由已验收 public 数据重新执行：

```text
cd web/stage20
pnpm run build
```

Vite 5.4.14 共转换 47 个模块，build `PASS`。Netlify 配置检查通过：base 为
`web/stage20`、command 为 `pnpm run build`、publish 为 `dist`，SPA 200 redirect 存在；
Vite base 为 `/`，production sourcemap 关闭。

- artifact hash：`4cca7ec81e90e34c7d05b25b583d29ab91a5d9956c4e154881444e0c63da1546`
- index SHA-256：`9be93b7e014000d7dc18993d0037cfed7103b84b3970e5a6fefd39905d2434e4`
- dist 文件：173
- public 数据文件：169

## 3. Netlify 授权与真实部署结果

当前执行环境检查结果：

- Netlify CLI：不存在；
- `NETLIFY_*` 授权环境变量：不存在；
- `.netlify/state.json` 站点绑定：不存在；
- Netlify connector：不可用。

OpenAI Sites 属于不同部署平台，不能替代或冒充 Netlify。由于没有正式身份和目标站点，
未执行交互登录或创建未知站点，也没有伪造 deployment id、site id 或 URL。

因此：

- deployment closure status：`BLOCKED`
- deployment status：`READY_NOT_DEPLOYED`
- production URL：`NULL`
- deployment id/site id/deployed_at：`NULL`

## 4. Artifact 安全与静态 Smoke

- candidate event leak：0；
- secret scan：`PASS`；
- local absolute path scan：`PASS`；
- forbidden DuckDB/SQLite/source map/fixture/debug：0；
- source map count：0。

本地静态 smoke 为 `PASS`：index 与其 JS/CSS 引用存在，A 股、港股、ETHUSDT 代表分片可读，
Stage 19 event 保持 `BLOCKED/NULL`，不存在“0 次涨停/跌停”替代不可用，港股基本面正确显示
`UNAVAILABLE`。由于没有 production URL，线上 smoke 为 `NOT_RUN_NO_PRODUCTION_URL`，
visual QA 为 `UNAVAILABLE_NO_PRODUCTION_URL`。

## 5. 测试与不可变性

- 部署收口与 Stage 20 定向：`37 passed in 7.27s`；
- Stage 0 冻结检查：`35/35 PASS`；
- 全仓回归：`1122 passed in 437.19s`，0 failed。

Stage 0/17/18/19 正式资产和治理状态均未修改。Stage 19 formal event release 仍为
`BLOCKED`，remediation 仍为 `OPEN`；Stage 21 仍为 `NOT_STARTED`。

## 6. 正式机器证据

`reports/stage20/d2f02a9d-901f-4e99-9f4f-20b6d17c77ef/deployment_closure_evidence.json`

本次部署收口不能宣布 PASS。待提供正式 Netlify 授权以及明确目标站点或获准创建站点后，
应在独立 Stage 20 部署收口任务中执行真实 production deploy，并对真实 URL 进行线上 smoke。
