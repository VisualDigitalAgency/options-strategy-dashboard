import { useMemo, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { ArrowDown, ArrowUp, ChevronRight, Search, AlertCircle } from 'lucide-react'
import { useScreen } from '../screen'
import { useBudget } from '../settings'
import { ActionBadge, ProbMeter, SentimentBadge } from '../components/Badges'
import { addDaysIso, longDate, num, pct, rupee, suggestLots, todayIso } from '../format'
import DecayCurve from '../components/DecayCurve'

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
  { key: 'sentiment', label: 'Sentiment', get: (c) => c.sentiment?.score ?? -9 },
  { key: 'action', label: 'Setup', get: (c) => c.legs.length },
  { key: 'pop', label: 'POP', get: (c) => c.strategy?.pop ?? -1, num: true },
  { key: 'mpp', label: 'Max P prob.', get: (c) => c.strategy?.max_profit_prob ?? -1, num: true },
  { key: 'profit', label: 'Profit / lot', get: (c) => c.strategy?.max_profit ?? -1, num: true },
  { key: 'margin', label: 'Margin / lot', get: (c) => c.strategy?.margin ?? Infinity, num: true },
  { key: 'roi', label: 'ROI', get: (c) => c.strategy?.roi_pct ?? -1, num: true },
  { key: 'lots', label: 'Lots', get: (c) => c._lots, num: true },
  { key: 'pcr', label: 'PCR', get: (c) => c.pcr ?? 9, num: true },
]

const SK_WIDTHS = ['70%', '60%', '55%', '80%', '45%', '65%', '70%', '50%', '35%', '45%']

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
  const { data, loading, error, load } = useScreen()
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

  const rows = useMemo(() => {
    const col = COLUMNS.find((c) => c.key === sort.key)
    return candidates
      .filter((c) => matches(c, filter))
      .filter((c) => mood === 'all' || c.sentiment?.label === mood)
      .filter((c) => c.symbol.toLowerCase().includes(query.trim().toLowerCase()))
      .sort((a, b) => {
        const x = col.get(a), y = col.get(b)
        const cmp = typeof x === 'string' ? x.localeCompare(y) : x - y
        return sort.dir === 'asc' ? cmp : -cmp
      })
  }, [candidates, filter, mood, query, sort])

  const actionable = candidates.filter((c) => c.legs.length > 0)
  const avgPop = actionable.length ? actionable.reduce((s, c) => s + (c.strategy?.pop ?? 0), 0) / actionable.length : null
  const best = [...actionable].sort((a, b) => (b.strategy?.roi_pct ?? 0) - (a.strategy?.roi_pct ?? 0))[0]
  const moods = ['Bullish', 'Neutral', 'Bearish'].map((m) => [m, candidates.filter((c) => c.sentiment?.label === m).length])
  const series = candidates.find((c) => c.expiry)
  const today = todayIso()
  const slIso = addDaysIso(today, 15)

  const firstLoad = candidates.length === 0 && (loading || !data)
  // While batches are in flight, hold space for the next few stocks so rows slot in without a jump.
  const pending = firstLoad ? 6 : loading && progress ? Math.min(progress.total - progress.done, 4) : 0

  const toggleSort = (key) =>
    setSort((s) => ({ key, dir: s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }))
  const counts = Object.fromEntries(FILTERS.map(([k]) => [k, candidates.filter((c) => matches(c, k)).length]))

  return (
    <>
      <section className="hero-band" aria-label="Series summary">
        <div className="hero-copy">
          <h1 className="display">{series ? `The ${longDate(series.expiry)} series` : 'Scanning the Nifty 50'}</h1>
          <p className="lede">
            {series
              ? `${series.dte} days of time decay to sell across ${candidates.length} stocks. Stops arm on ${longDate(slIso)}, fifteen days in.`
              : 'Pulling option chains, lot sizes and the NSE margin file for every stock in the index.'}
          </p>
        </div>

        <dl className="hero-facts">
          {firstLoad ? (
            Array.from({ length: 4 }, (_, i) => (
              <div key={i}>
                <span className="skeleton" style={{ width: '60%', height: 12 }} />
                <span className="skeleton" style={{ width: '45%', height: 30, marginTop: 8 }} />
              </div>
            ))
          ) : (
            <>
              <div>
                <dt>Setups ready</dt>
                <dd className="display-num">{actionable.length}<small> of {candidates.length}</small></dd>
              </div>
              <div>
                <dt>Average POP</dt>
                <dd className="display-num">{avgPop != null ? pct(avgPop) : '—'}</dd>
              </div>
              <div>
                <dt>Best return on margin</dt>
                <dd className="display-num">{best ? pct(best.strategy?.roi_pct, 2) : '—'}</dd>
                {best && <p className="fact-note">{best.symbol}, {rupee(best.strategy?.max_profit)} a lot</p>}
              </div>
              <div>
                <dt>Sentiment</dt>
                <dd>
                  <span className="split" aria-hidden>
                    {moods.map(([m, n]) => (
                      <span key={m} className={`split-${m.toLowerCase()}`} style={{ flexGrow: n || 0.0001 }} />
                    ))}
                  </span>
                </dd>
                <p className="fact-note">{moods.map(([m, n]) => `${n} ${m.toLowerCase()}`).join(', ')}</p>
              </div>
            </>
          )}
        </dl>

        {series ? (
          <DecayCurve start={today} slDate={slIso} expiry={series.expiry} />
        ) : (
          <span className="skeleton decay-sk" aria-hidden />
        )}
      </section>

      {error && (
        <div className="alert" role="alert">
          <AlertCircle size={18} aria-hidden />
          <span>Couldn't reach the screening server ({error}). Start it with <code>python server.py</code>.</span>
          <button className="btn" onClick={() => load()}>Retry</button>
        </div>
      )}

      {loading && (
        <div className="progress" role="status" aria-live="polite">
          <div className="progress-text">
            <span>
              {progress?.batch
                ? <>Screening batch <b className="num">{progress.batch}</b> of <b className="num">{progress.batches}</b></>
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
                  className={c.num ? 'num' : ''}
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
              const go = () => navigate(`/stock/${encodeURIComponent(c.symbol)}`)
              return (
                <tr key={c.symbol} className={c.legs.length ? 'row' : 'row dim'} onClick={go}>
                  <td>
                    <Link to={`/stock/${encodeURIComponent(c.symbol)}`} className="sym" onClick={(e) => e.stopPropagation()}>
                      {c.symbol}
                    </Link>
                    <span className="sub mono">{num(c.spot)}</span>
                  </td>
                  <td><SentimentBadge sentiment={c.sentiment} /></td>
                  <td>
                    <ActionBadge action={c.action} />
                    {c.legs.length > 0 && (
                      <span className="sub mono">{c.legs.map((l) => `${l.strike}${l.side}`).join(' / ')}</span>
                    )}
                  </td>
                  <td className="num"><ProbMeter value={s?.pop} label="POP" /></td>
                  <td className="num mono">{pct(s?.max_profit_prob)}</td>
                  <td className="num mono">{rupee(s?.max_profit)}</td>
                  <td className="num mono">{rupee(s?.margin)}</td>
                  <td className="num mono">{pct(s?.roi_pct, 2)}</td>
                  <td className={`num mono ${s?.margin && c._lots === 0 ? 'warn' : ''}`} title={s?.margin && c._lots === 0 ? 'One lot needs more margin than your per-trade limit' : undefined}>
                    {s?.margin ? c._lots : '—'}
                  </td>
                  <td className="num mono">{num(c.pcr, 3)}</td>
                  <td className="chev"><ChevronRight size={16} aria-hidden /></td>
                </tr>
              )
            })}
            {pending > 0 && <SkeletonRows count={pending} />}
          </tbody>
        </table>
        {data && !loading && rows.length === 0 && (
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
          <li key={c.symbol}>
            <Link to={`/stock/${encodeURIComponent(c.symbol)}`} className={`m-card ${c.legs.length ? '' : 'dim'}`}>
              <div className="m-card-head">
                <span className="sym">{c.symbol}</span>
                <ActionBadge action={c.action} />
              </div>
              <div className="m-card-row">
                <SentimentBadge sentiment={c.sentiment} />
                <span className="mono muted">Spot {num(c.spot)}</span>
              </div>
              {c.strategy && (
                <div className="m-card-stats">
                  <span><em>POP</em><b className="mono">{pct(c.strategy.pop)}</b></span>
                  <span><em>Max profit</em><b className="mono">{rupee(c.strategy.max_profit)}</b></span>
                  <span><em>Margin</em><b className="mono">{rupee(c.strategy.margin)}</b></span>
                  <span><em>Lots</em><b className={`mono ${c.strategy.margin && c._lots === 0 ? 'warn' : ''}`}>{c.strategy.margin ? c._lots : '—'}</b></span>
                </div>
              )}
            </Link>
          </li>
        ))}
        {pending > 0 && <SkeletonCards count={pending} />}
      </ul>
    </>
  )
}
