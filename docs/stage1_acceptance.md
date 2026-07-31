# 阶段1 独立验收报告

> 验收日期：2026-07-28
> 验收类型：独立、严格、可复现验收

## 1. 验收范围

对阶段1"环境与项目骨架"的全部产物进行独立验收。不修復任何问题，不進入階段2。

## 2. 最终状态

| 项目 | 值 |
|---|---|
| **验收结论** | **PASS** |
| **是否允许进入阶段2** | **是** |
| 验收人 | Codex 独立验收任务 |

## 3. 环境和解释器

| 项目 | 值 |
|---|---|
| Python 版本 | 3.11.4 |
| 位数 | 64-bit |
| 虚拟环境 | `.venv` (隔离已验证) |
| `sys.prefix` | `.venv` |
| `sys.base_prefix` | `E:\anaconda` |
| 偏差 | 优选 3.12，当前 3.11.4（≥3.9 通过） |

## 4. 文件完整性

全部 18 个必需文件和 17 个必需目录存在。仅 `AGENTS.md` 被阶段1修改（追加 11 行 Stage 1 规则），无阶段0文件被修改。

## 5. 依赖和锁定文件

| 检查项 | 状态 |
|---|---|
| `pyproject.toml` 作为单一事实来源 | ✓ |
| `src` 布局 | ✓ |
| 14 个运行依赖完整 | ✓ |
| `pytest` + `pandera` dev 依赖 | ✓ |
| CLI 入口已配置 | ✓ |
| `requirements-lock.txt` 非空、含版本号 | ✓ |
| 锁文件无敏感信息 | ✓ |

## 6. 包导入结果

全部 14 个必需包可导入（14/14）：

```
akshare==1.18.80, pandas==3.0.5, numpy==2.4.6, pyarrow==25.0.0,
duckdb==1.5.5, sqlalchemy==2.0.51, pydantic==2.13.4, pyyaml==6.0.3,
dotenv (imported, no __version__), tenacity==9.1.4,
matplotlib==3.11.1, openpyxl==3.1.5, pytest==9.1.1, pandera==0.32.1
```

## 7. pip check

```bash
$ .venv\Scripts\python.exe -m pip check
No broken requirements found.
```

Exit code: 0 ✓

## 8. pytest 结果

```bash
$ .venv\Scripts\python.exe -m pytest -q
74 passed in 12.77s
```

Exit code: 0 ✓。无跳过、无 xfail、无失败。

## 9. Ruff 结果

Ruff 未安装。阶段1未要求 Ruff，记录为偏差。

## 10. show-config 结果

| 测试 | exit code | 日期 | 股票 | ETHUSDT |
|---|---|---|---|---|
| `--as-of-date 2026-07-27` | 0 | 2026-07-27 | 16 | ✓ |
| `--as-of-date 2026-07-20` | 0 | 2026-07-20 | 16 | ✓ |

- 无环境变量全集输出
- 无密钥、Cookie、Token
- CLI 日期覆盖功能正常

## 11. doctor 结果

```
Doctor check: PASS
  Python: 3.11.4 (64bit)
  Resolved as_of_date: 2026-07-27
  Packages: 14/14 importable
  Config checks: 9/9
  Filesystem checks: 20/20
  DuckDB memory: OK
```

Exit code: 0 ✓。JSON 已生成到 `reports/stage1_acceptance_doctor.json`。

## 12. 网络隔离证据

- `test_stage1_doctor.py` 中的 socket 阻断测试通过（7/7）
- 无 AKShare 数据接口调用（源码扫描确认）
- 无 `requests.get/post`、`httpx`、`urllib.request.urlopen` 调用
- `show-config` 不触发网络访问

## 13. 阶段0配置检查

| 检查项 | 状态 |
|---|---|
| 股票数量 = 16 | ✓ |
| 所有 6 位字符串 | ✓ |
| 无重复 | ✓ |
| 交易所映射正确 | ✓ |
| ETHUSDT 精确匹配 | ✓ |
| `exact_match_required=true` | ✓ |
| `allow_pair_substitution=false` | ✓ |
| 均线窗口 [3,5,7,10,13,20,21] | ✓ |
| 趋势前复权 | ✓ |
| 涨跌停不复权 | ✓ |
| 活跃度权重和 = 1.0 | ✓ |
| `as_of_date = 2026-07-27` | ✓ |

## 14. 阶段0 SHA-256 验证

| 文件 | 前 SHA-256 | 当前 SHA-256 | 一致 | 证据 |
|---|---|---|---|---|
| `config/universe.yml` | `0B6F61...CCEC65` | `0B6F61...CCEC65` | ✓ | `docs/stage1_environment.md` |
| `config/metric_definition.yml` | `13F941...5C00C4` | `13F941...5C00C4` | ✓ | `docs/stage1_environment.md` |
| `docs/stage0_scope.md` | `18EEEC...761615` | `18EEEC...761615` | ✓ | `docs/stage1_environment.md` |

## 15. 阶段越界检查

| 检查项 | 状态 |
|---|---|
| 无 AKShare 数据接口调用 | ✓ |
| 无阶段2适配器/抓取器 | ✓ |
| 无正式业务表 DDL | ✓ |
| `data/raw`、`clean`、`feature`、`export` 仅有 `.gitkeep` | ✓ |
| `database` 仅有 `.gitkeep` | ✓ |
| `duckdb.connect` 仅用于 `:memory:` | ✓ |

## 16. 敏感信息检查

所有与 `api_key`、`token`、`password`、`cookie`、`proxy`、`secret` 的匹配均为安全规则声明或测试用例。无实际凭据泄露。✓

## 17. 文档一致性检查

| 检查项 | 文档声明 | 实际结果 | 一致 |
|---|---|---|---|
| Python 版本 | 3.11.4 | 3.11.4 | ✓ |
| AKShare 版本 | 1.18.80 | 1.18.80 | ✓ |
| 测试通过数 | 74 | 74 | ✓ |
| Doctor 状态 | PASS | PASS | ✓ |
| pip check | 通过 | 通过 | ✓ |
| show-config | 16 股票 ETHUSDT | 16 股票 ETHUSDT | ✓ |
| 阶段0 哈希 | 一致 | 一致 | ✓ |

## 18. 失败项

无。

## 19. 警告项

| 警告 | 说明 |
|---|---|
| Python 3.11.4 非 3.12 | 阶段1 规格优先推荐 3.12，当前为 3.11.4。≥3.9 最低要求满足。 |
| Ruff 未安装 | Ruff 未被阶段1要求声明，不构成失败。 |

## 20. 修复建议

无需修复。

## 21. 阶段2 入口结论

> 阶段1已独立验收通过，可以进入阶段2：接口盘点与冒烟测试。

## 22. 验收产物

- `reports/stage1_acceptance_report.json`
- `docs/stage1_acceptance.md`
- `reports/stage1_acceptance_doctor.json`
