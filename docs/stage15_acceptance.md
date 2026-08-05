# 阶段15验收记录

验收日期：2026-08-05。全部命令从项目根目录、已激活 `.venv` 的解释器执行。
基线提交：`d8eee25 feat(stage14): complete final acceptance closure`（当前分支
`feature/stage15` 的 HEAD 为 `fd22519`，是基线之上的既有 chore 提交，仅新增
`logs/` 与 `reports/run_status/` 忽略规则）。

## 验收清单

| 编号 | 原文要求 | 实现位置 | 验收方法 | 结果 |
| -: | --- | --- | --- | --- |
| S15-1 | 15.1 每日质量检查：行数异常下降 | `stage15_checks.py::_row_count_rows` | 合成数据 + 基线对比测试 | 通过 |
| S15-2 | 最新交易日更新 | `_latest_trade_date_rows` | 合成数据 + 真实库 max(trade_date) | 通过 |
| S15-3 | 字段集合变化 | `_schema_rows` | 基线 schema 对比测试 | 通过 |
| S15-4 | 样本股票缺失 | `_coverage_rows` | 16 股覆盖率检查 | 通过 |
| S15-5 | OHLC 逻辑关系 | `_ohlc_rows` | 非法 OHLC 注入测试 | 通过 |
| S15-6 | 主键重复 | `_duplicate_rows` | 重复主键注入测试 | 通过 |
| S15-7 | 非法负成交量/金额 | `_negative_volume_rows` | 负值注入测试 | 通过 |
| S15-8 | PE/PB 缺失率异常 | `_pe_pb_missing_rows` | 高缺失率注入测试 | 通过 |
| S15-9 | 财报关键字段缺失 | `_financial_key_field_rows` | Stage10 12 项映射覆盖测试 | 通过 |
| S15-10 | 接口执行耗时突增 | `_elapsed_rows` | 基线倍数与配置阈值测试 | 通过 |
| S15-11 | 15.2 交叉验证：最近5日收盘/成交量 | `build_cross_validation` | 合成 + 真实库快照 | 通过 |
| S15-12 | 15.2 交叉验证：最近一期营收/归母净利润 | `_latest_financial_value` | 合成 + 真实库快照 | 通过 |
| S15-13 | 15.2 交叉验证：最新 PE/PB | `build_cross_validation` | 真实库快照 | 通过 |
| S15-14 | 15.2 交叉验证：最近涨停日/次日开盘 | Stage 8 正式事件读取 | Stage8 缺失时 UNAVAILABLE，不伪造 | 部分通过（需补验） |
| S15-15 | 15.3 风险日志 10 字段 | `build_risk_log` | 字段契约测试 | 通过 |
| S15-16 | CLI 命令 | `cli.py::quality-control` | help/dry-run/validate/real 测试 | 通过 |
| S15-17 | 幂等与 run_id | `stage15_build.py` | 同 run_id 重跑测试 | 通过 |
| S15-18 | Stage8 阻塞处理 | `stage8.block_whole_run=false` + risk log | 真实运行验证 | 通过 |
| S15-19 | 阶段1—14回归 | 全量 pytest | 866 项全过 | 通过 |
| S15-20 | 文档交付 | `docs/stage15_implementation.md`、`docs/stage15_acceptance.md` | 存在且内容完整 | 通过 |

## 测试命令与结果

| 命令 | 退出码 | 结果 |
| --- | --: | --- |
| `python -m compileall -q src tests run_pipeline.py` | 0 | 语法检查通过 |
| `python -m pytest -q tests/test_stage15_*.py` | 0 | 47 passed |
| `python -m pytest -q tests/test_stage1_structure.py tests/test_stage15_*.py` | 0 | 83 passed（含阶段1边界） |
| `python -m pytest -q` | 0 | 867 passed in 224.86s |

阶段15定向测试覆盖：正常路径、空输入、缺失输入、非法参数、日期边界、重复运行、
失败退出码、输出路径、输出结构、幂等性、不覆盖历史成果、BLOCKED 传播、中文路径
与 UTF-8、字段契约、风险日志状态枚举、无投资建议文本。

## 真实运行证据

```text
run_id: 3d4c304c-b0c9-41ac-9b6e-2487244a93ca
as_of_date: 2026-07-27
命令: python run_pipeline.py quality-control --as-of-date 2026-07-27 --run-id 3d4c304c-b0c9-41ac-9b6e-2487244a93ca
退出码: 0
状态: PASS
质量检查: 58 pass, 0 warn, 0 fail
风险日志: 8 行（2 blocked + 6 open）
交叉验证: 21 行（3 只股票 × 7 项）
Stage8 阻塞: no_authoritative_limit_rules; no_authoritative_security_status_history
```

复核状态语义后新增一次验证运行（`run_id: 647c9927-9cc5-4242-be31-852bea677579`）：

```text
退出码: 0
状态: PASS_WITH_UNAVAILABLE_ITEMS
质量检查: 58 pass, 0 warn, 0 fail
unavailable_items: 6
blocked_risks: 2
说明: 每日质量检查通过，但 S15-14 交叉验证仍存在 UNAVAILABLE 项和 Stage 8 blocked 风险
```

历史运行 `3d4c304c…` 与 `cb6125d0…` 的状态字段在本次状态语义修正前生成，其
`quality_summary.json` 仍保留当时的 `PASS` 标签；本次复核已修正状态判定，后续
运行不会再出现用 `PASS` 掩盖 `UNAVAILABLE` 的情况。

报告目录 `reports/stage15/3d4c304c-b0c9-41ac-9b6e-2487244a93ca/`：

| 文件 | 大小 | SHA-256 |
| --- | ---: | --- |
| `quality_check_results.csv` | 18000 | 84B0C9CF1D4F5D6F2BFC5590EBC6DAEFFCFB4EF1F40B6AEC4B3ADFC6A962E88D |
| `quality_summary.json` | 47710 | 293571A62E10872A45E09F5E606A0D8602174041F37A6609E005BA784201C99A |
| `cross_validation.csv` | 4643 | D9E69FE0EFB852361311927C82C1842F6AFC2DCA9395E2DE0CDAB6E6BD322228 |
| `cross_validation.md` | 4336 | A385A3A14FD7EA1D37115A2E4D377EA34A38A972C19373CEB4EC4A1B16557688 |
| `risk_log.csv` | 2655 | 5144D191B3561725957644FC5776A3AEEEC5A8A2E2CB0617F3A52E3D4C60BBEA |
| `risk_log.json` | 4285 | AC1AA35D0FB0B0CE18D24CA838C7A9A2A4E9F9F9C75E03A60E3AB1EA6BCEDA52 |

数据库 `database/stage15/3d4c304c-b0c9-41ac-9b6e-2487244a93ca/stage15_quality.duckdb`
（2371584 字节，SHA-256 005B6B9D2F25EDE3294DD140DE5AE546820C4C501C66879C6E85F1D9752A6D54）：

| 表 | 行数 |
| --- | ---: |
| `quality.check_result` | 58 |
| `quality.risk_log` | 8 |
| `quality.cross_validation` | 21 |
| `audit.stage15_run` | 1 |

交叉验证快照中 `002067`：最近5日收盘/成交量、最新营收
`1429974397.88@2026-03-31`、归母净利润 `21210555.74@2026-03-31`、PE 74.05、
PB 0.94 均为 `REVIEW`；涨停相关两项为 `UNAVAILABLE`（Stage 8 阻塞，不伪造）。

## 回归与范围检查

- 全量测试 866 项通过，未发现阶段1—14回归。
- 阶段0冻结文件（`config/universe.yml`、`config/metric_definition.yml`、
  `docs/stage0_scope.md`）未修改。
- 阶段14 `quality-check` 仍映射 `validate-stage5`，11 步顺序不变。
- 未纳入 `logs/` 与 `reports/run_status/`，未使用 `git add .`。
- 新增运行产物位于 `reports/stage15/<run_id>/` 与
  `database/stage15/<run_id>/`，按现有 `.gitignore` 保持未跟踪。

## Stage 8 阻塞影响

阶段15不依赖 Stage 8 实际业务产物完成每日质量检查和风险日志；只有交叉验证涨停项
受影响，已如实标记 `UNAVAILABLE` 并写入 `blocked` 风险，不伪造数据。按本次最终
验收规则复核，原始文档没有明确允许 `UNAVAILABLE` 作为 S15-14 的通过状态，因此
S15-14 判定为部分通过，需后续单独数据治理任务补齐权威规则与证券状态历史后补验。

## 未完成项与 PowerShell 任务

唯一未完成项：S15-14“最近一个涨停日及次日开盘价”交叉验证尚未产生实际可核对数据，
阻塞原因为 Stage 8 缺少权威涨跌停规则与证券状态历史。代码、降级记录和风险日志已
完成，只待权威输入后补验。阶段15没有遗留的 PowerShell 独立任务。

## 最终验收规则复核（S15-14）

### 原始文档证据

| 文档 | 章节或行号 | 原文准确概括 | 对 S15-14 的影响 |
| -- | ----- | ------ | ---------- |
| 分阶段操作步骤 | 15.2（第997、1002、1004行） | 选2～3只股票，对“最近一个涨停日及次日开盘价”等四项进行人工核对；交叉验证仅用于确认数量级和字段解释 | S15-14 被明确列为必须人工核对的确认项，需要实际可核对数据 |
| 分阶段操作步骤 | 3.6（第310行） | 日期无数据时记录为“非交易日、上游暂无数据或接口失败”，不能默认为 0 个涨停 | 上游缺失必须如实记录且禁止伪造，但原文没有规定 `UNAVAILABLE` 可作为通过状态 |
| 总纲 | 10（第270行） | 历史涨跌停池仅支持近期，无法直接统计全年；以日线和历史规则自行重建事件，股池仅用于校验 | 正式涨停事件依赖权威规则与证券状态历史，缺失时无法合法替代 |
| 总纲 | 11.2（第293行） | 资金流、涨跌停池等受限接口必须记录实际覆盖范围 | 记录不可用是义务，但不等同于交叉验证已完成 |
| AGENTS.md | Data integrity（第38行） | Empty DataFrame and call failure must be recorded as separate statuses | 空/不可用与成功必须分开，`UNAVAILABLE` 不能并入成功状态 |
| stage0_scope.md | 2.7（第74-78行） | 涨跌停识别必须考虑交易所、板块、ST历史、上市状态、规则生效日期；股池仅用于校验 | 缺少权威输入时正式涨停事件无法产出，S15-14 无合法替代输入 |
| stage0_scope.md | 6（第176行） | 涨跌停规则表和证券状态历史表的构建列为尚未进入实现的事项 | 缺口在阶段0已冻结，不构成阶段15的完成豁免 |

### S15-14 判定

结论B：**部分通过。** 工程降级和风险记录正确，但实际交叉验证尚未完成。原因：
原始文档要求对“最近一个涨停日及次日开盘价”进行人工核对，但没有明确允许
`UNAVAILABLE` 作为通过状态；项目原则只规定缺失数据必须如实记录、不得伪造，
并未把“如实记录缺失”升级为“验收通过”。

### 整体 PASS 状态是否准确

不准确。原实现把整体状态标为 `PASS`，而同一运行同时存在 2 条 BLOCKED 风险和 6 个
`UNAVAILABLE` 交叉验证项，容易让用户误认为所有交叉验证数据均可用。本次复核已将
状态判定改为 `PASS_WITH_UNAVAILABLE_ITEMS`，并在 CLI 与 `quality_summary.json`
中显著输出 `unavailable_items`、`blocked_risk_count` 和受影响的 Stage 8 阻塞码。

### 是否需要后续补验

需要。补验条件：提供权威涨跌停规则与证券状态历史后重跑 `quality-control`，
S15-14 两项从 `UNAVAILABLE` 变为实际可核对值，整体状态不再出现
`PASS_WITH_UNAVAILABLE_ITEMS`。

## 最终结论

**阶段15主体通过，但 S15-14 仍需补验，暂不能称为完全通过。**
