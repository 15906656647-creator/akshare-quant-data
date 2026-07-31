# Stage 2 Independent Acceptance Report

> Acceptance date: 2026-07-28 14:33 UTC+8
> Baseline date: 2026-07-27
> Reviewer: Independent Codex acceptance task

## 1. Acceptance Verdict

| Dimension | Result |
|---|---|
| **Overall status** | **BLOCKED** |
| Engineering implementation | PASS |
| Live interface verification | BLOCKED |
| Can enter Stage 3 | **No** |

## 2. Stage 1 Pre-Gate Results

| Check | Command | Exit Code | Result |
|---|---|---|---|
| Python 3.11.4 64-bit in .venv | `python -c "import sys, struct"` | 0 | PASS |
| pip check | `python -m pip check` | 0 | PASS |
| pytest (all) | `python -m pytest -q` | 0 | 86 passed |
| show-config | `python run_pipeline.py show-config --as-of-date 2026-07-27` | 0 | 16 stocks + ETHUSDT |
| doctor | `python run_pipeline.py doctor --as-of-date 2026-07-27 --output ...` | 0 | PASS, 14/14 pkgs |

## 3. Stage 0 Hash Verification

| File | SHA-256 | Match |
|---|---|---|
| `config/universe.yml` | `0B6F61...CCEC65` | MATCH |
| `config/metric_definition.yml` | `13F941...5C00C4` | MATCH |
| `docs/stage0_scope.md` | `18EEEC...761615` | MATCH |

All three files match the Stage 1/Stage 2 recorded hashes.

## 4. Stage 2 File Completeness

| File | Size (bytes) | Valid |
|---|---|---|
| `config/interfaces.yml` | 5,074 | Yes |
| `src/akshare_data_test/adapters/akshare_probe.py` | 12,666 | Yes |
| `src/akshare_data_test/smoke.py` | 6,733 | Yes |
| `src/akshare_data_test/cli.py` | 7,523 | Yes |
| `tests/test_stage2_interface_config.py` | 6,049 | Yes |
| `docs/stage2_interface_smoke.md` | 6,344 | Yes |
| `reports/interface_smoke_test.csv` | 6,983 | Yes |
| `reports/interface_smoke_test_summary.md` | 1,068 | Yes |
| `reports/evidence/stage2/<run_id>/manifest.json` | 257 | Yes |

All required files present and non-empty. No sensitive data (cookies, tokens, proxy) found.

## 5. interfaces.yml Validation

- 12 probes defined, all 12 expected IDs present
- All 12 interface_name mappings match expected AKShare functions
- stock_daily_qfq uses `adjust=qfq`, stock_daily_raw uses `adjust=""` — correct
- Full-market probes identified: stock_spot, limit_up_pool, limit_down_pool

## 6. AKShare Function Existence & Signatures (offline verification)

| Function | Exists | Signature |
|---|---|---|
| `stock_zh_a_hist` | Yes | `(symbol, period, start_date, end_date, adjust, timeout) -> DataFrame` |
| `stock_zh_a_spot_em` | Yes | `() -> DataFrame` |
| `stock_financial_abstract` | Yes | `(symbol) -> DataFrame` |
| `stock_financial_analysis_indicator` | Yes | `(symbol, start_year) -> DataFrame` |
| `stock_balance_sheet_by_report_em` | Yes | `(symbol) -> DataFrame` |
| `stock_profit_sheet_by_report_em` | Yes | `(symbol) -> DataFrame` |
| `stock_cash_flow_sheet_by_report_em` | Yes | `(symbol) -> DataFrame` |
| `stock_individual_fund_flow` | Yes | `(stock, market) -> DataFrame` |
| `stock_zt_pool_em` | Yes | `(date) -> DataFrame` |
| `stock_zt_pool_dtgc_em` | Yes | `(date) -> DataFrame` |
| `crypto_js_spot` | Yes | `() -> DataFrame` |

**Note**: 12 probes use 11 unique AKShare functions (stock_zh_a_hist is used twice for qfq and raw).
The Stage 2 report's phrasing "12 functions all exist" is slightly imprecise but does not invalidate the findings.

## 7. Offline Test Results

```
pytest -q: 86 passed in 12.82s (0 failed, 0 skipped)
```

tests/test_stage2_interface_config.py: 12/12 passed (config parsing, probe count, ID uniqueness, required keys, scope values, ProbeResult model, schema hash stability, import-no-network, function_missing status).

## 8. Smoke Test Results

### Original run (run_id: c4d1a7b9-02ae-4f68-bec9-6e815ef1edb5)

### Independent re-run (run_id: 0974e67e-776d-4d1e-b398-b9359daf645e)

Both runs identical:

| probe_id | status | error_type | rows | cols |
|---|---|---|---|---|
| stock_daily_qfq | failed | connection_error | - | - |
| stock_daily_raw | failed | connection_error | - | - |
| stock_spot | failed | connection_error | - | - |
| financial_abstract | failed | connection_error | - | - |
| financial_indicator | failed | connection_error | - | - |
| balance_sheet_report | failed | connection_error | - | - |
| profit_sheet_report | failed | connection_error | - | - |
| cashflow_sheet_report | failed | connection_error | - | - |
| individual_fund_flow | failed | connection_error | - | - |
| limit_up_pool | skipped | dependency_failure | - | - |
| limit_down_pool | skipped | dependency_failure | - | - |
| crypto_spot | failed | connection_error | - | - |

## 9. Network Failure Root Cause Analysis

All 10 network failures are HTTPSConnectionPool errors with `Max retries exceeded`.
Affected hosts:

| Host | Probes |
|---|---|
| `push2his.eastmoney.com:443` | stock_daily_qfq, stock_daily_raw, individual_fund_flow |
| `82.push2.eastmoney.com:443` | stock_spot |
| `quotes.sina.cn:443` | financial_abstract |
| `money.finance.sina.com.cn:443` | financial_indicator |
| `emweb.securities.eastmoney.com:443` | balance_sheet_report, profit_sheet_report, cashflow_sheet_report |
| `datacenter-api.jin10.com:443` | crypto_spot |

Classification is correct: all are connection-level failures before HTTP response.
No DNS errors, no timeout, no SSL errors, no parameter errors, no parse errors.
The probe adapter's built-in retry (1 retry, 2s delay) was exhausted identically.
The root cause is consistent network-level blocking, not code or configuration defects.

## 10. Skip Logic Audit

limit_up_pool and limit_down_pool were skipped with `dependency_failure` because:
1. Their `parameter_policy.date` is `resolve_pool_date`
2. The probe adapter requires `current_pool_date` to resolve this; if None, it returns `skipped`
3. `current_pool_date` is resolved from stock_daily_qfq's coverage_end
4. stock_daily_qfq failed → pool_date=None → limit pools skipped

**Assessment**: This dependency chain is documented in the Stage 2 prompt. However,
both `stock_zt_pool_em` and `stock_zt_pool_dtgc_em` have default date parameters
(`date='20241008'` and `date='20241011'` respectively). When network is unavailable,
these probes could have been attempted independently rather than skipped.
This is recorded as a warning, not a blocking failure.

## 11. CSV Validation

- 12 rows, 12 unique probe IDs matching the expected set: PASS
- Single run_id throughout: PASS
- Status counts: 10 failed, 2 skipped: PASS
- Error types: all 10 connection_error: PASS
- Error messages are truncated (~200 chars) and desensitized: PASS

## 12. Manifest & Evidence

- manifest.json exists with correct run_id and probe_count=12: PASS
- Status counts in manifest match CSV: PASS
- No dead links to deleted temp files: PASS
- No raw market data or batch captures: PASS

## 13. Stage Boundary Check

| Directory | Content | Status |
|---|---|---|
| `data/raw/` | .gitkeep only | CLEAN |
| `data/clean/` | .gitkeep only | CLEAN |
| `data/feature/` | .gitkeep only | CLEAN |
| `data/export/` | .gitkeep only | CLEAN |
| `database/` | .gitkeep only | CLEAN |

No batch captures of 16 stocks, no formal Raw/Clean/Feature data, no business database.

## 14. ETHUSDT Assessment

- `crypto_js_spot()` exists in AKShare 1.18.80
- Actual probe failed with connection_error (jin10.com)
- No ETHUSDT pair substitution or renaming detected
- **Conclusion: UNVERIFIED** — function exists but network unreachable

## 15. Security Check

- No hardcoded credentials, API keys, cookies, tokens, or proxy addresses found
- No personal absolute paths in source files
- CSV error messages desensitized (truncated to ~200 chars)
- Sensitive check patterns: PASS

## 16. Documentation Consistency

| Claim in Stage 2 report | Verified? |
|---|---|
| Python 3.11.4 64-bit | Yes |
| AKShare 1.18.80 | Yes |
| .venv isolation | Yes |
| pip check exit 0 | Yes |
| pytest 86 passed | Yes (86, not just claim) |
| 12 probes defined | Yes |
| 11 unique AKShare functions exist | Yes (report said "12" — minor imprecision) |
| 10 failed, 2 skipped | Yes |
| Failures are connection_error | Yes |
| Retry once | Yes (probe adapter retries once) |
| No stage violations | Yes |
| No formal data created | Yes |
| ETHUSDT unverified | Yes (correctly not claimed as supported or unsupported) |

## 17. Failures

None blocking. Engineering implementation passes all checks.

## 18. Warnings

1. Stage 2 report says "12 functions all exist" — should be "12 probes correspond to 11 unique functions"
2. limit_up_pool/limit_down_pool skipped due to dependency on stock_daily_qfq, but both functions have default date parameters and could attempt independent calls
3. `sqlalchemy` pattern found in source (from Stage 1 — not a Stage 3+ leak, it's a pre-existing project dependency)

## 19. Minimal Next Step

**Do not enter Stage 3.** The engineering implementation is sound and can be retained.
Re-run the original smoke-test in an environment with network access to AKShare upstream:

```bash
python run_pipeline.py smoke-test --as-of-date 2026-07-27 --sample-symbol 600763 --output reports/interface_smoke_test.csv --evidence-dir reports/evidence/stage2 --max-sample-rows 20
```

When core probes (stock_daily_qfq, stock_daily_raw, stock_spot) all return `success` and
at least one financial probe returns `success`, re-run this acceptance to authorize Stage 3.

## 20. Acceptance Products

| Product | Path |
|---|---|
| Acceptance report (this file) | `docs/stage2_acceptance.md` |
| Acceptance JSON | `reports/stage2_acceptance_report.json` |
| Independent re-run CSV | `reports/stage2_acceptance_smoke.csv` |
| Independent re-run evidence | `reports/evidence/stage2_acceptance/0974e67e-.../` |
| Doctor output | `reports/stage2_acceptance_doctor.json` |

## 21. Final Entry Declaration

> 阶段2工程实现可以保留，但真实接口能力尚未完成验证，当前禁止进入阶段3。请在可访问AKShare上游数据源的环境中重新运行阶段2冒烟测试，并再次验收。

> Stage 2 engineering implementation can be retained, but live interface
> capability has not been verified — entering Stage 3 is currently prohibited.
> Please re-run the Stage 2 smoke test in an environment with access to
> AKShare upstream data sources, and re-verify.
