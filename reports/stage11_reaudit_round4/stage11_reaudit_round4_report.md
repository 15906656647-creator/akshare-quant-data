# Stage 11 第四轮独立复验报告

## 一、最终结论

**通过**。首轮 26 个失败项均取得最终关闭证据；原始故障矩阵 28/28、Manifest 故障矩阵 21/21、封闭世界故障矩阵 9/9 均通过真实生产入口阻断。正常 960 行数据返回就绪，完整测试 542/542 通过。

本轮只执行独立验收，没有修改实现代码、配置、数据库结构、原始数据或既有验收与修复报告。本项目仅用于研究和测试，本报告不构成投资建议。

## 二、历次失败关闭映射

| 历次失败项 | 修复位置 | 第四轮独立验证方法 | 实际结果 |
|---|---|---|---|
| DATA-03 | assets.py、crypto_market.py、crypto_repository.py、stage11_schema.sql | 身份注入、格式对账、960 行身份唯一值检查 | 通过 |
| FAULT-A4 | quality/crypto_checks.py | 顺序与时间质量生产入口复跑 | 通过 |
| FAULT-A5 | quality/crypto_checks.py、stage11_build.py | 范围外与缺 K 生产入口复跑 | 通过 |
| FAULT-B1 | 身份模型与 Repository 防线 | ETH-USD 注入 | 通过 |
| FAULT-B2 | 身份模型与 Repository 防线 | ETH-USDT-SWAP 注入 | 通过 |
| FAULT-B3 | 身份模型与 Repository 防线 | 错误数据提供方注入 | 通过 |
| FAULT-B4 | 身份模型与 Repository 防线 | 数据来源注入 | 通过 |
| FAULT-B5 | 身份模型与 Repository 防线 | 缺少原始身份字段 | 通过 |
| FAULT-B6 | 身份模型与 Repository 防线 | 错误交易所注入 | 通过 |
| FAULT-C5 | quality/crypto_checks.py | 非有限或非数值字段注入 | 通过 |
| FAULT-D1 | stage11_build.py、cli.py、crypto_repository.py | CSV 删除行 | 通过 |
| FAULT-D2 | 同上 | CSV/JSON 数值篡改 | 通过 |
| FAULT-D3 | 同上 | DuckDB 数据来源篡改 | 通过 |
| FAULT-D4 | 同上 | 时间戳篡改 | 通过 |
| FAULT-E1 | crypto_evidence.py、stage11_build.py、cli.py | Raw 目录缺失 | 通过 |
| FAULT-E2 | 同上 | Raw 响应缺失 | 通过 |
| FAULT-E3 | 同上 | Raw 响应为空 | 通过 |
| FAULT-E4 | 同上 | Raw 行数不一致 | 通过 |
| FAULT-E5 | 同上 | Schema 与内容哈希不一致 | 通过 |
| FAULT-F3 | fundamental_analysis.py、stage10_build.py、cli.py | 加密货币生产入口与财务读取隔离 | 通过，读取次数 0 |
| RAW-02 | crypto_evidence.py | Raw 元数据与证据契约复验 | 通过 |
| STATIC-02 | 身份模型与 Repository 防线 | 静态审查与身份矩阵 | 通过 |
| STATIC-03 | 身份字段、Repository 与数据库结构 | 八个身份维度全量对账 | 通过 |
| STATIC-05 | validate-only 三格式门禁 | CSV、JSON、DuckDB 篡改 | 通过 |
| STATIC-06 | crypto_evidence.py、Manifest 契约与封闭世界修复 | 原 Manifest 21 项及封闭世界 9 项生产复跑 | 通过 |
| STATIC-07 | Stage 10 资产类型隔离 | 加密货币、股票、未知类型复验 | 通过 |

首轮失败关闭：**26/26**。

## 三、Git 与哈希基线

验收前分支为 `feature/stage11-ethusdt-validation`，完整提交号为 `d6b2b6a447f55c8f59f17f31ff1fd326dfc095c3`，已暂存文件为 0。工作区包含实施方既有未提交变更，本轮以验收前快照为边界。

Stage 0 三个冻结文件、原 AKShare Raw、原 Stage 11 DuckDB、正常价格 CSV/JSON、历次验收目录及历次修复交付物均记录 SHA-256、大小和修改时间。验收后完全一致。既有 LF→CRLF 提示仅作为观察项，没有转换换行符。

## 四、封闭世界修复静态审查

审查确认：

1. 实际普通文件集合必须严格等于 Manifest 声明文件集合加 `manifest.json`；
2. 从 run-specific Raw 根目录递归枚举子目录；
3. 使用相对路径，统一路径分隔符并按 Windows 大小写不敏感语义比较；
4. 规范化点路径段，拒绝绝对路径、盘符、父目录穿越和逃逸；
5. 不跟随符号链接，显式拒绝 symlink、junction/reparse point 和其他非普通文件；
6. 保留原始列表，分别检测 Manifest 重复项和实际路径规范化后的重复项；
7. 对所有未声明文件稳定排序并逐项输出相对路径；
8. 底层阻断原因由 `validate_stage11_inputs` 原样汇总至生产命令，不会降级；
9. 未发现硬编码 `orphan.json`、特定测试文件名、自动删除、忽略或自动补录逻辑。

## 五、独立测试结果

| 测试范围 | 收集 | 通过 | 失败 | 跳过 | 预期失败 | 警告 | 退出码 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 封闭世界新增测试 | 12 | 12 | 0 | 0 | 0 | 0 | 0 |
| 原 Manifest 测试 | 22 | 22 | 0 | 0 | 0 | 0 | 0 |
| 既有修复测试 | 53 | 53 | 0 | 0 | 0 | 0 | 0 |
| Stage 11 全部测试 | 98 | 98 | 0 | 0 | 0 | 0 | 0 |
| Stage 10 全部测试 | 45 | 45 | 0 | 0 | 0 | 0 | 0 |
| Stage 0 检查 | 35 | 35 | 0 | 0 | 0 | 0 | 0 |
| 完整测试集 | 542 | 542 | 0 | 0 | 0 | 0 | 0 |

这些结果均为第四轮重新执行所得，没有复制修复方日志。

## 六、真实生产命令封闭世界验证

通过 `validate-crypto --validate-only` 独立制造并阻断：根目录孤立文件、嵌套孤立文件、备份文件、临时文件、隐藏文件、空文件、二进制文件、多个未声明文件及大小写变化的未声明文件。

每个异常均满足：非零退出码、顶层已阻断、不输出就绪、错误代码为 `manifest_unlisted_file`、输出具体相对路径、多个文件完整稳定排序，且 Raw、Manifest、CSV、JSON、DuckDB 的 SHA-256、大小和修改时间不变。孤立文件没有被删除或写入 Manifest。

## 七、完整故障矩阵

- 原始故障矩阵：**28/28 阻断**；
- Manifest 故障矩阵：**21/21 阻断**；
- 封闭世界故障矩阵：**9/9 阻断**；
- 强制故障总计：**58/58 阻断**。

所有场景均在临时副本上通过生产入口重新执行，没有只引用既有测试或 CSV。60 个受网络守卫覆盖的生产子进程连接调用总数为 0。

## 八、正常 960 行验证

未篡改的临时正常产物执行结果为就绪、退出码 0、960 行，前后快照完全一致。Manifest 封闭世界检查通过，未声明和缺失文件列表均为空。

Raw、CSV、JSON、DuckDB 全量一致；原始层、清洗层和指标层各 960 行，画像层 1 行，质量层 19 行，审计层 1 行。provider、exchange、原始/标准品种、现货类型及 1 小时周期八个身份维度均只有一个唯一值。时间戳连续、无重复和缺口，数值有限，OHLCV 合法，既有指标未变化。

同一运行编号再次执行为通过，Raw 与价格文件哈希稳定，数据库逻辑计数保持幂等。旧数据库返回已阻断、退出码 2，旧库哈希未变化。

## 九、Stage 10 隔离回归

加密货币返回结构化“不适用”，财务读取次数为 0；股票路径 45/45 回归通过；未知资产类型在入口边界被拒绝，没有默认进入股票路径。

## 十、文件完整性与变更边界

验收结束后，HEAD 未变化、已暂存文件仍为 0、实现目录所有 Python 文件哈希未变化。Stage 0、原 Raw、原 DuckDB和历次验收/修复文件均未变化。除 `reports/stage11_reaudit_round4/` 外，没有验收过程产生的新仓库修改。

## 十一、最终判定

附件列出的十一项通过条件全部满足，Stage 11 第四轮独立复验结论为：**通过**。
