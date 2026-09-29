import { useEffect, useMemo, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import {
  AlertCircle, ArrowDown, ArrowUp, CalendarClock, CalendarDays, ChartColumn, ChevronRight, ChevronsUpDown,
  Database, ListChecks, Radio, Scale, Search, ShieldAlert, Target, Triangle,
} from 'lucide-react'
import { rpc } from '../rpc'
import { useScreen } from '../screen'
import { useBudget } from '../settings'
import { useMarketClock, tradingDays } from '../market'
import { ActionBadge, SentimentBadge } from '../components/Badges'
import RangeStrip from '../components/RangeStrip'
import UpdatedTag from '../components/UpdatedTag'
import { addDaysIso, num, pct, rupee, shortDate, signedPct, suggestLots, todayIso } from '../format'

const dayChange = (c) => (c.prev_close && c.spot ? ((c.spot - c.prev_close) / c.prev_close) * 100 : null)
const stripIv = (c) => (c.legs.length ? c.legs.reduce((s, l) => s + l.iv, 0) / c.legs.length : c.atm_iv)
const detailPath = (c) =>
  `/stock/${encodeURIComponent(c.symbol)}${c.expiry ? `?expiry=${encodeURIComponent(c.expiry)}` : ''}`
const rowKey = (c) => `${c.symbol}-${c.expiry ?? ''}`
const room = (c) => (c.legs.length ? Math.min(...c.legs.map((l) => Math.abs(l.distance_pct))) : -1)

/** One short line on why a stock produced no trade, from its first failed rule. */
export function skipReason(c) {
  const f = c.checks?.find((k) => k.status === 'fail')
  if (!f) return null
  return f.detail
    .replace(/, leg dropped$/, '')
    .replace(/ \(\d+ touches\)/, '')
    .replace(' is outside ', ' outside ')
    .replace(' sits in ', ' in ')
    .replace(/ zone ~/, ' ~')
}

const FILTERS = [
  ['actionable', 'Actionable'],
  ['strangle', 'Strangle'],
  ['ce', 'CE only'],
  ['pe', 'PE only'],
  ['skip', 'Skipped'],
  ['all', 'All'],
]

const matches = (c, f) =>
  f === 'all' ||
  (f === 'actionable' && c.legs.length > 0) ||
  (f === 'strangle' && c.action === 'SELL STRANGLE') ||
  (f === 'ce' && c.action === 'SELL CE ONLY') ||
  (f === 'pe' && c.action === 'SELL PE ONLY') ||
  (f === 'skip' && c.legs.length === 0)

const COLUMNS = [
  { key: 'symbol', label: 'Stock', get: (c) => c.symbol },
  { key: 'expiry', label: 'Expiry', get: (c) => c.dte ?? 999, num: true },
  { key: 'sentiment', label: 'Trend', get: (c) => c.sentiment?.score ?? -9 },
  { key: 'action', label: 'Setup', get: (c) => c.legs.length },
  { key: 'room', label: 'Room to strike', get: room, wide: true },
  { key: 'pop', label: 'POP', get: (c) => c.strategy?.pop ?? -1, num: true },
  { key: 'iv', label: 'IV', get: (c) => stripIv(c) ?? -1, num: true },
  { key: 'profit', label: 'Credit / lot', get: (c) => c.strategy?.max_profit ?? -1, num: true },
  { key: 'margin', label: 'Margin / lot', get: (c) => c.strategy?.margin ?? Infinity, num: true },
  { key: 'roi', label: 'ROI', get: (c) => c.strategy?.roi_pct ?? -1, num: true },
  { key: 'lots', label: 'Lots', get: (c) => c._lots, num: true },
  { key: 'pcr', label: 'PCR', get: (c) => c.pcr ?? 9, num: true },
]

const SK_WIDTHS = ['50%', '60%', '55%', '90%', '60%', '45%', '65%', '70%', '50%', '35%', '45%']

function SkeletonRows({ count }) {
  return Array.from({ length: count }, (_, i) => (
    <tr key={`sk${i}`} className="skeleton-row" aria-hidden>
      <td>
        <span className="skeleton" style={{ width: 90 }} />
        <span className="skeleton sk-sub" style={{ width: 56 }} />
      </td>
      {COLUMNS.slice(1).map((c, j) => (
        <td key={c.key} className={c.num ? 'num' : ''}>
          <span className={`skeleton ${c.num ? 'sk-right' : ''}`} style={{ width: SK_WIDTHS[j] }} />
        </td>
      ))}
      <td />
    </tr>
  ))
}

function SkeletonCards({ count }) {
  return Array.from({ length: count }, (_, i) => (
    <li key={`sk${i}`} aria-hidden>
      <div className="m-card sk-card">
        <div className="m-card-head">
          <span className="skeleton" style={{ width: 110, height: 18 }} />
          <span className="skeleton sk-pill" />
        </div>
        <div className="m-card-row">
          <span className="skeleton sk-pill" style={{ width: 84 }} />
          <span className="skeleton" style={{ width: 96 }} />
        </div>
        <div className="m-card-stats">
          {[0, 1, 2, 3].map((k) => (
            <span key={k}>
              <span className="skeleton" style={{ width: '60%', height: 10 }} />
              <span className="skeleton" style={{ width: '80%', height: 14, marginTop: 6 }} />
            </span>
          ))}
        </div>
      </div>
    </li>
  ))
}

export default function Overview() {
  const { data, loading, refreshing, error, load } = useScreen()
  const { perTrade } = useBudget()
  const navigate = useNavigate()
  const [filter, setFilter] = useState('actionable')
  const [mood, setMood] = useState('all')
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState({ key: 'pop', dir: 'desc' })

  const progress = data?.progress
  const candidates = useMemo(
    () => (data?.candidates ?? []).map((c) => ({ ...c, _lots: suggestLots(c.strategy?.margin, perTrade) })),
    [data, perTrade],
  )

  const [minDte, setMinDte] = useState(null)
  // Every expiry cycle the backend screened (several per stock) at or past the slider's floor.
  const inRange = useMemo(
    () => candidates.filter((c) => minDte == null || c.dte == null || c.dte >= minDte),
    [candidates, minDte],
  )

  const rows = useMemo(() => {
    const col = COLUMNS.find((c) => c.key === sort.key)
    return inRange
      .filter((c) => matches(c, filter))
      .filter((c) => mood === 'all' || c.sentiment?.label === mood)
      .filter((c) => c.symbol.toLowerCase().includes(query.trim().toLowerCase()))
      .sort((a, b) => {
        const x = col.get(a), y = col.get(b)
        const cmp = typeof x === 'string' ? x.localeCompare(y) : x - y
        return sort.dir === 'asc' ? cmp : -cmp
      })
  }, [inRange, filter, mood, query, sort])

  const actionable = inRange.filter((c) => c.legs.length > 0)
  const avgPop = actionable.length ? actionable.reduce((s, c) => s + (c.strategy?.pop ?? 0), 0) / actionable.length : null
  const best = [...actionable].sort((a, b) => (b.strategy?.roi_pct ?? 0) - (a.strategy?.roi_pct ?? 0))[0]
  // Trend is per stock, not per expiry cycle: count each stock once.
  const perStock = [...new Map(candidates.map((c) => [c.symbol, c])).values()]
  const moods = ['Bullish', 'Neutral', 'Bearish'].map((m) => [m, perStock.filter((c) => c.sentiment?.label === m).length])
  // Nearest cycle still shown under the Expiry slider.
  const series = inRange.filter((c) => c.expiry).sort((a, b) => a.dte - b.dte)[0]
  const today = todayIso()
  const clock = useMarketClock()
  const [cfg, setCfg] = useState(null)
  useEffect(() => { rpc('get_config').then(setCfg).catch(() => {}) }, [])
  // Opens on every screened cycle, nearest (under the strategy's 30-day entry) included.
  useEffect(() => { if (cfg && minDte == null) setMinDte(cfg.screen_dte_range?.[0] ?? 20) }, [cfg]) // eslint-disable-line react-hooks/exhaustive-deps
  const baseDte = cfg?.min_dte ?? 30
  const [dteFloor, dteCeil] = cfg?.screen_dte_range ?? [20, 90]
  const grace = cfg?.sl_grace_days ?? 15
  const slIso = addDaysIso(today, grace)
  const scanned = data?.generated_at
    ? new Date(data.generated_at * 1000).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false })
    : null

  // Placeholders only before the first screen ever lands; later refreshes swap rows in place.
  const firstLoad = candidates.length === 0 && loading
  const pending = firstLoad ? 6 : 0

  const toggleSort = (key) =>
    setSort((s) => ({ key, dir: s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }))
  const counts = Object.fromEntries(FILTERS.map(([k]) => [k, inRange.filter((c) => matches(c, k)).length]))

  return (
    <>
      <header className="screen-head">
        <div>
          <h1>Screener</h1>
          <p className="muted">Short OTM options on the Nifty 50, picked by highest OI and filtered by these rules.</p>
          <UpdatedTag ts={data?.generated_at} refreshing={refreshing} />
        </div>
        <ul className="rules" aria-label="Screening rules">
          <li className="rule-slider" title={`Only show expiry cycles at least this many days out. Every monthly expiry ${dteFloor}–${dteCeil} days out is screened for each stock; drag up to hide the nearer cycles. Cycles under ${baseDte} days are shown but outside the strategy's entry rule: auto-trade only opens cycles ${baseDte}+ days out.`}>
            <CalendarClock size={14} strokeWidth={2} aria-hidden />
            <span className="rule-label">Expiry</span>
            <input
              type="range"
              className="dte-slider"
              min={dteFloor}
              max={dteCeil}
              step={1}
              value={minDte ?? dteFloor}
              onChange={(e) => setMinDte(Number(e.target.value))}
              aria-label="Minimum days to expiry"
            />
            <b className="num">{'≥'} {minDte ?? dteFloor} days</b>
          </li>
          {[
            [Triangle, 'Delta', `< ${cfg?.delta_max_abs ?? 0.15}`, 'Strike must have |delta| below this'],
            [Scale, 'PCR', cfg ? `${cfg.pcr_range[0]}–${cfg.pcr_range[1]}` : '0.4–0.7', 'Put-call OI ratio range for the stock'],
            [ChevronsUpDown, 'S/R zone', `±${cfg?.sr_zone_width_pct ?? 1.5}%`, 'A strike inside a swing S/R zone drops that leg'],
            [ShieldAlert, 'Stop loss', `from day ${grace}`, 'Stop at premium collected, armed after the grace period'],
          ].map(([Icon, label, value, tip]) => (
            <li key={label} title={tip}>
              <Icon size={14} strokeWidth={2} aria-hidden />
              <span className="rule-label">{label}</span>
              <b className="num">{value}</b>
            </li>
          ))}
        </ul>
      </header>

      <dl className="session" aria-label="Session">
        <div>
          <dt><Radio size={13} aria-hidden />NSE</dt>
          <dd><span className={`mkt-dot ${clock.key}`} aria-hidden />{clock.label} <span className="num">{clock.time}</span> <small>IST</small></dd>
          <p>{clock.note}</p>
        </div>
        <div>
          <dt><CalendarDays size={13} aria-hidden />Series</dt>
          <dd>{series ? shortDate(series.expiry) : <span className="skeleton" style={{ width: 70 }} />}</dd>
          <p>{series ? <><span className="num">{series.dte}</span> days, ≈<span className="num">{tradingDays(today, series.expiry)}</span> sessions</> : 'Monthly, 30+ days out'}</p>
        </div>
        <div>
          <dt><ShieldAlert size={13} aria-hidden />Stops arm</dt>
          <dd>{shortDate(slIso)}</dd>
          <p>Day {grace}{series ? ` of ${series.dte}` : ''}</p>
        </div>
        <div>
          <dt><ListChecks size={13} aria-hidden />Setups</dt>
          <dd><span className="num">{actionable.length}</span> <small>of {inRange.length || 50}</small></dd>
          <p className="num">{counts.strangle} strangle, {counts.ce} CE, {counts.pe} PE</p>
        </div>
        <div>
          <dt><Target size={13} aria-hidden />Avg POP</dt>
          <dd className="num">{avgPop != null ? pct(avgPop) : '—'}</dd>
          <p>{best ? <>Best ROI {best.symbol} <span className="num">{pct(best.strategy?.roi_pct, 2)}</span></> : '—'}</p>
        </div>
        <div className="session-breadth">
          <dt><ChartColumn size={13} aria-hidden />Trend breadth</dt>
          <dd>
            <span className="split" aria-hidden>
              {moods.map(([m, n]) => (
                <span key={m} className={`split-${m.toLowerCase()}`} style={{ flexGrow: n || 0.0001 }} />
              ))}
            </span>
          </dd>
          <p className="num">{moods.map(([m, n]) => `${n} ${m === 'Bullish' ? 'up' : m === 'Bearish' ? 'down' : 'flat'}`).join(', ')}</p>
        </div>
        <div>
          <dt><Database size={13} aria-hidden />Data</dt>
          <dd>{scanned ? <>Scanned <span className="num">{scanned}</span></> : 'Scanning…'}</dd>
          <p title="NSE SPAN risk-parameter file used for margin">{data?.span_source ? data.span_source.replace(/\.zip$/, '') : 'NSE option chain'}</p>
        </div>
      </dl>

      {error && (
        <div className="alert" role="alert">
          <AlertCircle size={18} aria-hidden />
          <span>Couldn't reach the screening server ({error}). Start it with <code>python server.py</code>.</span>
          <button className="btn" onClick={() => load()}>Retry</button>
        </div>
      )}

      {firstLoad && (
        <div className="progress" role="status" aria-live="polite">
          <div className="progress-text">
            <span>
              {progress?.batch
                ? <>
                    {progress.pass ? <>Expiry month <b className="num">{progress.pass}</b> of <b className="num">{progress.passes}</b>, batch</> : 'Screening batch'}{' '}
                    <b className="num">{progress.batch}</b> of <b className="num">{progress.batches}</b>
                  </>
                : 'Loading NSE margin file…'}
            </span>
            <span className="mono">{progress?.done ?? 0} / {progress?.total || 50} stocks</span>
          </div>
          <div className="progress-track" aria-hidden>
            <div className="progress-fill" style={{ transform: `scaleX(${progress?.total ? progress.done / progress.total : 0.02})` }} />
          </div>
        </div>
      )}
      {progress?.error && (
        <div className="alert" role="alert">
          <AlertCircle size={18} aria-hidden /> Screen stopped early: {progress.error}
          <button className="btn" onClick={() => load(true)}>Retry</button>
        </div>
      )}

      <section className="toolbar" aria-label="Filters">
        <div className="segmented" role="group" aria-label="Setup filter">
          {FILTERS.map(([k, label]) => (
            <button key={k} className={filter === k ? 'active' : ''} aria-pressed={filter === k} onClick={() => setFilter(k)}>
              {label} <span className="count mono">{data ? counts[k] : ''}</span>
            </button>
          ))}
        </div>
        <div className="toolbar-right">
          <label className="select">
            <span className="sr-only">Sentiment</span>
            <select value={mood} onChange={(e) => setMood(e.target.value)}>
              <option value="all">All sentiment</option>
              <option>Bullish</option>
              <option>Neutral</option>
              <option>Bearish</option>
            </select>
          </label>
          <label className="search">
            <Search size={16} aria-hidden />
            <span className="sr-only">Search stock</span>
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search symbol" />
          </label>
        </div>
      </section>

      <div className="table-card">
        <table className="grid-table">
          <thead>
            <tr>
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  className={c.num ? 'num' : c.wide ? 'wide' : ''}
                  aria-sort={sort.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                >
                  <button className="sort" onClick={() => toggleSort(c.key)}>
                    {c.label}
                    {sort.key === c.key && (sort.dir === 'asc' ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
                  </button>
                </th>
              ))}
              <th aria-label="Open" />
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const s = c.strategy
              const go = () => navigate(detailPath(c))
              const chg = dayChange(c)
              const reason = c.legs.length ? null : skipReason(c)
              return (
                <tr key={rowKey(c)} className={c.legs.length ? 'row' : 'row dim'} onClick={go}>
                  <td>
                    <Link to={detailPath(c)} className="sym" onClick={(e) => e.stopPropagation()}>
                      {c.symbol}
                    </Link>
                    <span className="sub num">
                      {num(c.spot)} <span className={chg > 0 ? 'pos' : chg < 0 ? 'neg' : ''}>{signedPct(chg)}</span>
                    </span>
                  </td>
                  <td className="num">
                    {shortDate(c.expiry)}
                    {c.dte != null && <span className="sub">{c.dte} days</span>}
                  </td>
                  <td><SentimentBadge sentiment={c.sentiment} /></td>
                  <td className="setup-cell">
                    <ActionBadge action={c.action} />
                    <span className="sub num" title={reason ?? undefined}>
                      {c.legs.length > 0 ? c.legs.map((l) => `${l.strike} ${l.side}`).join(' / ') : reason}
                    </span>
                  </td>
                  <td className="strip-cell">
                    <RangeStrip spot={c.spot} legs={c.legs} iv={stripIv(c)} dte={c.dte} zones={c.sr_near} />
                  </td>
                  <td className="num">
                    <span className={`pop ${s ? (s.pop >= 90 ? 'hi' : s.pop >= 80 ? 'mid' : 'lo') : ''}`}>{pct(s?.pop)}</span>
                    {s && <span className="sub">max {pct(s.max_profit_prob)}</span>}
                  </td>
                  <td className="num">{pct(stripIv(c))}</td>
                  <td className="num">{rupee(s?.max_profit)}</td>
                  <td className="num">{rupee(s?.margin)}</td>
                  <td className="num">
                    {pct(s?.roi_pct, 2)}
                    {s?.roi_annual_pct != null && <span className="sub">{pct(s.roi_annual_pct, 0)} p.a.</span>}
                  </td>
                  <td className={`num ${s?.margin && c._lots === 0 ? 'warn' : ''}`} title={s?.margin && c._lots === 0 ? 'One lot needs more margin than your per-trade limit' : undefined}>
                    {s?.margin ? c._lots : '—'}
                  </td>
                  <td className={`num ${cfg && c.pcr != null && (c.pcr < cfg.pcr_range[0] || c.pcr > cfg.pcr_range[1]) ? 'out' : ''}`}>{num(c.pcr, 2)}</td>
                  <td className="chev"><ChevronRight size={16} aria-hidden /></td>
                </tr>
              )
            })}
            {pending > 0 && <SkeletonRows count={pending} />}
          </tbody>
        </table>
        {data && !firstLoad && rows.length === 0 && (
          <div className="empty">
            <p>No stocks match these filters.</p>
            <button className="btn ghost" onClick={() => { setFilter('all'); setMood('all'); setQuery('') }}>
              Clear filters
            </button>
          </div>
        )}
      </div>

      <ul className="card-list" aria-label="Stocks">
        {rows.map((c) => (
          <li key={rowKey(c)}>
            <Link to={detailPath(c)} className={`m-card ${c.legs.length ? '' : 'dim'}`}>
              <div className="m-card-head">
                <span className="sym">
                  {c.symbol}
                  {c.expiry && <small className="m-card-exp num"> {shortDate(c.expiry)} · {c.dte}d</small>}
                </span>
                <ActionBadge action={c.action} />
              </div>
              <div className="m-card-row">
                <SentimentBadge sentiment={c.sentiment} />
                <span className="num muted">
                  {num(c.spot)} <span className={dayChange(c) > 0 ? 'pos' : dayChange(c) < 0 ? 'neg' : ''}>{signedPct(dayChange(c))}</span>
                </span>
              </div>
              <RangeStrip spot={c.spot} legs={c.legs} iv={stripIv(c)} dte={c.dte} zones={c.sr_near} />
              {c.strategy ? (
                <div className="m-card-stats">
                  <span><em>POP</em><b className="num">{pct(c.strategy.pop)}</b></span>
                  <span><em>Credit</em><b className="num">{rupee(c.strategy.max_profit)}</b></span>
                  <span><em>Margin</em><b className="num">{rupee(c.strategy.margin)}</b></span>
                  <span><em>Lots</em><b className={`num ${c.strategy.margin && c._lots === 0 ? 'warn' : ''}`}>{c.strategy.margin ? c._lots : '—'}</b></span>
                </div>
              ) : (
                <p className="m-card-reason">{skipReason(c)}</p>
              )}
            </Link>
          </li>
        ))}
        {pending > 0 && <SkeletonCards count={pending} />}
      </ul>
    </>
  )
}
