# Stage 11 第二轮修复报告

## 实施状态

`READY_FOR_THIRD_REAUDIT`。这是实施方自测状态，不是第三轮独立验收 PASS。

## 第二轮验收失败与根因

第二轮唯一剩余失败为 `STATIC-06 / R08`：manifest 遗漏必需文件或重复条目时，生产 `validate-only` 仍返回 READY。调用链为 `validate-crypto --validate-only` → `validate_stage11_inputs` → `validate_raw_evidence`。原验证器只遍历已列出条目并核对哈希，没有统计必需 role 的 multiplicity，也没有检查规范化路径唯一性；现有测试只追加不存在文件，因此没有覆盖遗漏和重复。

## 最小修复

仅修改 `src/akshare_data_test/crypto_evidence.py` 并新增 `tests/test_stage11_manifest_contract.py`。写入端为 request、response、metadata 各生成一次 `role/name/sha256/size_bytes`。验证端在任何集合化前使用原始条目计数，要求三个必需 role 各一次；路径统一斜杠、移除 `.`、按 Windows 大小写不敏感语义比较，拒绝绝对路径、驱动器路径、`..`、逃逸、重复路径和重复 role。每个条目必须对应 Raw 根目录内非符号链接的非空普通文件，size 与 SHA-256 均须一致；schema 错误均形成结构化 blocker。

CLI 沿既有 `blocking_reasons` 链传播上述错误，顶层返回 BLOCKED 和非零退出码，不联网、不去重、不补项、不重建或覆盖产物。

## 新增测试与故障矩阵

专项覆盖 19 个底层故障、1 个正常契约及 2 个真实 CLI 传播场景，共 **21/21** 个故障执行被阻断；正常 manifest 继续 READY。详细结果见 `reports/stage11_remediation_round2_manifest_matrix.csv`。原 28 项故障矩阵通过既有 remediation 回归复验为 **28/28**。

## 正常 960 行链路

使用已保存的 OKX 960 行价格产物在临时目录生成新契约 Raw，执行 build 两次和真实 CLI validate-only。结果 `READY`、exit 0；raw/clean/indicator 均 960 行，profile 1 行；同 run_id 稳定哈希不变，validate-only 前后所有临时 Raw/CSV/JSON/DuckDB 的哈希与 mtime 不变。指标公式与 960 行数据语义未修改，仅验证统计特征，未形成投资结论。

## 测试结果

| 范围 | passed | exit code | summary |
|---|---:|---:|---|
| manifest_contract | 22 | 0 | 22 passed in 6.12s |
| stage11_remediation | 53 | 0 | 53 passed in 41.74s |
| stage11 | 86 | 0 | 86 passed in 58.33s |
| stage10 | 45 | 0 | 45 passed in 18.86s |
| full | 530 | 0 | 530 passed in 195.51s (0:03:15) |
| stage0 | 35 | 0 | ALL CHECKS PASSED |

## Git、冻结与保护

Stage0 三个冻结文件、原 DuckDB 和原 Raw 哈希均未改变；第二轮独立验收目录未覆盖。工作区保持未 staged、未 commit、未 push。本轮没有修改指标公式、身份模型、Stage10 财务逻辑或既有正确产物。

## 第三轮独立复验重点

独立复验应重新注入：三个必需 role 分别遗漏、同路径重复、同 role 不同路径、大小写/分隔符/`.` 等价路径、绝对路径和 `..`、双 response 主体、size/hash/schema 异常；同时通过真实 CLI 核对 BLOCKED、非零退出码、明确错误代码及全产物只读性，并复验正常 960 行 READY 与同 run_id 幂等。
