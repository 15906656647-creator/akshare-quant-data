import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import './controls.css'

const Plot = React.lazy(() => import('react-plotly.js'))

const DATA = '/data/'
const pageNames = { dashboard: '总览', detail: '证券详情', compare: '跨市场比较', screen: '非事件筛选', quality: '数据状态' }

function Status({ value }) {
  const status = value || 'UNAVAILABLE'
  return <span className={`status ${status.toLowerCase()}`}>{status}</span>
}

function useJson(path) {
  const [state, setState] = useState({ loading: true, data: null, error: null })
  useEffect(() => {
    let active = true
    setState({ loading: true, data: null, error: null })
    fetch(path).then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json() })
      .then(data => active && setState({ loading: false, data, error: null }))
      .catch(error => active && setState({ loading: false, data: null, error: error.message }))
    return () => { active = false }
  }, [path])
  return state
}

const fmt = value => value == null ? '—' : Intl.NumberFormat('zh-CN', { maximumFractionDigits: 2 }).format(value)

function Shell({ meta, page, setPage, children }) {
  return <div className="shell">
    <aside>
      <div className="brand"><span className="brandmark">A·Q</span><div><b>AKShare</b><small>市场数据实验室</small></div></div>
      <nav>{Object.entries(pageNames).map(([id, label]) => <button key={id} className={page === id ? 'active' : ''} onClick={() => setPage(id)}>{label}</button>)}</nav>
      <div className="scope"><small>授权范围</small><strong>受限 · 非事件</strong><Status value={meta.event.availability_status} /></div>
    </aside>
    <main><header><div><small>STAGE 20 / RESTRICTED</small><h1>{pageNames[page]}</h1></div><div className="asof">研究基准日 <b>{meta.analysis_as_of_date}</b></div></header>{children}</main>
  </div>
}

function Dashboard({ meta }) {
  const counts = meta.securities.reduce((a, x) => ({ ...a, [x.market]: (a[x.market] || 0) + 1 }), {})
  return <>
    <section className="hero"><div><span className="eyebrow">FORMAL DATA · GOVERNED ACCESS</span><h2>跨市场，<em>一处看清。</em></h2><p>只呈现通过正式质量门禁的行情与基本面。不可用不是零，受阻塞也不会被推断替代。</p></div><div className="pulse"><b>{meta.securities.length}</b><span>正式标的</span></div></section>
    <section className="grid metrics">
      <article><small>A 股</small><b>{counts.A || 0}</b><Status value="AVAILABLE" /></article>
      <article><small>港股</small><b>{counts.HK || 0}</b><Status value="AVAILABLE" /></article>
      <article><small>ETHUSDT</small><b>{counts.CRYPTO || 0}</b><Status value="AVAILABLE" /></article>
      <article><small>Stage 19 事件</small><b className="null">NULL</b><Status value={meta.event.availability_status} /></article>
    </section>
    <section className="two-col"><article className="panel"><h3>数据覆盖</h3>{['A', 'HK', 'CRYPTO'].map(m => <div className="barrow" key={m}><span>{m === 'CRYPTO' ? 'ETH / USDT' : m === 'HK' ? '香港市场' : 'A 股市场'}</span><div className="bar"><i style={{ width: `${Math.max(18, (counts[m] || 0) / 16 * 100)}%` }} /></div><b>{counts[m] || 0}</b></div>)}</article>
      <article className="panel blocked-card"><small>事件模块</small><h3>正式发布门禁尚未通过</h3><p>{meta.event.reason}</p><div><Status value="BLOCKED" /> <span>value = NULL</span></div></article></section>
    <section className="panel lineage"><h3>正式 Lineage</h3><div><span>Stage 17 行情</span><code>{meta.lineage.stage17_run_id}</code><Status value="PASS" /></div><div><span>Stage 18 基本面</span><code>{meta.lineage.stage18_feature_run_id}</code><Status value="PASS" /></div><div><span>数据更新时间</span><code>{meta.data_updated_at}</code><Status value="AVAILABLE" /></div></section>
  </>
}

function Selectors({ meta, symbol, setSymbol, interval, setInterval, adjustment, setAdjustment, rangeDays, setRangeDays }) {
  const security = meta.securities.find(x => x.symbol === symbol) || meta.securities[0]
  return <section className="selectors"><label>市场 / 标的<select value={symbol} onChange={e => setSymbol(e.target.value)}>{meta.securities.map(s => <option key={s.symbol} value={s.symbol}>{s.market} · {s.symbol}</option>)}</select></label><label>周期<select value={interval} onChange={e => setInterval(e.target.value)}>{security.intervals.map(x => <option key={x}>{x}</option>)}</select></label><label>时间范围<select value={rangeDays} onChange={e => setRangeDays(e.target.value)}><option value="90">最近 90 条</option><option value="250">最近 250 条</option><option value="500">最近 500 条</option><option value="all">全部正式历史</option></select></label>{security.adjustments.length > 0 && <label>复权<select value={adjustment} onChange={e => setAdjustment(e.target.value)}>{security.adjustments.map(x => <option key={x}>{x}</option>)}</select></label>}</section>
}

function Detail({ meta }) {
  const [symbol, setSymbolRaw] = useState(meta.securities[0].symbol)
  const [interval, setInterval] = useState('1d')
  const [adjustment, setAdjustment] = useState('qfq')
  const [rangeDays, setRangeDays] = useState('500')
  const [visibleMa, setVisibleMa] = useState([5, 10, 20])
  const security = meta.securities.find(x => x.symbol === symbol)
  const setSymbol = next => { const s = meta.securities.find(x => x.symbol === next); setSymbolRaw(next); setInterval(s.intervals.includes('1d') ? '1d' : s.intervals[0]); setAdjustment(s.adjustments.includes('qfq') ? 'qfq' : s.adjustments[0] || 'none') }
  const key = `${interval}:${security.adjustments.length ? adjustment : 'none'}`
  const path = meta.series[symbol]?.[key]
  const series = useJson(path ? `/${path}` : `${DATA}unavailable.json`)
  const fundamental = useJson(`/${meta.fundamentals[symbol].path}`)
  const rows = series.data?.rows || []
  const recent = rangeDays === 'all' ? rows : rows.slice(-Number(rangeDays))
  const traces = series.data ? [{ type: 'candlestick', x: recent.map(x => x.time), open: recent.map(x => x.open), high: recent.map(x => x.high), low: recent.map(x => x.low), close: recent.map(x => x.close), name: `${symbol} ${adjustment}` }, ...visibleMa.map((w, i) => ({ type: 'scatter', mode: 'lines', x: recent.map(x => x.time), y: recent.map(x => x[`ma${w}`]), name: `MA${w}`, line: { width: 1.4, color: ['#d6ff4b','#68d8d6','#ff8d70','#bc9cff','#70a1ff','#ffd166','#f78fb3'][i] } }))] : []
  return <><Selectors {...{ meta, symbol, setSymbol, interval, setInterval, adjustment, setAdjustment, rangeDays, setRangeDays }} />
    <section className="detail-head"><div><small>{security.market} · {security.currency}</small><h2>{symbol}</h2></div><div className="chips">{meta.supported_ma.map(w => <button key={w} className={visibleMa.includes(w) ? 'on' : ''} onClick={() => setVisibleMa(v => v.includes(w) ? v.filter(x => x !== w) : [...v, w])}>MA{w}</button>)}</div></section>
    {series.loading && <div className="state">正在按标的加载正式序列…</div>}{series.error && <div className="state error">该组合 UNAVAILABLE：{series.error}</div>}{series.data && <><article className="chart panel"><Plot data={traces} layout={{ autosize: true, height: 470, paper_bgcolor: 'transparent', plot_bgcolor: 'transparent', font: { color: '#dfe6e9' }, margin: { l: 48, r: 22, t: 20, b: 44 }, xaxis: { rangeslider: { visible: false }, gridcolor: '#253138' }, yaxis: { gridcolor: '#253138' }, showlegend: true }} useResizeHandler style={{ width: '100%' }} config={{ displaylogo: false, responsive: true }} /></article>
      <section className="grid metrics compact"><article><small>最新收盘</small><b>{fmt(rows.at(-1)?.close)}</b><span>{series.data.currency}</span></article><article><small>成交量</small><b>{fmt(rows.at(-1)?.volume)}</b><span>原始单位</span></article><article><small>成交额</small><b>{fmt(rows.at(-1)?.amount)}</b><span>{series.data.currency}</span></article><article><small>换手</small><b>{fmt(rows.at(-1)?.turnover)}</b><span>{rows.at(-1)?.turnover == null ? 'UNAVAILABLE' : 'ratio'}</span></article></section>
      <div className="source-note">调整口径：<b>{series.data.adjustment || 'NOT_APPLICABLE'}</b> · 数据源 Stage {series.data.source_stage} / {series.data.source_run_id} · as of {series.data.as_of_date}</div></>}
    <Fundamentals state={fundamental} /></>
}

function Fundamentals({ state }) {
  const [metric, setMetric] = useState('ALL')
  if (state.loading) return <section className="panel state">加载正式基本面…</section>
  if (state.error) return <section className="panel state error">基本面加载失败：{state.error}</section>
  const f = state.data
  const visible = metric === 'ALL' ? f.features : f.features.filter(x => x.metric === metric)
  return <section className="panel fundamentals"><div className="section-title"><div><small>STAGE 18 · PIT</small><h3>基本面快照</h3></div><div className="inline-controls">{f.features.length > 0 && <select value={metric} onChange={e => setMetric(e.target.value)}><option value="ALL">全部指标</option>{f.features.map(x => <option key={x.metric} value={x.metric}>{x.metric}</option>)}</select>}<Status value={f.availability_status} /></div></div>{f.features.length ? <div className="fund-grid">{visible.map(x => <div key={x.metric}><span>{x.metric}</span><b>{fmt(x.value)}</b><Status value={x.availability_status} /><small>{x.report_period || '—'} · 公告 {x.announcement_date || '—'}</small></div>)}</div> : <p className="muted">{f.reason}</p>}</section>
}

function Compare({ meta }) {
  const [symbols, setSymbols] = useState([meta.securities[0].symbol, meta.securities.at(-1).symbol])
  const paths = symbols.map(s => { const sec = meta.securities.find(x => x.symbol === s); const key = sec.market === 'CRYPTO' ? '1d:none' : '1d:qfq'; return meta.series[s]?.[key] })
  const first = useJson(paths[0] ? `/${paths[0]}` : `${DATA}none`); const second = useJson(paths[1] ? `/${paths[1]}` : `${DATA}none`)
  const normalized = state => { const rows = state.data?.rows || []; const valid = rows.filter(x => x.close != null); const base = valid[0]?.close; return { x: valid.map(x => x.time), y: valid.map(x => base ? (x.close / base - 1) * 100 : null) } }
  const lines = [first, second].map(normalized)
  return <><section className="selectors compare-select">{[0,1].map(i => <label key={i}>标的 {i + 1}<select value={symbols[i]} onChange={e => setSymbols(v => v.map((x,j) => j === i ? e.target.value : x))}>{meta.securities.map(s => <option key={s.symbol} value={s.symbol}>{s.market} · {s.symbol}</option>)}</select></label>)}</section><article className="panel compare-note"><b>统一为区间收益（%）</b><span>跨 CNY / HKD / USDT 不直接比较名义金额；保留各自市场货币。</span></article><article className="panel chart"><Plot data={lines.map((x,i) => ({ type: 'scatter', mode: 'lines', x: x.x, y: x.y, name: symbols[i] }))} layout={{ autosize: true, height: 500, paper_bgcolor: 'transparent', plot_bgcolor: 'transparent', font: { color: '#dfe6e9' }, margin: { l: 48, r: 22, t: 25, b: 44 }, yaxis: { title: '区间收益 %', gridcolor: '#253138' }, xaxis: { gridcolor: '#253138' } }} useResizeHandler style={{ width: '100%' }} config={{ displaylogo: false }} /></article></>
}

function Screen({ meta }) {
  const [market, setMarket] = useState('ALL'); const [symbolQuery, setSymbolQuery] = useState(''); const [minPrice, setMinPrice] = useState(''); const [minVolume, setMinVolume] = useState(''); const [minTurnover, setMinTurnover] = useState(''); const [maxPe, setMaxPe] = useState('')
  const rows = useMemo(() => meta.summaries.filter(x => market === 'ALL' || x.market === market).filter(x => !symbolQuery || x.symbol.toLowerCase().includes(symbolQuery.toLowerCase())).filter(x => minPrice === '' || x.close >= Number(minPrice)).filter(x => minVolume === '' || x.volume >= Number(minVolume)).filter(x => minTurnover === '' || x.turnover != null && x.turnover >= Number(minTurnover)), [meta, market, symbolQuery, minPrice, minVolume, minTurnover])
  return <><section className="panel screen-intro"><small>授权能力：NON_EVENT_METRIC_FILTER</small><h2>只筛选可验证的非事件字段</h2><p>事件次数、连板、事件后收益及 candidate 字段不会进入筛选层。</p></section><section className="selectors"><label>市场<select value={market} onChange={e => setMarket(e.target.value)}><option>ALL</option><option>A</option><option>HK</option><option>CRYPTO</option></select></label><label>证券代码<input value={symbolQuery} onChange={e => setSymbolQuery(e.target.value)} placeholder="例如 600763" /></label><label>最低价格<input type="number" value={minPrice} onChange={e => setMinPrice(e.target.value)} placeholder="不限制" /></label><label>最低成交量<input type="number" value={minVolume} onChange={e => setMinVolume(e.target.value)} placeholder="不限制" /></label><label>最低换手率<input type="number" value={minTurnover} onChange={e => setMinTurnover(e.target.value)} placeholder="不限制" /></label><label>PE 上限（当前不可用）<input type="number" disabled value={maxPe} onChange={e => setMaxPe(e.target.value)} placeholder="UNAVAILABLE" /></label></section><section className="panel table-wrap"><table><thead><tr><th>市场</th><th>标的</th><th>价格</th><th>货币</th><th>成交量</th><th>成交额</th><th>换手</th></tr></thead><tbody>{rows.map(x => <tr key={x.symbol}><td>{x.market}</td><td><b>{x.symbol}</b></td><td>{fmt(x.close)}</td><td>{x.currency}</td><td>{fmt(x.volume)}</td><td>{fmt(x.amount)}</td><td>{fmt(x.turnover)}</td></tr>)}</tbody></table>{!rows.length && <div className="state">没有满足条件的正式数据。</div>}</section></>
}

function Quality({ meta }) {
  return <><section className="grid metrics"><article><small>Stage 17 行情</small><b>69 / 69</b><Status value="PASS" /></article><article><small>Stage 18 Features</small><b>170 / 276</b><Status value="PASS" /></article><article><small>Stage 19 事件</small><b className="null">NULL</b><Status value="BLOCKED" /></article><article><small>Candidate 泄漏</small><b>0</b><Status value="PASS" /></article></section><section className="panel table-wrap"><table><thead><tr><th>数据集</th><th>Availability</th><th>Quality</th><th>Source stage / run</th><th>as_of_date</th><th>说明</th></tr></thead><tbody><tr><td>A/H 日线与复权</td><td><Status value="AVAILABLE" /></td><td>PASS</td><td>17 / {meta.lineage.stage17_run_id}</td><td>{meta.data_updated_at}</td><td>69 个正式数据集</td></tr><tr><td>A/H 股票分钟</td><td><Status value="UNAVAILABLE" /></td><td>NOT_RUN</td><td>17 / {meta.lineage.stage17_run_id}</td><td>{meta.data_updated_at}</td><td>探针 0/10，不属于正式出口</td></tr><tr><td>ETH 1m/3m/5m/15m/1h/1d</td><td><Status value="AVAILABLE" /></td><td>PASS</td><td>17 / {meta.lineage.stage17_run_id}</td><td>{meta.data_updated_at}</td><td>OKX 确认 K 线</td></tr><tr><td>基本面 Features</td><td><Status value="AVAILABLE" /></td><td>PASS / UNAVAILABLE</td><td>18 / {meta.lineage.stage18_feature_run_id}</td><td>{meta.analysis_as_of_date}</td><td>PIT；不可用保持 NULL</td></tr><tr><td>正式涨跌停事件</td><td><Status value="BLOCKED" /></td><td>BLOCKED</td><td>19 / formal gate</td><td>{meta.analysis_as_of_date}</td><td>{meta.event.reason}</td></tr></tbody></table></section></>
}

function App() {
  const metaState = useJson(`${DATA}metadata.json`); const [page, setPage] = useState('dashboard')
  if (metaState.loading) return <div className="boot">正在验证正式数据入口…</div>
  if (metaState.error) return <div className="boot error">Stage 20 fail closed：{metaState.error}</div>
  const meta = metaState.data
  const content = page === 'dashboard' ? <Dashboard meta={meta} /> : page === 'detail' ? <Detail meta={meta} /> : page === 'compare' ? <Compare meta={meta} /> : page === 'screen' ? <Screen meta={meta} /> : <Quality meta={meta} />
  return <React.Suspense fallback={<div className="boot">正在加载图表组件…</div>}><Shell {...{ meta, page, setPage }}>{content}</Shell></React.Suspense>
}

createRoot(document.getElementById('root')).render(<React.StrictMode><App /></React.StrictMode>)
