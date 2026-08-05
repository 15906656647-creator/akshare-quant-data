# Stage8 数据源探测修复报告

> 报告日期：2026-08-05
> 分支：`feature/stage15-s15-14-fix`
> 探测 run_id：`9e0f1a2b-3c4d-4e5f-9a0b-1c2d3e4f5a6b`
> AKShare 版本：`1.18.80`

## 1. JSON 无效根因

旧 `probe_manifest.json` 由 `Path.write_text(json.dumps(...), encoding="utf-8")`
直接写出，没有写出后的自检，也没有处理 Windows PowerShell 默认读取编码问题。
当 Windows PowerShell 5.1 用 `Get-Content -Raw`（默认 ANSI/GBK）读取无 BOM 的
UTF-8 JSON 时，中文多字节尾字节可能和后面的 `"` 合并成一个 GBK 双字节序列，
导致引号被吞掉、字符串未终止，`ConvertFrom-Json` 报“数组无效/未终止字符串”。
另外旧 manifest 只有扁平字段，缺少列名、映射、日期覆盖和失败记录等结构化信息。

## 2. 编码乱码根因

UTF-8 中文（如 `证券简称`）被按 GBK 解码显示为 `璇佸埜绠€绉?`；这是读取端
编码假设错误，不是文件内容错误。修复措施：

- JSON、Markdown 使用 UTF-8 BOM 写入，PowerShell 5.1 的 `Get-Content` 可自动识别；
- CSV 使用 `utf-8-sig`；
- 写入临时文件后原子替换，随即重新读取并解析自检；
- `json.dumps(..., ensure_ascii=False)` 生成，字符串不拼接；
- 所有 pandas/numpy/日期/空值先规范化为 JSON 兼容类型。

## 3. 修改文件

- `src/akshare_data_test/adapters/status_probe.py`：重写安全 JSON 写入、原子替换、
  UTF-8 BOM、列映射、日期覆盖、重试与失败记录、保守分级、五类产物输出。
- `src/akshare_data_test/cli.py`：探测命令输出路径与 JSON 自检（`utf-8-sig`）。
- `tests/test_stage15_s14_fix.py`：新增编码/JSON/列映射/分级/失败闭环测试。
- `docs/stage8_source_probe_fix_report.md`（本报告，新增）。
- `docs/stage8_authoritative_sources.md`、`docs/stage15_s14_fix_report.md`：增加修订说明。

## 4. 新增测试

- 中文列名、Windows 中文路径、引号/换行/反斜杠列名；
- 空 DataFrame 与未知列 `UNMAPPED`；
- 网络失败错误文本与 `interface_failure` 分级；
- UTF-8 往返（CSV `utf-8-sig`、JSON/Markdown BOM）；
- 生成文件可被 `json.loads()` 重新解析；
- 非法 manifest 不得发布且 CLI 返回非零；
- 保守分级：当前成功接口最高 B 级，无 A 级。

## 5. 定向测试结果

```text
61 passed in 8.53s
```

覆盖 `tests/test_stage15_s14_fix.py` 与 `tests/test_stage1_structure.py`。

## 6. 全量测试结果

```text
891 passed in 384.17s (0:06:24)
```

## 7. 新 run_id

`9e0f1a2b-3c4d-4e5f-9a0b-1c2d3e4f5a6b`

## 8. 全部输出路径

```text
reports/stage15_s14_fix/source_probe/9e0f1a2b-3c4d-4e5f-9a0b-1c2d3e4f5a6b/
  probe_manifest.json
  source_grade_summary.json
  column_mapping.json
  source_feasibility.csv
  source_feasibility.md
  <interface>.csv （原始证据）
```

## 9. JSON 解析验证

以下两条 PowerShell 命令均已实际执行并成功：

```powershell
Get-Content <probe_manifest.json> -Raw | ConvertFrom-Json
Get-Content <source_grade_summary.json> -Raw | ConvertFrom-Json
```

结果：`probes=9`、`summary=authoritative_sources_insufficient`、
`authoritative_rule_source_ready=False`、`authoritative_status_source_ready=False`。
`column_mapping.json` 同样可解析（`interfaces=9`）。Python `json.loads()` 对三个
JSON 文件全部通过。

## 10. 各来源等级

| 来源 | 状态 | 行数 | 等级 | 阻断原因 |
| --- | --- | ---: | --- | --- |
| `stock_zh_a_st_em` | failed | 0 | C | interface_failure:connection_error |
| `stock_individual_info_em` | failed | 0 | C | interface_failure:connection_error |
| `stock_info_change_name` | success | 19 | C | no_effective_dates |
| `stock_info_sz_change_name_full` | success | 1756 | B | auxiliary_only |
| `stock_info_sz_change_name_short` | success | 7454 | B | auxiliary_only |
| `stock_info_sh_name_code` | success | 1698 | B | auxiliary_only |
| `stock_info_sz_name_code` | success | 2894 | B | auxiliary_only |
| `cninfo_risk_warning` | success | 0 | C | empty_result_cannot_prove_no_data |
| `cninfo_special_treatment` | success | 0 | C | empty_result_cannot_prove_no_data |

当前没有任何来源达到 A 级（官方正式状态历史 + 完整有效日期 + 可独立证明覆盖）。

## 11. A 级规则来源是否就绪

**否**。`authoritative_rule_source_ready = false`。

## 12. A 级状态来源是否就绪

**否**。`authoritative_status_source_ready = false`。

## 13. 是否允许执行 stage8-rules-build

**不允许**。`can_continue_rules_build = false`。

## 14. 是否允许执行 stage8-status-build

**不允许**。`can_continue_status_build = false`。

## 15. 是否仍需 PowerShell 操作

否。探测修复已由代码完成；用户可按第 9 节命令复验 JSON 可解析性。

## 16. 精确的下一步命令

在新增并验证正式状态历史来源、来源注册到 `SOURCE_KINDS`/`KNOWN_COLUMN_MAPPINGS`
并通过探测自检之前，不要执行规则/状态构建、Stage8 重建或 Stage15 重跑：

```powershell
# 复验本次产物
Get-Content reports/stage15_s14_fix/source_probe/9e0f1a2b-3c4d-4e5f-9a0b-1c2d3e4f5a6b/probe_manifest.json -Raw | ConvertFrom-Json
Get-Content reports/stage15_s14_fix/source_probe/9e0f1a2b-3c4d-4e5f-9a0b-1c2d3e4f5a6b/source_grade_summary.json -Raw | ConvertFrom-Json
```

阻塞项：`no_authoritative_rule_source`、`no_authoritative_status_history_source`、
`interface_failure:connection_error`、`empty_result_cannot_prove_no_data`、
`no_effective_dates`。

## 结论

> 当前只能完成数据源可行性审计，不能构建正式Stage8数据，S15-14继续BLOCKED，阶段15尚不能完全通过。
