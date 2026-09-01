# Stage 18.1.2 备用实时估值 Provider / 能力审计验收

## 结论

Stage 18.1.2 状态为 `PASS`。正式完整 run 为
`9c869e51-ae27-4b7e-895c-79a2c978258c`。

- A 股估值能力：`PASS`，选定同一 Provider 下的组合能力
  `EastmoneyDataCenter[valuation_comparison+scale_comparison]`。
- 港股估值能力：`PASS`，选定
  `stock_hk_financial_indicator_em`。
- 原 `stock_zh_a_spot_em` 与 `stock_hk_spot_em` 继续保持
  `FAIL / connection_error`，未降级为 `UNAVAILABLE`，也未在本阶段重试。
- 所有审计资产均为 `audit_only=true`、
  `eligible_for_stage18_2_ingestion=false`。
- 本次没有重跑完整 Stage 18.1，未授权或启动 Stage 18.2。

## 证据完整性

- manifest 中登记 59 个 Raw 文件，磁盘实际存在 59 个；大小与 SHA-256
  全部复算一致。
- 31 份 metadata 的 `asset_role=valuation_provider_audit`，且审计隔离标记
  全部一致。
- Raw 目录无临时文件，Stage 0 三个冻结文件在 run 前后及最终复核时哈希
  均保持不变。
- 中断 run `eb315f57-637f-4e3a-94a2-6936e4e0c16d` 的 32 个 append-only
  Raw 文件已保留，并有独立 `INTERRUPTED` 记录；它不提供正式能力结论。

## 测试门禁

- Python 编译校验：通过。
- Stage 18.1.2、Stage 18.1、Stage 0 与项目结构定向测试：`44 passed`。
- 完整离线测试：`1014 passed, 1 failed`。
- 唯一失败为既有 Stage 8 测试债务：
  `tests/test_stage8_manual_import.py::test_default_cli_fails_closed_without_real_dataset`；
  错误签名仍为“期望返回码 1，实际返回码 0”。无新增失败。
- 完整测试使用短 `basetemp`，未再出现 Stage 17 Windows 临时路径长度失败。

## 阶段边界

Stage 18.1.2 的能力解阻已经完成，但 Stage 18.1 的正式状态不会被本子阶段
报告就地改写。下一项允许工作是使用新 `run_id` 完整重跑 Stage 18.1，合并
既有历史财务能力与本次选定的估值 Provider，并重新执行 Stage 18.1 出口门禁。
只有该完整 run 给出 `PASS` 和 `stage18_2_authorized=true` 后，才可进入
Stage 18.2。

本项目仅用于数据能力研究与测试，不构成投资建议。
