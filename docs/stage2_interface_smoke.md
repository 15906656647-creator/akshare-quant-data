# Stage 2: Interface Inventory and Smoke Test

> Document date: 2026-07-28
> Baseline date: 2026-07-27
> Corresponding engineering stage: Stage 2 (Stage 3 in operator manual)

## 1. Stage Objectives

Validate the actual availability, function signatures, parameter requirements,
return fields, data types, time coverage, empty results, and error types for
12 candidate AKShare interfaces using a single representative stock (600763)
and a single full-market call, forming the factual basis for subsequent
capture development.

## 2. Stage 1 Pre-Gate Results

| Check | Result |
|---|---|
| Python version | 3.11.4 (64-bit CPython) |
| `pip check` | Exit 0, no broken requirements |
| `pytest` | 74 passed (offline) |
| `show-config` | Exit 0, 16 stocks + ETHUSDT displayed |
| `doctor` | Exit 0, PASS, 14/14 packages, 9/9 config, 20/20 fs |
| Stage 0 hash (universe.yml) | `0B6F61...CCEC65` - unchanged |
| Stage 0 hash (metric_definition.yml) | `13F941...5C00C4` - unchanged |
| Stage 0 hash (stage0_scope.md) | `18EEEC...761615` - unchanged |

**Pre-gate verdict: PASS**

## 3. Implementation

### 3.1 Files Created or Modified

| File | Action | Lines |
|---|---|---|
| `config/interfaces.yml` | Created | 206 |
| `src/akshare_data_test/adapters/akshare_probe.py` | Created | 302 |
| `src/akshare_data_test/smoke.py` | Created | 172 |
| `src/akshare_data_test/cli.py` | Modified | 168 |
| `tests/test_stage2_interface_config.py` | Created | 120+ |

### 3.2 Architecture

- **akshare_probe.py**: Minimal probe adapter. Lazily imports akshare, checks function
  existence, reads signatures via `inspect.signature`, calls functions with
  explicitly resolved parameters, returns `ProbeResult` dataclass. No business
  cleaning, no database, no network at import-time.
- **smoke.py**: Sequential orchestration. Loads probe config from
  `config/interfaces.yml`, calls probes one at a time, enforces single-call
  for full-market probes, resolves pool_date from stock_daily_qfq result,
  writes CSV output, saves evidence (schema JSONs, manifest.json).
- **CLI**: Added `smoke-test` subcommand with `--as-of-date`, `--sample-symbol`,
  `--pool-date`, `--output`, `--evidence-dir`, `--max-sample-rows`, `--only`,
  `--strict`, `--log-level`.

## 4. Execution

### 4.1 Command

```
python run_pipeline.py smoke-test \
  --as-of-date 2026-07-27 \
  --sample-symbol 600763 \
  --output reports/interface_smoke_test.csv \
  --evidence-dir reports/evidence/stage2 \
  --max-sample-rows 20
```

### 4.2 Result

**Exit code: 1** -- Overall status: **BLOCKED**

All 10 network-based probes failed with `connection_error`:
- All probes reached `function_exists=True` with correct AKShare 1.18.80 signatures
- Connection to all upstream hosts (push2his.eastmoney.com, push2.eastmoney.com,
  quotes.sina.cn, money.finance.sina.com.cn, emweb.securities.eastmoney.com,
  datacenter-api.jin10.com) failed with HTTPSConnectionPool MaxRetriesExceeded
- The probe adapter's built-in retry (1 retry on timeout/connection_error, 2s delay) was exhausted
- 2 probes (limit_up_pool, limit_down_pool) were `skipped` because pool_date
  could not be resolved from the failed stock_daily_qfq probe

### 4.3 Probe Results Summary

| probe_id | status | function_exists | function_signature |
|---|---|---|---|
| stock_daily_qfq | failed | True | (symbol, period, start_date, end_date, adjust, timeout) |
| stock_daily_raw | failed | True | (symbol, period, start_date, end_date, adjust, timeout) |
| stock_spot | failed | True | stock_zh_a_spot_em() |
| financial_abstract | failed | True | stock_financial_abstract(symbol) |
| financial_indicator | failed | True | stock_financial_analysis_indicator(symbol, start_year) |
| balance_sheet_report | failed | True | stock_balance_sheet_by_report_em(symbol) |
| profit_sheet_report | failed | True | stock_profit_sheet_by_report_em(symbol) |
| cashflow_sheet_report | failed | True | stock_cash_flow_sheet_by_report_em(symbol) |
| individual_fund_flow | failed | True | stock_individual_fund_flow(stock, market) |
| limit_up_pool | skipped | True | stock_zt_pool_em(date) |
| limit_down_pool | skipped | True | stock_zt_pool_dtgc_em(date) |
| crypto_spot | failed | True | crypto_js_spot() |

### 4.4 Key Findings

1. **All 12 probes map to 11 unique AKShare functions**, and all 11 functions
   exist in version 1.18.80 with the expected names
2. **Function signatures recorded** via `inspect.signature` for all 11 unique functions
3. **Network environment cannot reach AKShare upstream** -- all East Money,
   Sina Finance, and Jin10 endpoints are unreachable from the current machine
4. **The probe framework is functional**: CSV output generated with 12 rows,
   evidence manifest created in `reports/evidence/stage2/<run_id>/`

## 5. Offline Test Results

```
pytest -q: 86 passed in 17.38s
```

All Stage 0 tests (74) continue to pass; 12 Stage 2 interface config tests pass.

## 6. Stage 0 File Integrity

| File | SHA-256 | Status |
|---|---|---|
| `config/universe.yml` | `0B6F61...CCEC65` | Unchanged |
| `config/metric_definition.yml` | `13F941...5C00C4` | Unchanged |
| `docs/stage0_scope.md` | `18EEEC...761615` | Unchanged |

## 7. Stage-External Modifications

- No modifications to `data/raw`, `data/clean`, `data/feature`, or `database/`
- No batch capture of 16 stocks
- No formal Raw/Clean/Feature data written
- No business database created
- No indicators or analysis computed
- No non-AKShare data sources accessed
- No investment advice output

## 8. Stage Status: BLOCKED

**Reason**: The runtime environment cannot reach AKShare upstream servers.
All 10 network-based probes encountered `connection_error` after retry.

### Prerequisites for Stage 3

Before entering Stage 3 (batch capture of historical quotes and real-time
valuations), the following must be resolved:
1. Network connectivity to AKShare upstream hosts (eastmoney.com, sina.com.cn, jin10.com)
2. Successful smoke-test run with `stock_daily_qfq`, `stock_daily_raw`, and
   `stock_spot` all returning `success`
3. At least one financial probe returning `success`
4. Re-run `smoke-test` to confirm connectivity before proceeding

> This task completed only interface inventory and small-sample smoke testing;
> no batch capture of 16 stocks, no formal Raw/Clean/Feature data written,
> no business database created, no indicators or analysis computed,
> no non-AKShare data sources accessed.
