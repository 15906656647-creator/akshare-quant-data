# Stage 17港股人工/外部数据导入区

本目录用于Stage 17.6.5的`09669.HK`人工、商业、经纪商或HKEX授权数据导入。

当前仓库没有附带任何外部行情文件。不得将示例metadata当作来源证明，也不得用已有
Stage 17验证Raw复制补齐本目录。

## 文件命名

每个口径提供一个CSV或Parquet文件及一个metadata文件：

```text
09669.HK.raw.csv                   或 09669.HK.raw.parquet
09669.HK.raw.metadata.json
09669.HK.qfq.csv                   或 09669.HK.qfq.parquet
09669.HK.qfq.metadata.json
09669.HK.hfq.csv                   或 09669.HK.hfq.parquet
09669.HK.hfq.metadata.json
```

CSV/Parquet必须包含：

```text
symbol,date,open,high,low,close,volume
```

可选字段：`amount`、`turnover`。

## metadata要求

metadata必须至少包含：

```json
{
  "symbol": "09669.HK",
  "provider": "manual_external",
  "source": "供应商、授权产品或可审计来源标识",
  "adjust_type": "qfq",
  "acquired_at": "带时区的ISO-8601时间",
  "sha256": "对应CSV或Parquet的SHA-256",
  "adjustment_basis": "provider_native",
  "provider_adjust_semantics": "供应商对前复权或后复权的正式定义",
  "field_definition": "OHLCV字段、币种、交易所和单位说明"
}
```

`raw`必须使用：

```text
adjustment_basis=unadjusted_provider_native
```

`qfq/hfq`允许：

- `provider_native`：外部Provider直接提供，必须记录正式复权定义；
- `calculated_from_corporate_actions`：由Raw、公司行动和调整因子计算。

计算型数据还必须在`adjustment_evidence`中记录：

```json
{
  "raw_sha256": "...",
  "corporate_actions_sha256": "...",
  "factors_sha256": "..."
}
```

不得使用空字符串、推断来源、Yahoo `Adj Close`或未经证明的单位因子冒充qfq/hfq。

## 离线检查

```powershell
python -m akshare_data_test.stage17_hk_manual_validation `
  --evidence-run-id 78cddc46-4b2a-4ebe-9065-1e54e3dff522 `
  --input-dir data/manual/stage17/hk `
  --as-of-date 2026-08-24 `
  --validate-only
```

正式验证必须另传全新UUID作为`--run-id`。验证通过也不会自动修改Stage 17正式状态或
授权Stage 18。
