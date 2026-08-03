# Stage 12 实施验收记录

## 结论

本文件保留首次独立验收失败事实，并记录针对 `S12-AUDIT-001` 至 `004` 的修复轨迹。
修复后实现验证 fixture 返回 `READY`，但本轮仅说明 Stage 12 具备重新独立验收条件，
不代替新的独立验收结论。fixture 只用于验证工程能力，不代表真实证券筛选结论，
也不构成投资建议。

## 独立验收失败与关闭轨迹

| 问题 | 原失败事实 | 修复文件 | 回归测试与故障注入 | 本轮结果 |
|---|---|---|---|---|
| S12-AUDIT-001 | 负阈值、越界信号阈值和非法精度被接受 | `stage12_config.py`、`test_stage12_config.py` | 独立探针与 pytest 分别执行 12 个原门禁、6 个扩展门禁、105 个非有限数值案例 | closed：独立探针全部阻断，自动化案例全部通过 |
| S12-AUDIT-002 | `growth_score` 缺失且 `revenue_growth=Infinity` 时返回 READY | `stage12_analysis.py`、`fundamental_price_volume.py`、Stage 12 分析/CLI 测试 | 七个评分输入 × NaN/±Infinity/非法字符串；原始复现样例 | closed：28/28 阻断；原始样例 BLOCKED、退出码 2、零写入 |
| S12-AUDIT-003 | Stage 9/12 区间宽度和常数 R² 不一致 | `style_features.py`、`analysis/range_bound.py`、Stage 9/12 测试 | 常数、涨跌趋势、震荡、近等值、异常点及逆序输入 | closed：共享权威函数，跨阶段全部等价 |
| S12-AUDIT-004 | 原 21 个专项测试未覆盖上述缺陷，后续验收文档又把独立探针误称为 pytest 回归 | 三个 Stage 12 测试文件及 `test_style_features.py` | 完整 12+6+105 配置矩阵、结构化 CLI 和跨阶段等价测试 | closed：配置测试 135 passed，Stage 12 专项 188 passed，完整回归 731 passed |

## S12-AUDIT-004 自动化矩阵与独立探针

自动化矩阵位于 `tests/test_stage12_config.py`，字段清单是显式、固定且可审计的，未通过
动态遍历配置生成。对应测试函数为：

- Required configuration：`test_required_configuration_matrix_is_blocked`，pytest 自动化
  案例 12/12 passed。
- Extended configuration：`test_extended_configuration_matrix_is_blocked`，pytest 自动化
  案例 6/6 passed。
- Non-finite configuration：`test_all_numeric_config_fields_reject_non_finite`，显式 35 个
  数值字段分别注入 NaN、正 Infinity 和负 Infinity，pytest 自动化案例 105/105 passed。

三个矩阵另有独立的规模自检。Extended 的历史计数把信号阈值上界校验作为一个类别，
自动化六项矩阵以 `strong=2.0` 为该类别的代表；`moderate=1.5` 仍作为额外独立 pytest
案例保留，没有把两个字段合并进同一个测试节点。

pytest 参数定义之外另经 stdin 临时脚本重新构造非法配置并直接调用
`load_stage12_config`，结果为：

- Required configuration independent probes：12/12 blocked。
- Extended configuration independent probes：6/6 blocked。
- Non-finite configuration：35 个数值字段 × 每字段 3 个非有限值；independent probes
  105/105 blocked。

因此本文所称 `passed` 仅指 pytest 自动化案例，`blocked` 仅指独立非法配置探针；
`S12-AUDIT-004` 通过完整 12+6+105 自动化矩阵关闭。

## Git 与冻结基线

- 分支：`feature/stage12-analysis-examples`
- Stage 11 标签：`stage11-complete`
- 标签提交：`2aca17a74e2d4d7c2d9ee1265cfc1eff75c95740`
- `git merge-base --is-ancestor "stage11-complete^{}" HEAD`：退出码 0
- Stage 0 冻结 SHA-256：
  - `config/universe.yml`：`0b6f61d43e753945b7e7931d27359e34a199891eac3f7d59f29c9d17efccec65`
  - `config/metric_definition.yml`：`13f9415d3e55aacc91e9913652d6e6520d9c681ac3043f09409602c44b5c00c4`
  - `docs/stage0_scope.md`：`18eeec59594b2cca67cfc7e7f137855ed2b1f018c10623e426340188ac761615`
- 没有修改 Stage 11 Raw、DuckDB、验收证据、标签或提交历史。

## 测试结果

Stage 12 配置测试：

```text
135 passed in 1.93s
```

三个 `tests/test_stage12_*.py` 文件显式收集后的专项测试：

```text
188 passed in 6.65s
```

加入新增修复测试后的完整离线回归：

```text
731 passed in 171.45s (0:02:51)
```

首次实现的 21 项 Stage 12 测试虽通过但存在验收缺口；本轮没有删除、跳过、xfail 或
放宽原断言，而是把独立验收故障样例转为独立、可见的 pytest 参数节点。完整运行
`0 failed`，没有新增 skip、xfail，也没有用 warning 掩盖失败。

## 质量、安全与确定性

- 网络调用：0；测试 `conftest.py` 全局阻断真实 socket。
- fixture 输入：250 行可见价格、2 行可见基本面；另有 1 行未来价格和 1 行未来基本面。
- 未来记录：均被显式排除并记录为警告；修改未来极端值后全部 manifest 和输出保持一致。
- 修复后规范化结果 SHA-256：`4f755345be7b778ed46610b58abefaac691cc4acec19f908d46a9c8ce5838543`
- 旧哈希 `871747c51f17bf933cc21af9007dad27a5c439087fb124ce6d913894b483fb02`
  因相对区间宽度从错误的中点除法切换为 Stage 9 的 `high/low-1` 权威口径而变化。
- 同 run 重复生成全部七个 `stage12_*` 报告，逐文件 SHA-256 无变化。
- 输入顺序反转后七文件仍为 7/7 稳定，规范化哈希保持一致。
- dry-run：不创建数据库或报告目录；已有数据库文件不作为写入目标。
- DuckDB：同 run 重跑不产生重复行；不同输入复用同 run 被拒绝。
- 故障注入：事务中第二个关系注册失败后，旧 run 的全部行数保持不变。
- 原始基本面 Infinity 故障注入：`BLOCKED`、退出码 2，字段级阻断原因，数据库和报告均不存在。
- 配置故障注入：独立探针 Required 12/12、Extended 6/6、非有限配置 105/105 阻断；
  对应 pytest 自动化案例分别为 12/12、6/6、105/105 passed。
- Stage 9/12 等价探针：区间高低、绝对/相对宽度、斜率、归一化斜率和 R² 全部一致。
- fixture 数据库行数：活跃度 2、突破 2、区间 2、联合分析 2、质量 17。
- `git diff --check`：无空白错误。
- `.duckdb`、Raw、缓存、虚拟环境和临时日志均不属于 Stage 12 交付文件。

## 已知限制

- Stage 9 和 Stage 10 当前仓库报告明确标记为尚未正式运行，Stage 10 缺少已验证的
  Stage 5 manifest；因此没有将它们的空报告伪装成真实 Stage 12 基本面结果。
- 仓库内 Stage 12 CSV/JSON 是明确标记的 `implementation_validation_fixture`。
  对真实数据运行时应通过 CLI 传入经过来源和可用日期验证的价格及基本面 CSV。
- 组合分数使用可用权重重新归一化并保留完整度；它不是交易信号。
- 本阶段不定义入场、出场或止损，因此不计算策略盈亏比。

## 提交门禁

本记录只证明测试和审计已通过，不授权自动提交。仅在用户明确要求后才可执行：

```powershell
git commit -m "feat(stage12): add reproducible quantitative analysis examples"
```
