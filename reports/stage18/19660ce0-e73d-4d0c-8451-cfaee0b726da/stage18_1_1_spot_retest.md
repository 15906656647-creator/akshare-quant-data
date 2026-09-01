# Stage 18.1.1 实时估值接口专项复测

- Run ID：`19660ce0-e73d-4d0c-8451-cfaee0b726da`
- 被复测的正式 Stage 18.1 run：`95c730f5-1bc0-429b-a370-96eeead06f62`
- AKShare：`1.18.80`
- 固定 HTTP timeout：`20s`
- 每个共享接口最多尝试：`3`
- 结论：`BLOCKED`

## 复测结果

|市场|共享接口|目标主机|attempt 结果|终态|
|---|---|---|---|---|
|A股|`stock_zh_a_spot_em`|`82.push2.eastmoney.com`|3/3 `connection_error`|`FAIL`|
|港股|`stock_hk_spot_em`|`72.push2.eastmoney.com`|3/3 `connection_error`|`FAIL`|

本窗口没有观察到 DNS、TLS、空表、字段漂移或业务逻辑错误。没有按 5 只样本重复请求；每个市场只复测其唯一共享全市场请求。详细 attempt 时长见同目录 JSON。

## 治理结论

- 未触发完整 Stage 18.1 新 run，既有正式 run 与 Raw 未覆盖。
- `stage18_2_authorized=false`，未启动 Stage 18.2。
- 本任务没有进入 Stage 18.1.2；下一项允许规划的任务是备用实时估值 Provider 能力审计。
- 后续新 Stage 18.1 run 的全部 `interface_audit` 数据均隔离为审计资产，不可直接用于 Stage 18.2 正式采集或分析。

## 测试证据

- Stage 18.1、Stage 0 与结构定向测试：`41 passed`。
- Stage 17 Tencent recovery 测试在短 Windows `--basetemp` 下：`9 passed`，此前两个失败已确认由默认临时路径长度触发。
- 完整 pytest 在短 Windows `--basetemp` 下：`1011 passed, 1 failed`。
- 唯一失败：`tests/test_stage8_manual_import.py::test_default_cli_fails_closed_without_real_dataset`，签名为期望返回码 1、实际返回码 0；与既有 Stage 8 测试债务一致。
- Stage 0 三个冻结文件哈希前后不变。

本报告仅用于数据能力研究与测试，不构成投资建议。
