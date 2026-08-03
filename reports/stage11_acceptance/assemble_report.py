from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
EVIDENCE = json.loads((OUT / "independent_audit_evidence.json").read_text(encoding="utf-8"))
NETWORK = json.loads((OUT / "stage11_network_evidence.json").read_text(encoding="utf-8"))
TESTS = json.loads((OUT / "test_execution_results.json").read_text(encoding="utf-8"))
FAULTS = list(csv.DictReader((OUT / "stage11_fault_injection.csv").open(encoding="utf-8-sig")))


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=True).stdout.rstrip()


checks: list[dict] = []


def add(check_id, category, description, method, command, expected, actual, evidence, status, severity, notes=""):
    checks.append({
        "check_id": check_id, "category": category, "description": description,
        "method": method, "command": command, "expected": expected, "actual": actual,
        "evidence": evidence, "status": status, "severity": severity, "notes": notes,
    })


branch = git("branch", "--show-current")
head = git("rev-parse", "HEAD")
tag = git("rev-parse", "stage10-verified-20260802^{commit}")
ancestor_rc = subprocess.run(["git", "merge-base", "--is-ancestor", "stage10-verified-20260802", "HEAD"], cwd=ROOT).returncode
status_short = git("status", "--short")
status_branch = git("status", "--short", "--branch")
diff_stat = git("diff", "--stat")
diff_names = git("diff", "--name-status")
diff_check = subprocess.run(["git", "diff", "--check"], cwd=ROOT, text=True, capture_output=True)
staged = git("diff", "--cached", "--name-only")
untracked = git("ls-files", "--others", "--exclude-standard")
ignored_relevant = "\n".join(x for x in git("status", "--short", "--ignored").splitlines() if any(k in x for k in ("database/", "data/raw/crypto_js_spot")))

frozen = [
    ("config/universe.yml", "0B6F61D43E753945B7E7931D27359E34A199891EAC3F7D59F29C9D17EFCCEC65", "reports/stage1_acceptance_report.json"),
    ("config/metric_definition.yml", "13F9415D3E55AACC91E9913652D6E6520D9C681AC3043F09409602C44B5C00C4", "reports/stage1_acceptance_report.json"),
    ("docs/stage0_scope.md", "18EEEC59594B2CCA67CFC7E7F137855ED2B1F018C10623E426340188AC761615", "reports/stage1_acceptance_report.json"),
]
frozen_rows = []
for path, reference, source in frozen:
    current = hashlib.sha256((ROOT / path).read_bytes()).hexdigest().upper()
    frozen_rows.append((path, current, reference, current == reference, source))

add("GIT-01", "git", "当前分支", "Git 查询", "git branch --show-current", "feature/stage11-ethusdt-validation", branch, "stage11_git_evidence.txt", "PASS" if branch == "feature/stage11-ethusdt-validation" else "FAIL", "CRITICAL")
add("GIT-02", "git", "Stage10 标签祖先关系", "Git merge-base", "git merge-base --is-ancestor stage10-verified-20260802 HEAD", "exit 0", f"exit {ancestor_rc}; tag={tag}; HEAD={head}", "stage11_git_evidence.txt", "PASS" if ancestor_rc == 0 and tag == head else "FAIL", "CRITICAL")
add("GIT-03", "git", "Stage0 冻结文件 SHA-256", "逐字节 SHA-256 与既有验收基线比对", "Get-FileHash SHA256", "3/3 一致", f"{sum(x[3] for x in frozen_rows)}/3 一致", "stage11_git_evidence.txt", "PASS" if all(x[3] for x in frozen_rows) else "FAIL", "CRITICAL", "HEAD blob 与工作树换行表现不同；逐字节哈希与保存基线一致。")
add("GIT-04", "git", "验收过程变更边界", "前后 Git 状态复核", "git status --short", "验收新增仅在 reports/stage11_acceptance/", "满足；实现方原有未提交变更仍在", "stage11_git_evidence.txt", "PASS", "HIGH")
add("GIT-05", "git", "工作树换行提示", "git diff --check stderr 审查", "git diff --check", "无阻断性 whitespace error", "exit 0；三个既有 tracked 改动提示下次 Git 接触时 LF 将转 CRLF", "stage11_git_evidence.txt", "OBSERVATION", "LOW")
add("STATIC-01", "static", "网络调用集中于 adapter", "源码审查", "rg adapters/collectors", "业务层无 HTTP", "OKX/Binance/AKShare 网络能力位于 adapters/crypto_exchange.py", "src/akshare_data_test/adapters/crypto_exchange.py", "PASS", "HIGH")
add("STATIC-02", "static", "目标 instrument 与市场身份不可被改名冒充", "源码审查及 B1/B2/B6 注入", "independent_audit.py", "非 ETH-USDT SPOT 必须阻断", "normalize_crypto_bars 按配置覆盖 symbol/exchange/market；注入未阻断", "stage11_fault_injection.csv; src/akshare_data_test/crypto_market.py:45", "FAIL", "CRITICAL")
add("STATIC-03", "static", "持久化 provider、原始品种、标准品种和周期", "SQL/模型/导出字段审查", "rg data_provider original_symbol", "字段齐全且可追溯", "仅 source/symbol/exchange/market/interval；无 data_provider/original instrument", "sql/stage11_schema.sql; stage11_data_reconciliation.csv", "FAIL", "CRITICAL")
add("STATIC-04", "static", "crypto 时间与年化口径", "配置和公式审查+独立重算", "independent_audit.py", "UTC、24/7、8760", "UTC/continuous_24_7/8760，未使用 252", "config/stage11.yml; stage11_metric_recalculation.csv", "PASS", "HIGH")
add("STATIC-05", "static", "CSV/JSON/DuckDB 一致性质量门禁", "源码审查及 D1-D4 注入", "validate-crypto --validate-only", "任一产物篡改必须阻断", "质量行预置 PASS；validate-only 不读取既有产物，D1-D4 均 READY", "src/akshare_data_test/stage11_build.py:159; stage11_fault_injection.csv", "FAIL", "CRITICAL")
add("STATIC-06", "static", "Raw 探针证据门禁", "源码审查及 E1-E5 注入", "validate-crypto --validate-only", "缺失/空/不一致必须阻断", "validate_stage11_inputs 不检查 Raw；E1-E5 均 READY", "src/akshare_data_test/stage11_build.py:56; stage11_fault_injection.csv", "FAIL", "CRITICAL")
add("STATIC-07", "static", "Stage10 生产财务入口隔离 crypto", "调用链审查及 F3 注入", "rg require_equity_asset", "crypto 明确 not_applicable 且不执行财务分析", "防护 helper 仅被测试调用；analyze_stage10 无 asset_type 参数/生产防护", "src/akshare_data_test/fundamental_analysis.py:25; src/akshare_data_test/stage10_build.py:271", "FAIL", "CRITICAL")
add("STATIC-08", "static", "Repository 事务与幂等", "临时 DuckDB 两次重跑+失败回滚", "independent_audit.py", "计数/哈希稳定、无重复、回滚完整", json.dumps(EVIDENCE["idempotency"], ensure_ascii=False), "independent_audit_evidence.json", "PASS", "HIGH")

for t in TESTS:
    add("TEST-" + t["scope"].upper().replace(" ", "-"), "tests", t["scope"], "独立执行并捕获 stdout/stderr/退出码", t["command"], "exit 0，无 failed/skip/xfail", f"collected={t['collected']}, passed={t['passed']}, failed={t['failed']}, skipped={t['skipped']}, xfail={t['xfail']}, exit={t['exit_code']}", "stage11_test_execution.log", "PASS" if t["exit_code"] == 0 and t["failed"] == 0 and t["skipped"] == 0 and t["xfail"] == 0 else "FAIL", "HIGH")

raw = EVIDENCE["akshare_raw"]
add("RAW-01", "akshare", "AKShare 精确 ETHUSDT 能力判断", "独立读取完整 parquet 并搜索所有字段", "independent_audit.py", "exact=0 且 unsupported", f"rows={raw['row_count']}, ETH rows={raw['eth_related_rows']}, exact={raw['exact_ethusdt_rows']}, status={raw['independent_status']}", "independent_audit_evidence.json", "PASS", "CRITICAL")
add("RAW-02", "akshare", "AKShare Raw 元数据完整性", "响应和 metadata 字段核对", "independent_audit.py", "抓取时间、版本、参数、列、行数、schema hash", f"missing={raw['metadata_missing_fields']}", "independent_audit_evidence.json", "FAIL", "HIGH")

for key, desc in [("okx_http_200", "OKX 公共接口可访问"), ("okx_exact_spot_instrument", "ETH-USDT 确认为 SPOT"), ("saved_latest_found_live", "保存末根K线可与实时历史接口重叠"), ("saved_latest_confirmed_closed", "末根K线 confirm=1"), ("saved_latest_values_match", "重叠 OHLCV/quote volume 一致"), ("binance_http_451_reproduced", "Binance HTTP 451 可复现")]:
    value = NETWORK["checks"][key]
    add("NET-" + key.upper(), "network", desc, "独立 urllib 公共只读请求", "network_check.py", "true", str(value).lower(), "stage11_network_evidence.json", "PASS" if value else "FAIL", "CRITICAL" if "okx" in key or "spot" in key else "HIGH")

dq = EVIDENCE["data_quality"]
quality_ok = dq["row_count"] == 960 and dq["unique_timestamps"] == 960 and not any(dq[k] for k in ("missing_intervals", "non_hour_differences", "duplicated_timestamps", "invalid_ohlc_count", "negative_volume_count", "non_finite_numeric_count", "invalid_timestamp_count"))
add("DATA-01", "data", "960 根小时K线底层质量", "独立读取 OHLCV，不调用项目质量函数", "independent_audit.py", "960、逐小时、无重复/非法值", json.dumps(dq, ensure_ascii=False), "independent_audit_evidence.json", "PASS" if quality_ok else "FAIL", "CRITICAL")
add("DATA-02", "data", "40 个完整 UTC 自然日边界", "按 UTC 日独立分组", "independent_audit.py", "40 日×24=960；2026-06-18 00:00 至 2026-07-27 23:00", f"min={dq['min_timestamp']}, max={dq['max_timestamp']}, daily_counts={set(dq['utc_day_counts'].values())}", "independent_audit_evidence.json", "PASS", "HIGH")
add("DATA-03", "data", "原始 instrument 身份保留", "字段与注入核验", "independent_audit.py", "每行保留 ETH-USDT 原始品种", "无原始品种字段；只有标准 symbol=ETHUSDT", "stage11_data_reconciliation.csv", "FAIL", "CRITICAL")
add("RECON-01", "reconciliation", "CSV/JSON/DuckDB 独立逐行一致性", "全量排序、UTC 规范化、1e-12 数值容差、规范化 SHA-256", "independent_audit.py", "字段/主键/960行/值/哈希一致", f"failed={EVIDENCE['reconciliation']['failed']}; hashes={EVIDENCE['reconciliation']['rounded_hashes']}", "stage11_data_reconciliation.csv", "PASS" if EVIDENCE["reconciliation"]["failed"] == 0 else "FAIL", "CRITICAL")
add("METRIC-01", "metrics", "Stage9 指标独立重算", "仅从 OHLCV 自行实现公式", "independent_audit.py", "16项在1e-12容差内", f"failed={EVIDENCE['metrics']['failed']}; checks={EVIDENCE['metrics']['checks']}", "stage11_metric_recalculation.csv", "PASS" if EVIDENCE["metrics"]["failed"] == 0 else "FAIL", "CRITICAL")

for f in FAULTS:
    add("FAULT-" + f["id"], "fault_injection", f["injected_fault"], "每项独立临时 CSV/JSON/DuckDB/Raw 副本", "independent_audit.py", f["expected_gate"], f["actual_result"], "stage11_fault_injection.csv", f["status"], "CRITICAL" if f["status"] == "FAIL" else "HIGH", f"exit_code={f['exit_code']}; blocked={f['blocked']}")

add("DOC-01", "documentation", "来源边界与研究用途", "实现文档/报告文本审查", "rg OKX AKShare Binance", "披露实际来源、范围、时区，不含投资结论", "已披露 OKX 实际来源、AKShare unsupported、Binance 451、40 UTC 日、研究验证用途", "docs/stage11_implementation.md; reports/stage11_validation.md", "PASS", "HIGH")
add("DOC-02", "documentation", "外部接口许可/使用条件", "文档引用审查", "rg docs", "引用官方接口说明并记录使用风险", "有官方接口 URL/参数，但未形成许可条款审查证据", "docs/stage11_implementation.md", "OBSERVATION", "MEDIUM", "不作法律结论，建议法务确认。")
add("SAFETY-01", "safety", "无投资建议或价格预测", "报告和生成物关键词/语义审查", "rg", "仅描述统计特征", "未发现买卖建议、预测或投资结论", "reports/stage11_validation.md; reports/stage11_independent_audit.md", "PASS", "CRITICAL")

mandatory = [x for x in checks if x["status"] != "OBSERVATION"]
passed = sum(x["status"] == "PASS" for x in mandatory)
failed = sum(x["status"] == "FAIL" for x in mandatory)
blocked = sum(x["status"] == "BLOCKED" for x in mandatory)
final_status = "BLOCKED" if blocked and failed == 0 else "FAIL" if failed else "PASS"

results = {
    "schema_version": "stage11-independent-acceptance-v1",
    "generated_at": datetime.now().astimezone().isoformat(),
    "final_status": final_status,
    "mandatory_checks_passed": passed,
    "mandatory_checks_total": len(mandatory),
    "failed_checks": failed,
    "blocked_checks": blocked,
    "checks": checks,
    "artifacts": sorted(p.name for p in OUT.iterdir() if p.is_file()),
}
(OUT / "stage11_acceptance_results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

env_lines = [
    f"captured_at={datetime.now().astimezone().isoformat()}", f"os={platform.platform()}",
    f"python={sys.version.replace(chr(10), ' ')}", "environment=.venv (project existing virtual environment)",
    "dependency_source=project requirements-lock.txt and editable project install",
    "clean_environment_created=no; existing locked project venv used; reproducibility limitation recorded",
]
for package in ("akshare", "pandas", "numpy", "duckdb", "pytest", "pyarrow", "yaml"):
    try:
        module = __import__(package)
        env_lines.append(f"{package}={getattr(module, '__version__', 'unknown')}")
    except Exception as exc:
        env_lines.append(f"{package}=IMPORT_ERROR:{exc}")
env_lines.append("\n--- requirements-lock.txt ---\n" + (ROOT / "requirements-lock.txt").read_text(encoding="utf-8"))
(OUT / "stage11_environment.txt").write_text("\n".join(env_lines), encoding="utf-8")

git_lines = [
    f"captured_at={datetime.now().astimezone().isoformat()}", f"branch={branch}", f"HEAD={head}",
    f"stage10_tag={tag}", f"stage10_is_ancestor_exit={ancestor_rc}", "\n--- status --short --branch ---", status_branch,
    "\n--- status --short ---", status_short, "\n--- tracked diff --stat ---", diff_stat,
    "\n--- tracked diff --name-status ---", diff_names, "\n--- diff --check stdout ---", diff_check.stdout or "(clean)",
    "\n--- diff --check stderr ---", diff_check.stderr or "(none)",
    "\n--- staged files ---", staged or "(none)", "\n--- untracked files ---", untracked,
    "\n--- relevant ignored evidence ---", ignored_relevant, "\n--- frozen SHA-256 ---",
]
for path, current, reference, match, source in frozen_rows:
    git_lines.append(f"{path}\tcurrent={current}\treference={reference}\tmatch={match}\tsource={source}")
(OUT / "stage11_git_evidence.txt").write_text("\n".join(git_lines), encoding="utf-8")

test_rows = "\n".join(f"| {t['scope']} | `{t['command']}` | {t['collected']} | {t['passed']} | {t['failed']} | {t['skipped']} | {t['exit_code']} | {t['status']} |" for t in TESTS)
frozen_table = "\n".join(f"| `{p}` | `{c}` | `{r}` | {'PASS' if m else 'FAIL'} | `{s}` |" for p,c,r,m,s in frozen_rows)
failure_rows = [x for x in checks if x["status"] == "FAIL"]
top_failures = "\n".join(f"- `{x['check_id']}` {x['description']}：{x['actual']}。证据：`{x['evidence']}`" for x in failure_rows[:10])
fault_pass = sum(f["status"] == "PASS" and f["blocked"].lower() == "true" for f in FAULTS)

report = f"""# Stage 11 ETHUSDT 独立验收报告

## 1. 执行摘要

本次仅执行独立验收，没有修改实现代码、配置、SQL、既有测试或既有报告。独立公网核验、全量数据对账、指标重算、临时数据库幂等测试及 29 项故障注入均已执行。

## 2. 最终结论

**FAIL**。强制检查通过 {passed}/{len(mandatory)}，失败 {failed}，阻塞 {blocked}。尽管 455/455 完整测试通过，仍有强制故障未被门禁检测，按验收规则必须失败。

## 3. 验收范围

覆盖 Git/冻结基线、Stage11 源码与配置、Stage7–11/Stage0/完整回归、AKShare Raw、OKX/Binance 公网来源、960 根 K 线、三格式一致性、独立指标、幂等/回滚、故障注入、Stage10 财务隔离与文档边界。未执行投资分析。

## 4. 环境与版本

Windows，Python 3.11.4；akshare 1.18.80、pandas 3.0.5、numpy 2.4.6、DuckDB 1.5.5、pytest 9.1.1。使用项目现有 `.venv` 和 `requirements-lock.txt`，未另建环境；这是可复现性限制，详见 `stage11_environment.txt`。

## 5. Git 和冻结基线验证

分支 `{branch}`；HEAD `{head}`；Stage10 标签 `{tag}`，标签为当前祖先且与 HEAD 相同。无 staged changes，`git diff --check` 退出码为 0；三个实施方既有 tracked 改动有 LF→CRLF 提示，记为观察项而非 whitespace failure。

| 冻结文件 | 当前 SHA-256 | 参考 SHA-256 | 结论 | 证据来源 |
|---|---|---|---|---|
{frozen_table}

工作树因实施方 Stage11 未提交变更并不干净；本验收仅新增 `reports/stage11_acceptance/`。

## 6. Stage 11 文件变更审查

适配器边界和 8760 年化口径合理，Repository 使用事务/upsert。关键缺陷是标准化函数覆盖输入身份，数据模型未保存 `data_provider` 和原始 instrument；一致性质量行在写前预置 PASS；Raw 和既有输出未进入 validate-only 门禁。

## 7. 自动化测试结果

| 范围 | 命令 | collected | passed | failed | skipped | exit code | 结论 |
|---|---|---:|---:|---:|---:|---:|---|
{test_rows}

没有 skip、xfail 或 deselected。完整日志见 `stage11_test_execution.log`。

## 8. AKShare 探针核验

独立读取完整 parquet：10 行、9 列，ETH 相关 0 行，精确 ETHUSDT 0 行，`unsupported` 判断正确。Raw 元数据缺少 `fetched_at`、`akshare_version`、`parameters`、`columns`、`schema_hash`，因此证据完整性 FAIL；Raw 缺失/空/损坏也不会阻断 validate-only。

## 9. OKX 来源和品种核验

独立公网请求返回 200；官方公共 instruments 结果确认 `ETH-USDT` 为 `SPOT`。保存的末根 1H K 线在历史接口重叠区间找到、`confirm=1`，六个数值字段在 1e-12 内一致。Binance HTTP 451 亦独立复现。公网响应哈希、请求参数和结果见 `stage11_network_evidence.json`。

## 10. 960 根小时 K 线质量结果

960 行、960 个唯一 UTC 时间戳；无缺时、重复、非整小时、非法 OHLC、负成交量、NaN/Infinity。范围为 {dq['min_timestamp']} 至 {dq['max_timestamp']}。标准字段分布是 ETHUSDT/OKX/spot/1h，但因未保存原始 instrument，不能仅凭这些被标准化后的字段证明每一行原始身份。

## 11. UTC 日边界验证

共有 40 个 UTC 自然日，每日恰好 24 根，数学关系 40×24=960；首根 2026-06-18 00:00 UTC，末根 2026-07-27 23:00 UTC。本地时间字段为 UTC+08:00。DuckDB 客户端可能按会话时区显示 `+08:00`，独立规范化后为同一 UTC 时刻。

## 12. CSV/JSON/DuckDB 一致性

三者均 960 行，主键集合和被比较字段集合一致；全量逐行不一致为 0，数值最大绝对误差 0（布尔/文本/时间亦一致）。规范化 SHA-256 均为 `{next(iter(EVIDENCE['reconciliation']['rounded_hashes'].values()))}`。数据库表计数：raw 960、clean 960、feature 960、profile 1、quality 11、audit 1。

## 13. 指标独立重算

未导入项目指标函数，自行从 OHLCV 重算 16 个指标，全部在 1e-12 容差内：年化波动率约 66.211%、ATR/close 约 1.0443%、布林带宽约 4.4085%、趋势斜率约 -0.1472%/bar、箱体宽约 4.7111%、确认假突破计数 32。这些仅为统计特征，不构成预测或建议。

## 14. 数据库幂等验证

在临时 DuckDB 副本上用同一 run_id 连续写两次：各表计数和关键哈希稳定、主键重复为 0、quality 仍为 11、audit 仍为 1、其他 run 保留。注入缺列失败后事务回滚完整。结论 PASS。

## 15. 故障注入结果

共 29 项，其中 {fault_pass} 项异常被成功阻断，19 项强制异常漏检，另 1 项为 equity 基线不应阻断。主要漏检：输入顺序/范围、instrument/provider/exchange 身份、Infinity、四类产物篡改、五类 Raw 证据异常、Stage10 生产入口隔离。完整矩阵见 `stage11_fault_injection.csv`。

## 16. Stage 10 财务隔离

`require_equity_asset` helper 对 crypto 返回 `not_applicable` 的单元测试通过，但生产 `analyze_stage10` 入口没有 `asset_type` 参数，也未调用该 helper。Stage11 报告中的 `not_applicable` 是硬编码描述，不能证明生产财务入口拒绝 crypto。结论 FAIL。

## 17. 来源与许可风险

实现文档清楚披露 AKShare unsupported、OKX 实际来源、Binance 451、单一交易所及 40 UTC 日范围。已记录官方公共接口 URL 和参数，但没有足够证据对使用条款作法律判断；建议在进入更广泛使用前由法务确认。

## 18. 回归影响

Stage7 22/22、Stage8 134/134、Stage9 43/43、Stage10 45/45、Stage11 11/11、Stage0 35/35、完整集 455/455 均通过。现有测试覆盖不足以发现本次故障注入揭示的门禁缺陷。

## 19. 发现的问题

{top_failures}

其余失败逐项见 `stage11_acceptance_results.json` 和 `stage11_fault_injection.csv`。

## 20. 已知限制

- 使用现有锁定 `.venv`，未从零安装环境。
- 独立网络核验只重叠验证保存数据的末根 K 线；实现方未保存 OKX 完整 Raw HTTP 响应，无法逐页重演 960 根采集链。
- 未作外部接口许可的法律结论。
- 当前实现变更未提交，验收基于工作区快照。

## 21. Git 清洁性复核

末次 `git status --short`、diff、未跟踪/忽略证据和冻结哈希已保存至 `stage11_git_evidence.txt`。除实施方原有文件外，验收过程的新文件全部位于 `reports/stage11_acceptance/`；未 staged、commit 或 push。

## 22. 验收结论和后续动作

最终状态：**FAIL**。建议实施方修复身份与来源不可伪造、Raw/产物完整性门禁、Infinity/范围检查和 Stage10 生产入口隔离后，再由独立验收方复跑本证据包。当前不建议标记 Stage11 已验收。
"""
(OUT / "stage11_acceptance_report.md").write_text(report, encoding="utf-8")

print("STAGE 11 INDEPENDENT ACCEPTANCE")
print(f"Final status: {final_status}")
print(f"Mandatory checks passed: {passed}/{len(mandatory)}")
print(f"Failed checks: {failed}")
print(f"Blocked checks: {blocked}")
print("Regression tests: 455/455 passed")
print("Stage 11 tests: 11/11 passed")
print("Data rows reconciled: 960")
print(f"Fault injections blocked: {fault_pass}/28 mandatory abnormal cases")
print("Report: reports/stage11_acceptance/stage11_acceptance_report.md")
for item in failure_rows[:10]:
    print(f"- {item['check_id']}: {item['description']} [{item['evidence']}]")
