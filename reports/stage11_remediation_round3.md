# Stage 11 第三次最小修复报告

## 1. 实施状态

`READY_FOR_FOURTH_REAUDIT`。这是修复方自测状态，不是独立验收 PASS；Stage 12 尚未开始。

## 2. 第三轮复验失败摘要

第三轮独立复验的唯一剩余失败为 `STATIC-06 / M13`：在 run-specific Raw 目录加入未被 Manifest 声明的 `orphan.json` 后，真实 `validate-crypto --validate-only` 仍返回 `READY`、退出码 0。其余原 28 项故障、Manifest 既有场景、正常 960 行链路、Stage 10 隔离和完整回归均已通过。

## 3. 根因与原生产调用链

生产调用链为：

```text
validate-crypto --validate-only
  → validate_stage11_inputs
  → validate_raw_evidence
  → blocking_reasons 汇总
  → CLI status/exit code
```

原验证器只遍历 `manifest.evidence_files` 已列出的条目并检查 role、路径、size、SHA-256 和物理文件，没有递归枚举 Raw 根目录，也没有比较实际文件集合与 Manifest 声明集合。因此未声明文件没有产生 blocker，空 blocker 被顶层解释为 READY。

## 4. 最小修复范围

仅修改：

- `src/akshare_data_test/crypto_evidence.py`
- 新增 `tests/test_stage11_manifest_closed_world.py`

未修改指标、身份模型、Stage 10 财务逻辑、数据库结构、Stage 0 文件、原 Raw、原 DuckDB或既有验收/修复报告。

## 5. Raw 封闭证据包规则

验证器现在强制：

```text
实际普通文件集合
=
Manifest 声明文件集合 + manifest.json
```

`manifest.json` 不声明自身哈希，避免自引用。当前 Manifest role 契约仍只允许 `request`、`response`、`metadata`；即使附加文件被声明，未知 role 也会明确失败，不会被静默接受。

## 6. 递归枚举与路径规范化

从 run-specific Raw 根目录开始，通过不跟随链接的目录扫描递归枚举：

- 只接受普通文件；
- 路径转换为相对 Raw 根目录的 `/` 形式；
- 按 Windows 大小写不敏感语义比较；
- 规范化 `.`，继续拒绝绝对路径、盘符、`..` 和逃逸；
- 拒绝 symlink、junction/reparse point 和其他非普通文件；
- 保留原始列表，分别检查 Manifest 重复项和实际路径规范化后的重复项。

没有增加 `.tmp`、`.bak`、隐藏文件或未知 JSON 的忽略规则。

## 7. 未声明文件检测与结构化结果

验证器建立 `listed_files`、`actual_files` 和 `expected_files`，分别计算未声明与缺失集合。多个未声明路径稳定排序并全部输出。结构化结果示例：

```json
{
  "check_name": "manifest_closed_world",
  "status": "FAIL",
  "error_code": "manifest_unlisted_file",
  "unlisted_files": ["orphan.json"],
  "missing_files": []
}
```

同时将 `manifest_unlisted_file: <relative path>` 加入 `blocking_reasons`。

## 8. CLI fail-closed 传播

根目录和嵌套 orphan 均通过真实 `validate-crypto --validate-only` 验证：顶层 `BLOCKED`、exit 2、输出具体相对路径，不包含 READY。Raw、CSV、JSON、DuckDB 的 SHA-256、大小和 mtime 前后不变；测试中的 socket 连接计数为 0。实现不会删除额外文件、修改 Manifest、补项、去重或重建产物。

## 9. 新增测试

新增 12 项测试，覆盖：根目录 orphan、嵌套 orphan、`.bak`、`.tmp`、隐藏文件、空文件、二进制文件、多文件稳定排序、正常目录、已声明但 role 不受支持的附加文件，以及两个真实 CLI 只读/离线传播场景。

最终代码形态下，closed-world 与原 Manifest 合并专项为 34/34；Stage 11 为 98/98。

## 10. 故障矩阵

- 原 28 项故障：**28/28 阻断**。
- 原 Manifest 21 项：**21/21 阻断**。
- 新增 closed-world 生产场景：**9/9 阻断**。

新增矩阵覆盖根目录、子目录、备份、临时、隐藏、空、二进制、多个未声明文件，以及声明附加文件但使用不受支持 role。详见 `reports/stage11_remediation_round3_closed_world_matrix.csv`。

## 11. 正常 960 行与幂等验证

正常临时证据经生产 `validate-only` 返回 `READY`、exit 0、960 行，执行前后全产物快照不变。CSV/JSON/DuckDB 对账、身份、时间、OHLCV 和指标门禁保持通过。同一 run_id 再执行为 PASS，Raw 与价格 CSV/JSON 哈希稳定，数据库逻辑计数保持幂等。

## 12. 测试与回归

| 范围 | passed | failed | skipped | xfailed | warnings | exit code |
|---|---:|---:|---:|---:|---:|---:|
| closed-world 专项 | 12 | 0 | 0 | 0 | 0 | 0 |
| 原 Manifest 专项 | 22 | 0 | 0 | 0 | 0 | 0 |
| 既有 remediation | 53 | 0 | 0 | 0 | 0 | 0 |
| Stage 11 | 98 | 0 | 0 | 0 | 0 | 0 |
| Stage 10 | 45 | 0 | 0 | 0 | 0 | 0 |
| Stage 0 | 35 | 0 | 0 | 0 | 0 | 0 |
| 完整回归 | 542 | 0 | 0 | 0 | 0 | 0 |

完整回归最终运行：`542 passed in 140.97s`。

## 13. Git、哈希与保护状态

HEAD 保持 `d6b2b6a447f55c8f59f17f31ff1fd326dfc095c3`，staged 文件为 0，未 commit、未 push。Stage 0 三文件、原 AKShare Raw、原 Stage 11 DuckDB及第三轮独立复验五个交付物哈希均未改变。`git diff --check` 通过；既有 LF→CRLF 提示仅作为观察项，未转换换行符。

## 14. 第四轮独立复验重点

第四轮应独立验证：

1. 真实 CLI 对根目录、嵌套、隐藏、空、二进制、`.bak`、`.tmp` 和多个未声明文件全部 fail-closed；
2. 错误码和所有相对路径稳定输出；
3. symlink/junction/reparse point 无法绕过闭集；
4. 原 Manifest 21 项和原 28 项保持全阻断；
5. 正常 960 行仍 READY、validate-only 离线只读；
6. 同 run_id 幂等、Stage 10 财务读取为 0；
7. 冻结文件、原 Raw、原 DuckDB和第三轮独立验收报告未改变。

第四轮独立复验通过前，不得进入 Stage 12。
