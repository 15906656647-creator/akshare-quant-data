# Stage 13: test data presentation, database display, and reproducible report

## Execution summary

- Status: **READY**
- as_of_date: `2026-07-27`
- run_id: `stage13-20260727-reverify-remediation`
- config_sha256: `aded67bbde36eb19927552d9a280adeb93718463c6dcc8bf7bc7ba52716dc6d7`
- visible_input_sha256: `28fda7115e9d0c3515d85198511dfcdb5771ae341116c2f7242d18a609a1e24a`
- canonical_sha256: `360fcbc6ee33d47c7d765806899dcacf8bf26118d4e2fc2a686d6734a02d31be`
- run_identity_sha256: `05bb6ac9b76208df9569571afc02fb80ae5c6ac3cdcc07a3140a6871cfb9272b`
- Universe coverage: `16/16`
- Asset matrix: `144 = 16 × 9`
- Status totals: AVAILABLE=112, PARTIAL=16, NOT_AVAILABLE=16, BLOCKED=0
- Data source: local Stage 5, Stage 6, and Stage 7 DuckDB files; no network access.

## Asset availability

| asset | AVAILABLE | PARTIAL | NOT_AVAILABLE | BLOCKED |
|---|---:|---:|---:|---:|
| activity_components | 16 | 0 | 0 | 0 |
| financial_trend | 16 | 0 | 0 | 0 |
| fund_flow_price | 16 | 0 | 0 | 0 |
| limit_events | 16 | 0 | 0 | 0 |
| next_open_return | 16 | 0 | 0 | 0 |
| price_ma | 16 | 0 | 0 | 0 |
| range_40_breakouts | 0 | 16 | 0 | 0 |
| valuation_snapshot | 0 | 0 | 16 | 0 |
| volume_ma | 16 | 0 | 0 | 0 |

Limit-event outputs use only formal Stage 6 `confirmed` rows; an empty confirmed set is a valid AVAILABLE no-event result and no fixed ±10% rule is substituted. Next-open return is `next_trade_day_open / event_day_close - 1`, with cutoff events lacking a visible next day retained as missing. Valuation snapshots are never backdated. Range charts are PARTIAL because authoritative Stage 6 range metrics exist but a formal breakout-event result does not.

## Database display

- Database files: 3
- Schemas: 5
- Tables/views: 42
- Inventory status: AVAILABLE=42, PARTIAL=0, NOT_AVAILABLE=0, BLOCKED=0
- Connections: read-only; physical hashes are checked transiently and never enter published identity.
- Full row counts, date ranges, and target-symbol coverage: [database_inventory.md](database_inventory.md)

## Reproducible SQL

| query | title | rows | result SHA-256 |
|---|---|---:|---|
| query_01 | Activity ranking | 16 | 942d1f44544e9728865b5881d7600b5ea416907627d4cc6f88f5bb77c85ca590 |
| query_02 | Latest volume expansion | 0 | a469c49c5da4457020b447ed82f2122c7b71cff0e5ba58f2374bf6363a347f9b |
| query_03 | Latest 40-session range profile | 16 | 7eb5be727353d5e645c4dcf2fb344acd061391fd549f638877cc9e41089a736f |

SQL text and CSV results are stored under `sql/`. All statements are single-statement, parameterized, read-only queries with stable ordering.

## Stock chart index

| symbol | generated assets |
|---|---|
| 000100 | [activity_components](charts/000100/activity_components.png), [financial_trend](charts/000100/financial_trend.png), [fund_flow_price](charts/000100/fund_flow_price.png), [limit_events](charts/000100/limit_events.png), [next_open_return](charts/000100/next_open_return.png), [price_ma](charts/000100/price_ma.png), [range_40_breakouts](charts/000100/range_40_breakouts.png), [volume_ma](charts/000100/volume_ma.png) |
| 002067 | [activity_components](charts/002067/activity_components.png), [financial_trend](charts/002067/financial_trend.png), [fund_flow_price](charts/002067/fund_flow_price.png), [limit_events](charts/002067/limit_events.png), [next_open_return](charts/002067/next_open_return.png), [price_ma](charts/002067/price_ma.png), [range_40_breakouts](charts/002067/range_40_breakouts.png), [volume_ma](charts/002067/volume_ma.png) |
| 002129 | [activity_components](charts/002129/activity_components.png), [financial_trend](charts/002129/financial_trend.png), [fund_flow_price](charts/002129/fund_flow_price.png), [limit_events](charts/002129/limit_events.png), [next_open_return](charts/002129/next_open_return.png), [price_ma](charts/002129/price_ma.png), [range_40_breakouts](charts/002129/range_40_breakouts.png), [volume_ma](charts/002129/volume_ma.png) |
| 002230 | [activity_components](charts/002230/activity_components.png), [financial_trend](charts/002230/financial_trend.png), [fund_flow_price](charts/002230/fund_flow_price.png), [limit_events](charts/002230/limit_events.png), [next_open_return](charts/002230/next_open_return.png), [price_ma](charts/002230/price_ma.png), [range_40_breakouts](charts/002230/range_40_breakouts.png), [volume_ma](charts/002230/volume_ma.png) |
| 002361 | [activity_components](charts/002361/activity_components.png), [financial_trend](charts/002361/financial_trend.png), [fund_flow_price](charts/002361/fund_flow_price.png), [limit_events](charts/002361/limit_events.png), [next_open_return](charts/002361/next_open_return.png), [price_ma](charts/002361/price_ma.png), [range_40_breakouts](charts/002361/range_40_breakouts.png), [volume_ma](charts/002361/volume_ma.png) |
| 002600 | [activity_components](charts/002600/activity_components.png), [financial_trend](charts/002600/financial_trend.png), [fund_flow_price](charts/002600/fund_flow_price.png), [limit_events](charts/002600/limit_events.png), [next_open_return](charts/002600/next_open_return.png), [price_ma](charts/002600/price_ma.png), [range_40_breakouts](charts/002600/range_40_breakouts.png), [volume_ma](charts/002600/volume_ma.png) |
| 300274 | [activity_components](charts/300274/activity_components.png), [financial_trend](charts/300274/financial_trend.png), [fund_flow_price](charts/300274/fund_flow_price.png), [limit_events](charts/300274/limit_events.png), [next_open_return](charts/300274/next_open_return.png), [price_ma](charts/300274/price_ma.png), [range_40_breakouts](charts/300274/range_40_breakouts.png), [volume_ma](charts/300274/volume_ma.png) |
| 300433 | [activity_components](charts/300433/activity_components.png), [financial_trend](charts/300433/financial_trend.png), [fund_flow_price](charts/300433/fund_flow_price.png), [limit_events](charts/300433/limit_events.png), [next_open_return](charts/300433/next_open_return.png), [price_ma](charts/300433/price_ma.png), [range_40_breakouts](charts/300433/range_40_breakouts.png), [volume_ma](charts/300433/volume_ma.png) |
| 600231 | [activity_components](charts/600231/activity_components.png), [financial_trend](charts/600231/financial_trend.png), [fund_flow_price](charts/600231/fund_flow_price.png), [limit_events](charts/600231/limit_events.png), [next_open_return](charts/600231/next_open_return.png), [price_ma](charts/600231/price_ma.png), [range_40_breakouts](charts/600231/range_40_breakouts.png), [volume_ma](charts/600231/volume_ma.png) |
| 600438 | [activity_components](charts/600438/activity_components.png), [financial_trend](charts/600438/financial_trend.png), [fund_flow_price](charts/600438/fund_flow_price.png), [limit_events](charts/600438/limit_events.png), [next_open_return](charts/600438/next_open_return.png), [price_ma](charts/600438/price_ma.png), [range_40_breakouts](charts/600438/range_40_breakouts.png), [volume_ma](charts/600438/volume_ma.png) |
| 600763 | [activity_components](charts/600763/activity_components.png), [financial_trend](charts/600763/financial_trend.png), [fund_flow_price](charts/600763/fund_flow_price.png), [limit_events](charts/600763/limit_events.png), [next_open_return](charts/600763/next_open_return.png), [price_ma](charts/600763/price_ma.png), [range_40_breakouts](charts/600763/range_40_breakouts.png), [volume_ma](charts/600763/volume_ma.png) |
| 601012 | [activity_components](charts/601012/activity_components.png), [financial_trend](charts/601012/financial_trend.png), [fund_flow_price](charts/601012/fund_flow_price.png), [limit_events](charts/601012/limit_events.png), [next_open_return](charts/601012/next_open_return.png), [price_ma](charts/601012/price_ma.png), [range_40_breakouts](charts/601012/range_40_breakouts.png), [volume_ma](charts/601012/volume_ma.png) |
| 601500 | [activity_components](charts/601500/activity_components.png), [financial_trend](charts/601500/financial_trend.png), [fund_flow_price](charts/601500/fund_flow_price.png), [limit_events](charts/601500/limit_events.png), [next_open_return](charts/601500/next_open_return.png), [price_ma](charts/601500/price_ma.png), [range_40_breakouts](charts/601500/range_40_breakouts.png), [volume_ma](charts/601500/volume_ma.png) |
| 601636 | [activity_components](charts/601636/activity_components.png), [financial_trend](charts/601636/financial_trend.png), [fund_flow_price](charts/601636/fund_flow_price.png), [limit_events](charts/601636/limit_events.png), [next_open_return](charts/601636/next_open_return.png), [price_ma](charts/601636/price_ma.png), [range_40_breakouts](charts/601636/range_40_breakouts.png), [volume_ma](charts/601636/volume_ma.png) |
| 603259 | [activity_components](charts/603259/activity_components.png), [financial_trend](charts/603259/financial_trend.png), [fund_flow_price](charts/603259/fund_flow_price.png), [limit_events](charts/603259/limit_events.png), [next_open_return](charts/603259/next_open_return.png), [price_ma](charts/603259/price_ma.png), [range_40_breakouts](charts/603259/range_40_breakouts.png), [volume_ma](charts/603259/volume_ma.png) |
| 603799 | [activity_components](charts/603799/activity_components.png), [financial_trend](charts/603799/financial_trend.png), [fund_flow_price](charts/603799/fund_flow_price.png), [limit_events](charts/603799/limit_events.png), [next_open_return](charts/603799/next_open_return.png), [price_ma](charts/603799/price_ma.png), [range_40_breakouts](charts/603799/range_40_breakouts.png), [volume_ma](charts/603799/volume_ma.png) |

## Definitions, evidence, and limitations

- Price is qfq; volume is standardized shares. MA3/5/7/10/13/20/21 and volume MA5/20 come from Stage 6 rather than being recomputed in the chart layer.
- Confirmed limit-event CSV rows preserve `event_price` from authoritative Stage 6 `feat_limit_event.raw_close`; event charts plot that same value. Invalid or missing authoritative prices are never replaced with zero and make the affected assets PARTIAL.
- Financial values are reported cumulative values, not derived single-quarter values. Only records with `announcement_date <= as_of_date` are visible.
- The upstream-labelled main-fund-flow category is not evidence of a verified trading entity. Any related interpretation is only a **疑似主力行为特征** and requires feature evidence, confidence, and explanation.
- No snapshot is presented as a historical valuation series. Missing data remains missing rather than being replaced by zero or fixture data.
- No future price, volume, event, financial, valuation, or fund-flow row enters an output.
- PNG generation is headless, fixed-size, fixed-DPI, deterministic, and closes every figure.

## Quality, tests, Git, and reproduction

- Network attempts: 0. Stage 13 contains no adapter, collector, AKShare, or HTTP call.
- Database evidence: read-only opens and transient physical SHA-256 equality before/after generation; physical hashes are not published.
- Atomicity: outputs are built in a temporary sibling directory and published only after validation.
- Manifest: unique symbol × 9 keys; every AVAILABLE/PARTIAL path exists and matches its SHA-256.
- Inventory gate: `inventory_blocked_count=0`; READY publication requires zero BLOCKED inventory rows.
- Dry-run performs validation but creates no report directory.
- Automated-test and Git gate evidence is recorded in `docs/stage13_acceptance.md`; this generated report does not invent test outcomes.
- Reproduce with the same local databases, `config/stage13.yml`, cutoff, and run_id via `present-stage13`.
- This formal report was regenerated by the production entry from the current `config/stage13.yml`; its recorded `config_sha256` matches that file.
- Future-data byte-identity gate: **PASS**. The acceptance black box added post-cutoff price/volume, event, financial, fund-flow, valuation, style, and activity rows to an independent database copy; every published file remained byte-for-byte identical.

This project is for research and data-pipeline testing only. It does not provide investment advice.
