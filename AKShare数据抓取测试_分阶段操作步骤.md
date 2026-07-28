# AKShare 数据抓取测试：分阶段操作步骤

> 文档日期：2026-07-27  
> 本文档用于指导实际实施。命令以 Linux/macOS Shell 为主，Windows PowerShell 可做等价调整。

## 0. 阶段零：冻结范围与分析口径

### 0.1 固定测试对象

```python
STOCKS = [
    "002067", "002600", "002230", "600763",
    "603259", "603799", "601012", "600438",
    "002361", "601500", "600231", "300274",
    "601636", "002129", "000100", "300433",
]
CRYPTO_PAIR = "ETHUSDT"
```

### 0.2 固定测试时间范围

建议：

- 日线基础测试：最近 3 年。
- “一年内涨跌停”统计：以测试执行日向前 365 个自然日为取数范围，再按交易日统计。
- 财务数据：最近 5 年年报和最近 12 个季度。
- 资金流：接口允许的全部历史，文档显示通常为近约 100 个交易日。
- 实时行情：执行测试时保存快照。

### 0.3 明确数据口径

- 趋势、均线和收益：前复权 `qfq`。
- 涨跌停识别：不复权 `adjust=""`。
- 长期财富曲线研究：可额外保存后复权 `hfq`。
- 财务数据：保留报告期、公告日、更新时间和是否累计口径。
- 百分比数据库存储：建议统一为小数，例如 5% 保存为 `0.05`。
- “主力行为”统一命名为“疑似主力行为特征”，不输出确定性结论。

阶段产出：`config/universe.yml`、`config/metric_definition.yml`。

---

## 1. 阶段一：环境搭建

### 1.1 安装 Python

AKShare README 要求 64 位 Python 3.9 及以上；当前文档推荐更高版本。测试环境建议使用 Python 3.12。

使用 `venv`：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
```

Windows：

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip setuptools wheel
```

### 1.2 安装依赖

```bash
pip install --upgrade akshare pandas numpy pyarrow duckdb sqlalchemy pydantic pyyaml python-dotenv tenacity matplotlib openpyxl
```

可选数据质量依赖：

```bash
pip install pandera pytest
```

生成依赖锁定文件：

```bash
pip freeze > requirements-lock.txt
```

建议手工维护简洁版 `requirements.txt`：

```text
akshare
pandas
numpy
pyarrow
duckdb
sqlalchemy
pydantic
pyyaml
python-dotenv
tenacity
matplotlib
pandera
pytest
```

### 1.3 验证环境

```bash
python - <<'PY'
import sys
import akshare as ak
import pandas as pd
import duckdb

print("Python:", sys.version)
print("AKShare:", ak.__version__)
print("pandas:", pd.__version__)
print("DuckDB:", duckdb.__version__)
PY
```

验收条件：所有包能正常导入并打印版本号。

---

## 2. 阶段二：建立项目目录和配置

### 2.1 推荐目录

```text
akshare_data_test/
├── README.md
├── requirements.txt
├── requirements-lock.txt
├── .env.example
├── config/
│   ├── universe.yml
│   ├── interfaces.yml
│   ├── field_mapping.yml
│   └── metric_definition.yml
├── data/
│   ├── raw/
│   ├── clean/
│   ├── feature/
│   └── export/
├── database/
│   └── akshare_test.duckdb
├── logs/
├── notebooks/
├── reports/
├── sql/
├── src/
│   ├── adapters/
│   │   ├── stock_market.py
│   │   ├── stock_finance.py
│   │   ├── stock_event.py
│   │   └── crypto_market.py
│   ├── collectors/
│   ├── cleaners/
│   ├── features/
│   ├── storage/
│   ├── quality/
│   └── utils/
├── tests/
└── run_pipeline.py
```

### 2.2 证券代码映射配置

`config/universe.yml` 示例：

```yaml
stocks:
  - symbol: "002067"
    exchange: "SZ"
  - symbol: "002600"
    exchange: "SZ"
  - symbol: "002230"
    exchange: "SZ"
  - symbol: "600763"
    exchange: "SH"
  - symbol: "603259"
    exchange: "SH"
  - symbol: "603799"
    exchange: "SH"
  - symbol: "601012"
    exchange: "SH"
  - symbol: "600438"
    exchange: "SH"
  - symbol: "002361"
    exchange: "SZ"
  - symbol: "601500"
    exchange: "SH"
  - symbol: "600231"
    exchange: "SH"
  - symbol: "300274"
    exchange: "SZ"
  - symbol: "601636"
    exchange: "SH"
  - symbol: "002129"
    exchange: "SZ"
  - symbol: "000100"
    exchange: "SZ"
  - symbol: "300433"
    exchange: "SZ"
crypto:
  - pair: "ETHUSDT"
```

在加载配置时生成：

```python
symbol_plain = "600763"
symbol_em = "SH600763"
market_lower = "sh"
```

---

## 3. 阶段三：接口盘点与冒烟测试

先对单只股票执行，不立即批量抓取 16 只股票。

### 3.1 A 股历史日线

```python
import akshare as ak

stock_daily = ak.stock_zh_a_hist(
    symbol="600763",
    period="daily",
    start_date="20250101",
    end_date="20260727",
    adjust="qfq",
    timeout=15,
)
print(stock_daily.head())
print(stock_daily.tail())
print(stock_daily.dtypes)
```

验证字段：日期、股票代码、开盘、收盘、最高、最低、成交量、成交额、振幅、涨跌幅、涨跌额、换手率。

再执行一次不复权数据：

```python
stock_daily_raw_price = ak.stock_zh_a_hist(
    symbol="600763",
    period="daily",
    start_date="20250101",
    end_date="20260727",
    adjust="",
)
```

### 3.2 实时行情与估值

```python
spot = ak.stock_zh_a_spot_em()
sample_spot = spot[spot["代码"].astype(str).str.zfill(6).isin(["600763", "002067"])]
print(sample_spot[[
    "代码", "名称", "最新价", "成交额", "振幅", "量比", "换手率",
    "市盈率-动态", "市净率", "总市值", "流通市值"
]])
```

注意：该接口一次返回全市场数据，批量任务中只调用一次，再筛选 16 个代码，不能每只股票重复调用。

### 3.3 财务关键指标

```python
financial_abstract = ak.stock_financial_abstract(symbol="600763")
print(financial_abstract.head())
```

```python
financial_indicator = ak.stock_financial_analysis_indicator(
    symbol="600763",
    start_year="2021",
)
print(financial_indicator.head())
```

### 3.4 三大财务报表

```python
balance = ak.stock_balance_sheet_by_report_em(symbol="SH600763")
profit = ak.stock_profit_sheet_by_report_em(symbol="SH600763")
cashflow = ak.stock_cash_flow_sheet_by_report_em(symbol="SH600763")

print(balance.shape, profit.shape, cashflow.shape)
```

先保存完整原始字段，不要在冒烟测试阶段直接删列。

### 3.5 个股资金流

```python
fund_flow = ak.stock_individual_fund_flow(stock="600763", market="sh")
print(fund_flow.head())
print(fund_flow.tail())
```

### 3.6 涨跌停池

使用最近有效交易日：

```python
zt_pool = ak.stock_zt_pool_em(date="20260724")
dt_pool = ak.stock_zt_pool_dtgc_em(date="20260724")
print(zt_pool.head())
print(dt_pool.head())
```

若日期无数据，记录为“非交易日、上游暂无数据或接口失败”，不能默认为 0 个涨停。

### 3.7 加密货币实时行情

```python
crypto_spot = ak.crypto_js_spot()
print(crypto_spot.head())
print(crypto_spot[crypto_spot.astype(str).apply(
    lambda col: col.str.contains("ETH", case=False, na=False)
).any(axis=1)])
```

结果判定：

- 返回明确的 ETHUSDT：AKShare 目标交易对实时行情测试成功。
- 仅返回 ETHUSD 或其他市场 ETH：部分成功，需要在数据模型中保存真实市场和交易品种，不能改名为 ETHUSDT。
- 无 ETH 数据：记录 AKShare 当前接口不覆盖目标品种。
- 需要历史 K 线但无相应 AKShare 接口：列为能力缺口，不伪造数据。

### 3.8 冒烟测试记录表

每个接口记录：

| 字段 | 说明 |
|---|---|
| `interface_name` | AKShare 函数名 |
| `parameters` | 调用参数 JSON |
| `run_time` | 执行时间 |
| `akshare_version` | AKShare 版本 |
| `status` | success / empty / failed |
| `row_count` | 返回行数 |
| `column_count` | 返回列数 |
| `elapsed_seconds` | 耗时 |
| `schema_hash` | 字段列表哈希 |
| `error_type` | 异常类型 |
| `error_message` | 异常信息 |

阶段产出：`reports/interface_smoke_test.csv`。

---

## 4. 阶段四：实现稳健抓取器

### 4.1 抓取器统一返回结构

```python
from dataclasses import dataclass
from datetime import datetime
import pandas as pd

@dataclass
class FetchResult:
    interface_name: str
    params: dict
    fetched_at: datetime
    status: str
    dataframe: pd.DataFrame
    error_message: str | None = None
```

### 4.2 增加重试和限速

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=20),
    reraise=True,
)
def fetch_stock_daily(symbol: str, start_date: str, end_date: str, adjust: str):
    import akshare as ak
    return ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust=adjust,
        timeout=20,
    )
```

批量抓取时：

- 股票之间增加 0.5～2 秒随机间隔。
- 失败时最多重试 3 次。
- 全市场接口只执行一次。
- 抓取结果先写临时文件，成功后原子重命名。
- 空 DataFrame 和异常分开记录。

### 4.3 保存 Raw 数据

文件命名建议：

```text
data/raw/stock_zh_a_hist/symbol=600763/adjust=qfq/fetch_date=2026-07-27/part.parquet
```

同时生成元数据 JSON：

```json
{
  "interface": "stock_zh_a_hist",
  "symbol": "600763",
  "adjust": "qfq",
  "fetched_at": "2026-07-27T10:00:00+08:00",
  "akshare_version": "实际运行版本",
  "rows": 760,
  "columns": ["日期", "股票代码", "开盘", "收盘"]
}
```

---

## 5. 阶段五：数据清洗与标准化

### 5.1 日线行情字段映射

| 原始字段 | 标准字段 | 处理 |
|---|---|---|
| 日期 | `trade_date` | 转 `date` |
| 股票代码 | `symbol` | `str.zfill(6)` |
| 开盘 | `open` | `float64` |
| 最高 | `high` | `float64` |
| 最低 | `low` | `float64` |
| 收盘 | `close` | `float64` |
| 成交量 | `volume_lot` | 原始单位“手” |
| 成交额 | `amount_cny` | 人民币元 |
| 振幅 | `amplitude` | 除以 100 转小数 |
| 涨跌幅 | `pct_change` | 除以 100 转小数 |
| 涨跌额 | `price_change` | 数值 |
| 换手率 | `turnover_rate` | 除以 100 转小数 |

派生字段：

```python
df["volume_share"] = df["volume_lot"] * 100
```

### 5.2 基础质量检查

```python
assert df["symbol"].str.len().eq(6).all()
assert df[["trade_date", "symbol", "adjust_type"]].duplicated().sum() == 0
assert (df["high"] >= df[["open", "close", "low"]].max(axis=1)).all()
assert (df["low"] <= df[["open", "close", "high"]].min(axis=1)).all()
assert (df["volume_lot"].dropna() >= 0).all()
```

不能简单删除所有空值。停牌日、财务字段未披露和接口异常要使用不同状态字段。

### 5.3 财务报表清洗

建议先做“关键字段白名单”，完整原始表保留在 Raw 层：

- 营业总收入/营业收入
- 营业成本
- 营业利润
- 利润总额
- 净利润
- 归母净利润
- 扣非归母净利润
- 经营活动现金流净额
- 总资产
- 总负债
- 归母股东权益
- 基本每股收益
- 净资产收益率
- 毛利率、净利率

处理重点：

1. 同一报告期可能存在多个公告版本，按更新时间排序并保留版本。
2. 累计利润表转单季度：二季度单季 = 半年累计 - 一季度累计；三季度类似；四季度单季 = 年度累计 - 前三季度累计。
3. 银行、保险等行业财务字段结构不同，缺失不能一律视为异常。
4. 财务金额单位统一为人民币元。

### 5.4 估值快照清洗

`stock_zh_a_spot_em` 中的 PE/PB 是抓取时点快照。每日定时运行并保存：

```text
symbol, snapshot_time, pe_dynamic, pb, total_market_cap, float_market_cap
```

历史估值不能通过当前快照回填。

---

## 6. 阶段六：数据库落地

### 6.1 初始化 DuckDB

```python
import duckdb

con = duckdb.connect("database/akshare_test.duckdb")
con.execute("CREATE SCHEMA IF NOT EXISTS raw")
con.execute("CREATE SCHEMA IF NOT EXISTS clean")
con.execute("CREATE SCHEMA IF NOT EXISTS feature")
con.execute("CREATE SCHEMA IF NOT EXISTS analysis")
```

### 6.2 建表示例

```sql
CREATE TABLE IF NOT EXISTS clean.fact_stock_daily (
    symbol VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    adjust_type VARCHAR NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume_lot BIGINT,
    volume_share BIGINT,
    amount_cny DOUBLE,
    amplitude DOUBLE,
    pct_change DOUBLE,
    price_change DOUBLE,
    turnover_rate DOUBLE,
    source_name VARCHAR,
    fetched_at TIMESTAMP,
    PRIMARY KEY (symbol, trade_date, adjust_type)
);
```

```sql
CREATE TABLE IF NOT EXISTS clean.fact_stock_spot (
    symbol VARCHAR NOT NULL,
    snapshot_time TIMESTAMP NOT NULL,
    name VARCHAR,
    latest_price DOUBLE,
    volume_ratio DOUBLE,
    turnover_rate DOUBLE,
    pe_dynamic DOUBLE,
    pb DOUBLE,
    total_market_cap DOUBLE,
    float_market_cap DOUBLE,
    PRIMARY KEY (symbol, snapshot_time)
);
```

```sql
CREATE TABLE IF NOT EXISTS analysis.fact_limit_event (
    symbol VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    event_type VARCHAR NOT NULL,
    close_price DOUBLE,
    limit_price DOUBLE,
    next_open_return DOUBLE,
    next_close_return DOUBLE,
    forward_5d_return DOUBLE,
    is_continued_limit BOOLEAN,
    rule_version VARCHAR,
    PRIMARY KEY (symbol, trade_date, event_type)
);
```

### 6.3 写入方式

```python
con.register("daily_df", daily_df)
con.execute("""
    INSERT OR REPLACE INTO clean.fact_stock_daily
    SELECT * FROM daily_df
""")
```

如使用 PostgreSQL，改用 SQLAlchemy，并通过 `ON CONFLICT DO UPDATE` 实现幂等写入。

### 6.4 数据库展示 SQL

查看样本股票最近行情：

```sql
SELECT symbol, trade_date, close, amount_cny, turnover_rate
FROM clean.fact_stock_daily
WHERE symbol IN ('600763', '603259')
  AND adjust_type = 'qfq'
ORDER BY trade_date DESC
LIMIT 20;
```

查看估值：

```sql
SELECT symbol, name, snapshot_time, pe_dynamic, pb, total_market_cap
FROM clean.fact_stock_spot
QUALIFY ROW_NUMBER() OVER (
    PARTITION BY symbol ORDER BY snapshot_time DESC
) = 1;
```

查看一年涨跌停统计：

```sql
SELECT
    symbol,
    SUM(event_type = 'limit_up') AS limit_up_count,
    SUM(event_type = 'limit_down') AS limit_down_count,
    AVG(CASE WHEN event_type = 'limit_up' THEN next_open_return END) AS avg_next_open_return
FROM analysis.fact_limit_event
WHERE trade_date >= CURRENT_DATE - INTERVAL 365 DAY
GROUP BY symbol
ORDER BY limit_up_count DESC;
```

---

## 7. 阶段七：计算均线与基础量价指标

### 7.1 均线

```python
MA_WINDOWS = [3, 5, 7, 10, 13, 20, 21]

df = df.sort_values(["symbol", "trade_date"])
for window in MA_WINDOWS:
    df[f"ma_{window}"] = (
        df.groupby("symbol")["close"]
          .transform(lambda s: s.rolling(window, min_periods=window).mean())
    )
```

### 7.2 成交量和收益指标

```python
df["return_1d"] = df.groupby("symbol")["close"].pct_change()
df["volume_ma_5"] = df.groupby("symbol")["volume_share"].transform(
    lambda s: s.rolling(5).mean()
)
df["volume_ma_20"] = df.groupby("symbol")["volume_share"].transform(
    lambda s: s.rolling(20).mean()
)
df["volume_ratio_20"] = df["volume_share"] / df["volume_ma_20"]
df["intraday_range"] = (df["high"] - df["low"]) / df["close"].shift(1)
```

### 7.3 活跃度评分建议

对每只股票最近 120 个交易日计算：

- 平均成交额及成交额分位数。
- 平均换手率和高换手天数占比。
- 20 日年化波动率均值。
- 日均振幅。
- `volume_ratio_20 >= 2` 的天数占比。
- `|return_1d| >= 5%` 的天数占比。
- 涨停、跌停和跳空次数。

示例公式：

```text
activity_score =
    0.25 × 成交额分位数
  + 0.20 × 换手率分位数
  + 0.20 × 波动率分位数
  + 0.15 × 放量频率分位数
  + 0.10 × 大涨大跌频率分位数
  + 0.10 × 事件频率分位数
```

必须同时输出组成分数，避免只保留总分。

---

## 8. 阶段八：涨跌停统计与事件研究

### 8.1 使用不复权行情

涨跌停必须基于真实交易价格，不使用前复权收盘价。

### 8.2 建立涨跌停规则表

建议表：

```text
exchange, board, special_treatment, effective_start, effective_end,
limit_up_ratio, limit_down_ratio, no_limit_flag, source_reference
```

证券状态历史表：

```text
symbol, effective_start, effective_end, board, is_st, listing_status
```

### 8.3 识别逻辑

优先级：

1. 若接口提供当日涨停价/跌停价，直接使用。
2. 若无历史限价字段，使用昨日收盘价、当日规则和价格精度计算理论限价。
3. 用收盘价与理论限价的最小价格单位容差匹配。
4. 用近期涨跌停池校验识别结果，但不依赖股池构建全年历史。

伪代码：

```python
is_limit_up = abs(close - limit_up_price) <= tick_size / 2
is_limit_down = abs(close - limit_down_price) <= tick_size / 2
```

### 8.4 次日开盘和后续表现

```python
df["next_open"] = df.groupby("symbol")["open"].shift(-1)
df["next_close"] = df.groupby("symbol")["close"].shift(-1)
df["next_open_return"] = df["next_open"] / df["close"] - 1
df["next_close_return"] = df["next_close"] / df["close"] - 1
```

再计算未来 3、5、10 日累计收益、最大有利变动和最大不利变动。

### 8.5 输出表

| symbol | 一年涨停次数 | 一年跌停次数 | 涨停次日平均开盘收益 | 次日高开比例 | 次日连板比例 | 5 日平均收益 |
|---|---:|---:|---:|---:|---:|---:|

---

## 9. 阶段九：横盘震荡和疑似洗盘风格

### 9.1 横盘特征

按 20、40、60 个交易日窗口计算：

```python
rolling_high = close.rolling(40).max()
rolling_low = close.rolling(40).min()
box_width = rolling_high / rolling_low - 1
```

补充：

- 线性回归斜率绝对值。
- R²，用于判断是否存在明显趋势。
- 布林带宽度。
- ATR/收盘价。
- 区间内触及上沿、下沿次数。
- 成交量趋势斜率。
- 假突破后 3 日内回到箱体的次数。

### 9.2 风格规则示例

**温和箱体型**：

- 40 日箱体宽度较小。
- 趋势斜率接近 0。
- 日均振幅较低。
- 成交量缓慢萎缩。

**高波动震荡型**：

- 箱体宽度中高。
- 方向趋势不明显。
- 大阳线、大阴线和长影线较多。
- 回撤和恢复速度快。

**放量冲击型**：

- 多次出现 `volume_ratio_20 >= 2`。
- 价格冲击箱体边缘后回落。
- 资金流短期显著但持续性不足。

**低活跃盘整型**：

- 成交额和换手率低。
- 波动率低。
- 突破次数少。

### 9.3 模型输出

```text
symbol, as_of_date, style_label, confidence,
box_width_40, slope_40, volatility_20,
volume_spike_frequency, long_shadow_frequency,
fund_flow_divergence, explanation
```

解释示例：

```text
“近 40 日趋势斜率接近零、箱体宽度 12%、成交量总体收缩，期间两次放量冲高回落，当前更接近温和箱体震荡，但主力行为证据不足。”
```

---

## 10. 阶段十：基本面分析

### 10.1 营收和利润

至少计算：

- 营业收入、归母净利润。
- 同比增长率。
- 最近四季度 TTM。
- 毛利率、净利率。
- 经营现金流/净利润。
- ROE、资产负债率。

### 10.2 估值

- 动态 PE、PB 来自实时行情快照。
- 历史估值需要每日沉淀快照，或者验证 AKShare 的其他历史估值接口。
- PE 为负值或缺失时，不能做普通高低排序，应单独标记亏损或不可用。

### 10.3 “盈亏比”口径

该词不是标准财务报表字段，建议在报告中并列给出两个口径：

1. **上涨/下跌收益比**：平均正收益 / 平均负收益绝对值。
2. **策略盈亏比**：只有定义买入、卖出、止损和持有期后才能计算。

```python
wins = returns[returns > 0]
losses = returns[returns < 0]
payoff_ratio = wins.mean() / abs(losses.mean())
```

---

## 11. 阶段十一：ETHUSDT 能力验证

### 11.1 AKShare 内部验证

1. 调用 `crypto_js_spot`。
2. 保存完整返回结果。
3. 筛选包含 `ETH` 的市场和交易品种。
4. 记录是否精确匹配 `ETHUSDT`。
5. 记录数据字段、更新时间、市场来源和调用稳定性。

### 11.2 结论分级

| 结果 | 结论 |
|---|---|
| 有 ETHUSDT 实时数据 | 实时能力通过 |
| 有 ETH 但非 USDT 计价 | 部分通过，不允许直接替代 |
| 仅有实时无历史 K 线 | 实时通过、历史能力缺失 |
| 无 ETH | AKShare 当前接口不支持目标样本 |

### 11.3 可选补充适配器

若任务明确要求 ETHUSDT 历史 OHLCV，可新建：

```text
src/adapters/crypto_exchange.py
```

该模块与 AKShare 适配器隔离，数据库中增加 `data_provider` 字段，并在报告中明确来源。这样不会把外部交易所数据误标成 AKShare 数据。

---

## 12. 阶段十二：数据筛选与分析样例

### 12.1 筛选活跃股票

```sql
SELECT symbol, activity_score, avg_turnover_120d, volume_spike_frequency
FROM analysis.analysis_stock_profile
WHERE activity_score >= 0.70
ORDER BY activity_score DESC;
```

### 12.2 筛选放量突破候选

```sql
SELECT symbol, trade_date, close, ma_20, volume_ratio_20
FROM feature.feature_stock_daily
WHERE close > ma_20
  AND volume_ratio_20 >= 2.0
ORDER BY trade_date DESC, volume_ratio_20 DESC;
```

### 12.3 筛选箱体震荡股票

```sql
SELECT symbol, as_of_date, style_label, confidence, box_width_40, slope_40
FROM analysis.analysis_stock_profile
WHERE style_label IN ('温和箱体型', '低活跃盘整型')
  AND confidence >= 0.60;
```

### 12.4 基本面与量价联合筛选

```sql
SELECT
    p.symbol,
    p.activity_score,
    f.revenue_yoy,
    f.net_profit_yoy,
    s.pe_dynamic,
    s.pb
FROM analysis.analysis_stock_profile p
JOIN analysis.latest_financial_summary f USING (symbol)
JOIN analysis.latest_stock_spot s USING (symbol)
WHERE f.revenue_yoy > 0
  AND f.net_profit_yoy > 0
  AND p.activity_score >= 0.50;
```

---

## 13. 阶段十三：测试数据呈现

每只股票至少输出以下图表或表格：

1. K 线或收盘价 + 3/5/7/10/13/20/21 日均线。
2. 成交量 + 5/20 日均量。
3. 一年涨停、跌停事件标记。
4. 涨停后次日开盘收益分布。
5. 活跃度子指标雷达图或横向条形图。
6. 40 日箱体区间和突破点。
7. 营收、净利润的季度或年度趋势。
8. 最新 PE、PB、市值及抓取时间。
9. 主力资金净流入及价格对比，仅覆盖接口可获得区间。

数据库展示至少包括：

- 数据库文件及表清单。
- 每张表记录数。
- 最早/最晚日期。
- 16 只股票覆盖率。
- SQL 查询结果截图或导出表。

---

## 14. 阶段十四：自动化运行

### 14.1 命令设计

```bash
python run_pipeline.py smoke-test
python run_pipeline.py fetch-market --start 20230101 --end 20260727
python run_pipeline.py fetch-financial
python run_pipeline.py clean
python run_pipeline.py build-features
python run_pipeline.py analyze-limit-events
python run_pipeline.py analyze-style
python run_pipeline.py build-report
```

### 14.2 运行顺序

```text
smoke-test
  → fetch-market
  → fetch-financial
  → fetch-event-and-fund-flow
  → clean
  → load-database
  → build-features
  → analyze-limit-events
  → analyze-style
  → quality-check
  → build-report
```

### 14.3 幂等要求

- 同一股票、日期、复权类型重复执行不产生重复行。
- 原始抓取文件不被无记录覆盖。
- 数据库写入使用主键 upsert。
- 每次运行生成唯一 `run_id`。
- 失败任务可单独重跑。

---

## 15. 阶段十五：质量控制和风险验证

### 15.1 每日质量检查

- 行数是否异常下降。
- 最新交易日是否更新。
- 字段集合是否变化。
- 样本股票是否缺失。
- OHLC 是否满足逻辑关系。
- 主键是否重复。
- 成交量、金额是否出现非法负值。
- PE/PB 缺失率是否异常。
- 财报关键字段是否缺失。
- 接口执行耗时是否突增。

### 15.2 交叉验证

选 2～3 只股票，对以下内容进行人工核对：

- 最近 5 个交易日收盘价和成交量。
- 最近一期营业收入和归母净利润。
- 最新 PE/PB。
- 最近一个涨停日及次日开盘价。

交叉验证仅用于确认数量级和字段解释，不在生产任务中频繁抓取多个网页。

### 15.3 风险日志

```text
risk_id, detected_at, category, interface_name, symbol,
severity, description, impact, mitigation, status
```

---

## 16. 阶段十六：最终报告结构

最终《AKShare 数据搭建报告》建议目录：

1. 项目概述
2. 测试范围与样本
3. 环境搭建
4. AKShare 版本及接口盘点
5. 数据获取流程
6. 接口测试结果与成功率
7. 数据存储架构
8. 数据库表设计与展示
9. 数据清洗规则
10. 测试数据呈现
11. 均线与量价指标
12. 股票活跃度分析
13. 一年涨跌停统计及事件后表现
14. 横盘震荡与疑似洗盘风格分析
15. 基本面和估值分析
16. ETHUSDT 能力验证
17. 数据质量结果
18. 风险点与限制
19. 后续优化建议
20. 附录：接口参数、字段字典、SQL 和运行日志

---

## 17. 分阶段验收清单

### 环境与接口

- [ ] Python 和 AKShare 可正常运行。
- [ ] 所有 16 只股票完成代码映射。
- [ ] 日线、实时、财务、资金流和涨跌停接口完成冒烟测试。
- [ ] ETH/ETHUSDT 返回情况有证据记录。

### 数据与数据库

- [ ] Raw 文件可追溯。
- [ ] Clean 数据字段和单位统一。
- [ ] DuckDB/SQLite 数据库可查询。
- [ ] 主键唯一、日期合理、OHLC 合法。
- [ ] 抓取日志和质量结果已入库。

### 指标与分析

- [ ] 7 组均线全部计算。
- [ ] 活跃度评分可解释。
- [ ] 一年涨停/跌停次数完成。
- [ ] 涨停次日开盘和后续收益完成。
- [ ] 横盘与震荡风格完成。
- [ ] 财务和估值摘要完成。

### 报告

- [ ] 流程、环境、搭建过程完整。
- [ ] 风险点和能力缺口明确。
- [ ] 测试数据和数据库有展示。
- [ ] 数据清洗需求有明细。
- [ ] 所有结论标注数据来源、时间范围和计算口径。

## 18. 参考资料

- [AKShare GitHub 仓库](https://github.com/akfamily/akshare)
- [AKShare README](https://github.com/akfamily/akshare/blob/main/README.md)
- [AKShare 安装与项目说明](https://akshare.akfamily.xyz/introduction.html)
- [AKShare 股票数据接口文档](https://akshare.akfamily.xyz/data/stock/stock.html)
- [AKShare 加密货币接口文档](https://akshare.akfamily.xyz/data/dc/dc.html)

