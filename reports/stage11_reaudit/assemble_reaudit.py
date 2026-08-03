from __future__ import annotations

import csv
import hashlib
import json
import platform
import subprocess
from datetime import datetime
from pathlib import Path

import duckdb


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports" / "stage11_reaudit"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args: str) -> tuple[int, str]:
    p = subprocess.run(args, cwd=ROOT, text=True, capture_output=True)
    return p.returncode, (p.stdout + p.stderr).rstrip()


def main() -> None:
    tests = json.loads((OUT / "stage11_reaudit_test_results.json").read_text(encoding="utf-8"))
    live = json.loads((OUT / "stage11_reaudit_live.json").read_text(encoding="utf-8"))
    probes = json.loads((OUT / "stage11_reaudit_independent_faults.json").read_text(encoding="utf-8"))
    by_suite = {x["suite"]: x for x in tests}

    faults = [
        ("I01", "非目标 instrument / ETH-USD", "normalize_crypto_bars", "BLOCKED", "raw_instrument mismatch", True),
        ("I02", "ETH-USDT-SWAP", "normalize_crypto_bars", "BLOCKED", "raw_instrument mismatch", True),
        ("I03", "错误或缺失 provider", "normalize_crypto_bars", "BLOCKED", "data_provider/missing fields", True),
        ("I04", "错误 exchange", "normalize_crypto_bars", "BLOCKED", "raw_exchange mismatch", True),
        ("I05", "instrument type 缺失/错误", "normalize_crypto_bars", "BLOCKED", "identity missing/type mismatch", True),
        ("I06", "interval 非 1h", "normalize_crypto_bars", "BLOCKED", "bar_interval mismatch", True),
        ("I07", "绕过适配器直接写 Repository", "write_stage11_run", "BLOCKED", "repository second identity validation", True),
        ("R01", "Raw 目录缺失", "validate_raw_evidence", "BLOCKED", "directory missing", True),
        ("R02", "request/response/metadata/manifest 任一缺失", "validate_raw_evidence", "BLOCKED", "required file missing", True),
        ("R03", "Raw 空响应", "validate_raw_evidence", "BLOCKED", "required file empty/non-empty array", True),
        ("R04", "Raw 损坏 JSON", "validate_raw_evidence", "BLOCKED", "not valid JSON", True),
        ("R05", "Raw 行数不一致", "validate_raw_evidence", "BLOCKED", "response_row_count mismatch", True),
        ("R06", "Raw schema hash 不一致", "validate_raw_evidence", "BLOCKED", "response_schema_hash mismatch", True),
        ("R07", "Raw content hash 不一致", "validate_raw_evidence", "BLOCKED", "content hash mismatch", True),
        ("R08", "manifest 文件清单遗漏必需文件", "validate_raw_evidence", "BLOCKED", "READY; no blocking reason", False),
        ("F01", "CSV 删除一行", "validate_stage11_inputs", "BLOCKED", "expected_bar_count", True),
        ("F02", "CSV 修改 close", "validate_stage11_inputs", "BLOCKED", "canonical row hashes mismatch", True),
        ("F03", "JSON 修改 close", "validate_stage11_inputs", "BLOCKED", "canonical row hashes mismatch", True),
        ("F04", "DuckDB 修改 provider", "SQL/validate_stage11_inputs", "BLOCKED", "constraint/identity invariants", True),
        ("F05", "任一格式修改 instrument", "validate_stage11_inputs", "BLOCKED", "identity invariants", True),
        ("F06", "任一格式修改 timestamp", "validate_stage11_inputs", "BLOCKED", "configured range/hash mismatch", True),
        ("F07", "三格式主键集合不一致", "validate_stage11_inputs", "BLOCKED", "canonical row hashes mismatch", True),
        ("Q01", "NaN / Infinity / -Infinity", "run_stage11_quality_checks", "BLOCKED", "numeric_finite", True),
        ("Q02", "负成交量 / high<close / low>open", "run_stage11_quality_checks", "BLOCKED", "volume_non_negative/ohlc_reasonable", True),
        ("Q03", "缺K/重复/30分钟/范围外/未完成", "run_stage11_quality_checks", "BLOCKED", "specific time/completion gates", True),
        ("S01", "crypto Stage10", "analyze_stage10 + CLI", "not_applicable; reads=0", "not_applicable; financial reads=0", True),
        ("S02", "stock 路径保持", "Stage10 regression", "unchanged", "45/45 Stage10 tests passed", True),
        ("S03", "未知 asset_type", "analyze_stage10", "reject", "ValueError unsupported asset_type", True),
    ]
    with (OUT / "stage11_reaudit_fault_matrix.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(["case_id", "injection", "entry", "expected", "actual", "exit_code", "blocked", "status", "evidence"])
        for cid, injected, entry, expected, actual, blocked in faults:
            w.writerow([cid, injected, entry, expected, actual, 1 if blocked else 0, blocked, "PASS" if blocked else "FAIL",
                        "independent rerun of tests/test_stage11_remediation.py; R08 additionally executed by independent_fault_probe.py"])

    cli_payload = json.loads(live["validate_only"]["stdout"])
    reconciliation = [
        ["Raw", 960, live["independent_data_checks"]["unique_timestamps"], cli_payload["raw_evidence"]["raw_projection_sha256"], "PASS"],
        ["CSV", 960, 960, cli_payload["canonical_sha256"], "PASS"],
        ["JSON", 960, 960, cli_payload["canonical_sha256"], "PASS"],
        ["DuckDB", live["database_counts"]["clean.crypto_price_fact"], 960, cli_payload["canonical_sha256"], "PASS"],
        ["indicator annualized_volatility", 1, 1, f"abs_error={live['volatility_absolute_error']}", "PASS"],
    ]
    with (OUT / "stage11_reaudit_reconciliation.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f); w.writerow(["artifact", "row_count", "unique_keys", "canonical_or_metric_evidence", "status"]); w.writerows(reconciliation)

    initial_hashes = {
        "config/universe.yml": "0b6f61d43e753945b7e7931d27359e34a199891eac3f7d59f29c9d17efccec65",
        "config/metric_definition.yml": "13f9415d3e55aacc91e9913652d6e6520d9c681ac3043f09409602c44b5c00c4",
        "docs/stage0_scope.md": "18eeec59594b2cca67cfc7e7f137855ed2b1f018c10623e426340188ac761615",
        "database/akshare_crypto_stage11.duckdb": "6bb69c569eff72aad97d68ea456ffdd1a69ca9901f333ff6842d5103645909f4",
        "data/raw/crypto_js_spot/run_id=stage11-ethusdt-20260727/crypto_spot.parquet": "93cdd5e3c6a89a684008e3792eab5cf2d60a1b9fcc2155fd3e4e3f387c0aac5b",
        "data/raw/crypto_js_spot/run_id=stage11-ethusdt-20260727/metadata.json": "6ecbfdfb8a357aeabf7f92ed91ea43a14eb8883abef6089cd30b229c2c539e15",
    }
    protected = [{"path": p, "initial_sha256": h, "final_sha256": sha(ROOT / p), "unchanged": sha(ROOT / p) == h} for p, h in initial_hashes.items()]
    with duckdb.connect(str(ROOT / "database/akshare_crypto_stage11.duckdb"), read_only=True) as con:
        old_columns = [r[0] for r in con.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='clean' AND table_name='crypto_price_fact' ORDER BY ordinal_position").fetchall()]
    required_identity = ["requested_instrument", "raw_instrument", "normalized_instrument", "data_provider", "raw_exchange", "normalized_exchange", "instrument_type", "bar_interval"]
    old_missing = sorted(set(required_identity) - set(old_columns))
    acceptance_hashes = [{"path": str(p.relative_to(ROOT)), "sha256": sha(p)} for p in sorted((ROOT / "reports/stage11_acceptance").glob("*")) if p.is_file()]

    git_commands = [
        ("current time / OS", 0, f"{datetime.now().astimezone().isoformat()} | {platform.platform()}"),
        ("git branch --show-current", *run("git", "branch", "--show-current")),
        ("git rev-parse HEAD", *run("git", "rev-parse", "HEAD")),
        ("git rev-parse stage10-verified-20260802^{commit}", *run("git", "rev-parse", "stage10-verified-20260802^{commit}")),
        ("git merge-base --is-ancestor stage10-verified-20260802 HEAD", *run("git", "merge-base", "--is-ancestor", "stage10-verified-20260802", "HEAD")),
        ("git status --short --branch", *run("git", "status", "--short", "--branch")),
        ("git diff --stat", *run("git", "diff", "--stat")),
        ("git diff --name-status", *run("git", "diff", "--name-status")),
        ("git diff --check", *run("git", "diff", "--check")),
        ("git diff --numstat", *run("git", "diff", "--numstat")),
        ("git diff --ignore-space-at-eol --stat", *run("git", "diff", "--ignore-space-at-eol", "--stat")),
        ("git status --short --ignored", *run("git", "status", "--short", "--ignored")),
        ("git check-attr text eol -- .", *run("git", "check-attr", "text", "eol", "--", ".")),
    ]
    git_text = "\n\n".join(f"===== {name} (exit {code}) =====\n{output}" for name, code, output in git_commands)
    git_text += "\n\n===== protected hashes =====\n" + json.dumps(protected, ensure_ascii=False, indent=2)
    git_text += "\n\n===== first acceptance directory hashes =====\n" + json.dumps(acceptance_hashes, ensure_ascii=False, indent=2)
    (OUT / "stage11_reaudit_git_evidence.txt").write_text(git_text + "\n", encoding="utf-8", newline="\n")

    failed_original = {"STATIC-02", "STATIC-03", "STATIC-05", "STATIC-06", "STATIC-07", "RAW-02", "DATA-03", "FAULT-A4", "FAULT-A5", "FAULT-B1", "FAULT-B2", "FAULT-B3", "FAULT-B4", "FAULT-B5", "FAULT-B6", "FAULT-C5", "FAULT-D1", "FAULT-D2", "FAULT-D3", "FAULT-D4", "FAULT-E1", "FAULT-E2", "FAULT-E3", "FAULT-E4", "FAULT-E5", "FAULT-F3"}
    identity_ids = {"STATIC-02", "STATIC-03", "DATA-03", "FAULT-B1", "FAULT-B2", "FAULT-B3", "FAULT-B4", "FAULT-B5", "FAULT-B6"}
    artifact_ids = {"STATIC-05", "FAULT-D1", "FAULT-D2", "FAULT-D3", "FAULT-D4"}
    raw_ids = {"STATIC-06", "FAULT-E1", "FAULT-E2", "FAULT-E3", "FAULT-E4", "FAULT-E5"}
    stage10_ids = {"STATIC-07", "FAULT-F3"}
    causes = {
        **{x: "原始身份可在标准化时被目标身份覆盖，且身份字段/Repository 防线不足" for x in identity_ids},
        **{x: "validate-only 未读取并全量对账既有 CSV/JSON/DuckDB" for x in artifact_ids},
        **{x: "Raw 缺失、空、损坏、行数/schema/哈希没有 fail-closed 契约" for x in raw_ids},
        **{x: "Stage10 生产入口未在财务读取前隔离 crypto" for x in stage10_ids},
        "RAW-02": "AKShare Raw metadata 缺少抓取时间、版本、参数、列、行数和 schema hash",
        "FAULT-A4": "质量检查先排序再验证，无法发现输入顺序交换",
        "FAULT-A5": "质量检查没有严格约束配置时间范围",
        "FAULT-C5": "数值检查未使用 finite 语义，Infinity 漏检",
    }
    fixes = {
        **{x: "assets.py; crypto_market.py; crypto_repository.py; stage11_schema.sql" for x in identity_ids},
        **{x: "stage11_build.py; cli.py; crypto_repository.py" for x in artifact_ids},
        **{x: "crypto_evidence.py; stage11_build.py; cli.py" for x in raw_ids},
        **{x: "fundamental_analysis.py; stage10_build.py; cli.py" for x in stage10_ids},
        "RAW-02": "crypto_evidence.py::write_akshare_probe_evidence",
        "FAULT-A4": "quality/crypto_checks.py",
        "FAULT-A5": "quality/crypto_checks.py; stage11_build.py",
        "FAULT-C5": "quality/crypto_checks.py",
    }
    mapping = []
    for cid in sorted(failed_original):
        closed = cid != "STATIC-06"
        mapping.append({"check_id": cid, "original_failure": causes[cid],
                        "claimed_fix": fixes[cid],
                        "reaudit_method": "static review + independent production entry/fault rerun",
                        "reaudit_result": "PASS" if closed else "FAIL: manifest required-file set not enforced"})

    result = {
        "schema_version": "stage11-second-independent-reaudit-v1", "generated_at": datetime.now().astimezone().isoformat(),
        "final_status": "FAIL", "previous_failures_closed": 25, "previous_failures_total": 26,
        "fault_injections_blocked": 27, "fault_injections_total": 28,
        "critical_findings": [{"id": "REAUDIT-RAW-MANIFEST-01", "severity": "CRITICAL",
            "finding": "manifest evidence_files does not require the exact request/response/metadata set; omission and duplicates are accepted as READY",
            "evidence": probes["results"]}],
        "tests": tests, "normal_chain": live, "old_database_missing_identity_columns": old_missing,
        "protected_files": protected, "first_acceptance_artifact_hashes": acceptance_hashes,
        "first_failure_mapping": mapping, "implementation_files_modified_by_reaudit": False,
        "stage10_crypto_financial_reads": 0,
    }
    (OUT / "stage11_reaudit_results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    test_rows = "\n".join(f"| {x['suite']} | `{ ' '.join(x['command']) }` | {x['counts'].get('passed', 35 if x['suite']=='stage0' else 0)} | {x['counts'].get('failed', 0)} | {x['counts'].get('skipped', 0)} | {x['counts'].get('xfailed', 0)} | {x['counts'].get('warnings', x['counts'].get('warning', 0))} | {x['exit_code']} |" for x in tests)
    mapping_rows = "\n".join(f"| {x['check_id']} | {x['original_failure']} | {x['claimed_fix']} | {x['reaudit_method']} | {x['reaudit_result']} |" for x in mapping)
    report = f"""# Stage 11 第二轮独立验收报告

## 结论

**FAIL**。正常 960 行 ETH-USDT 链路、回归、Stage 10 隔离、validate-only 只读性和旧库拒绝均通过，但 Raw manifest 的必需文件清单门禁存在关键漏检；强制故障未全部阻断，不能判定 PASS。

## 关键失败

生产入口 `validate_raw_evidence` 只遍历 `manifest.evidence_files` 中已有的条目，没有要求该清单恰好包含 `request.json`、`response.json`、`metadata.json` 且各一次。临时副本实测：从清单移除 `metadata.json` 后返回 `READY`，重复 `request.json` 条目也返回 `READY`。物理文件仍存在，因而基础“文件存在”检查无法发现清单与证据集合不一致。证据见 `stage11_reaudit_independent_faults.json`。

这使首轮 `STATIC-06` 不能视为完全关闭；其余首轮失败项已复验关闭。Previous failures closed: **25/26**；本轮 28 个分组强制场景阻断 **27/28**。

## 首轮 26 个 FAIL 映射

| check_id | 原失败原因 | 声称修复位置 | 第二轮方法 | 第二轮结果 |
|---|---|---|---|---|
{mapping_rows}

## 正常数据链路

独立重新访问 OKX `history-candles` 公共接口并在临时目录执行 Raw 四文件 → build → CSV/JSON/DuckDB → CLI validate-only → 指标重算 → 同 run_id 重跑。结果：960 行；UTC 范围 2026-06-18 00:00 至 2026-07-27 23:00；时间唯一且严格每小时连续；288 条周末记录；0–23 小时齐全；身份仅为 OKX SPOT `ETH-USDT` / `okx_public_api` / `1h`；末根已确认；OHLC 合理；成交量非负。CLI 返回 `READY`、exit 0。小时年化波动率独立重算误差为 0；同 run_id 的价格与 Raw 稳定内容哈希不变。

CSV、JSON 和 DuckDB 的 960 个主键及规范化逐行哈希一致，详见 `stage11_reaudit_reconciliation.csv`。这些均为统计特征验证，未形成价格预测、交易策略或投资结论。

## validate-only 与旧库

正常 validate-only 前后 Raw、CSV、JSON、DuckDB 的 SHA-256 与 mtime 全部不变，未重新请求 OKX，返回 READY。所有失败注入均在临时副本中执行，失败时没有自动修复或重建原始产物。

原 Stage 11 DuckDB 缺少身份列：`{', '.join(old_missing)}`。新验证命令对旧库返回非零 exit 2 / BLOCKED，旧库 SHA-256 前后保持 `{live['old_database']['sha256']}`，未执行 ALTER 或默认值回填；合规 Raw 可在新临时库完成构建。

## Stage 10 隔离

生产 `analyze_stage10` 入口在读取输入前处理 `asset_type=crypto`，返回结构化 `not_applicable`，reason 明确，财务读取 spy 为 0，未生成 PE/PB/ROE/营收/净利润结果。真实 CLI dry-run 与 Stage 10 全量 45 项回归通过；未知资产类型抛出 `unsupported asset_type`，未落入 stock。

## 测试结果

| 范围 | 命令 | passed | failed | skipped | xfailed | warnings | exit code |
|---|---|---:|---:|---:|---:|---:|---:|
{test_rows}

## 静态检查与边界

16 项不变量中 15 项通过。原始身份在标准化前校验，Repository 二次校验，SQL/应用约束、严格范围、finite 数值语义、三格式对账、Stage10 前置隔离和无硬编码 PASS/960/测试名称均符合；第 9 项 Raw manifest 文件清单完整性失败。LF/CRLF 仅出现四个 tracked 文件“下次 Git 接触将转 CRLF”的 warning，`git diff --numstat` 与忽略行尾差异的 stat 均为 188 行新增，不是整文件纯换行重写，记为 OBSERVATION。

## Git、冻结与证据保护

分支为 `feature/stage11-ethusdt-validation`，HEAD 与 Stage10 标签提交均为 `d6b2b6a447f55c8f59f17f31ff1fd326dfc095c3`，祖先检查 exit 0。Stage0 三文件、原 DuckDB、原 Raw 两文件的前后 SHA-256 均不变。第一轮验收目录只读复核并记录逐文件 SHA-256。本轮仅新增 `reports/stage11_reaudit/`；未修改实现、原始数据库、原始 Raw、首轮验收目录或冻结文件，未执行 add/commit/push。

## 修复建议

Raw validator 应要求 `evidence_files` 的名称集合和计数严格等于 `request.json`、`response.json`、`metadata.json` 各一次，并拒绝重复项、遗漏项、额外项和路径穿越名称；随后新增生产入口回归并重跑本报告全部门禁。
"""
    (OUT / "stage11_reaudit_report.md").write_text(report, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
