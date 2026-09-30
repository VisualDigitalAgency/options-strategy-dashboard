import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, CalendarDays, CalendarOff, CalendarRange, Coins, FileChartColumn, Search, Wallet } from 'lucide-react'
import { rpc } from '../rpc'
import UpdatedTag from '../components/UpdatedTag'
import EventTable from '../components/EventTable'
import EconomicCalendar from '../components/EconomicCalendar'
import { dayDate, dayMonth } from '../events'

// Results and dividends can gap a stock through a short strike; the rest (splits, bonuses,
// buybacks, AGMs, board meetings) are listed under corporate actions.
const FILTERS = [['risky', 'Results & dividends'], ['actions', 'Corporate actions'], ['all', 'All']]
const matches = (e, f) => f === 'all' || (f === 'risky' ? e.risky : !e.risky)

const weekend = (iso) => [0, 6].includes(new Date(`${iso}T00:00:00`).getDay())
const names = (list) => {
  const s = [...new Set(list.map((e) => e.symbol))]
  return s.length ? `${s.slice(0, 3).join(', ')}${s.length > 3 ? ` +${s.length - 3}` : ''}` : 'None'
}

// Events grouped by the expiry cycle they land in: each event goes to the first expiry on or after
// it. Events past the last screened expiry form a trailing "later" group.
function byCycle(events, expiries) {
  const groups = expiries.map((expiry, i) => ({ expiry, from: expiries[i - 1] ?? null, events: [] }))
  const later = { expiry: null, from: expiries.at(-1) ?? null, events: [] }
  for (const e of events) (groups.find((g) => e.date <= g.expiry) ?? later).events.push(e)
  return [...groups, later].filter((g) => g.events.length)
}

export default function MarketCalendar() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [held, setHeld] = useState(() => new Set())
  const [filter, setFilter] = useState('risky')
  const [query, setQuery] = useState('')

  useEffect(() => {
    rpc('get_market_calendar').then(setData).catch((e) => setError(e.message))
    // "Held" tags come from the virtual account's cached snapshot; the page works without them.
    rpc('va_get_positions').then((p) => setHeld(new Set((p?.groups ?? []).map((g) => g.symbol)))).catch(() => {})
  }, [])

  const all = useMemo(() => data?.events ?? [], [data])
  const expiries = data?.expiries ?? []
  const next = expiries[0]
  const dte = next && data ? Math.round((new Date(`${next}T00:00:00`) - new Date(`${data.today}T00:00:00`)) / 86400000) : null
  const inNext = next ? all.filter((e) => e.date <= next) : []
  const results = inNext.filter((e) => e.type === 'results')
  const dividends = inNext.filter((e) => e.type === 'dividend')
  const heldHit = [...new Set(inNext.filter((e) => held.has(e.symbol)).map((e) => e.symbol))]

  const holidays = (data?.holidays ?? []).filter((h) => !data || h.date >= data.today)
  const nextHoliday = holidays.find((h) => !weekend(h.date))

  const q = query.trim().toUpperCase()
  const counts = Object.fromEntries(FILTERS.map(([k]) => [k, all.filter((e) => matches(e, k)).length]))
  const shown = all.filter((e) => matches(e, filter) && (!q || e.symbol.includes(q)))
  const cycles = byCycle(shown, expiries)

  return (
    <>
      <header className="screen-head">
        <div>
          <h1>Market calendar</h1>
          <p className="muted">NSE trading holidays and Nifty 50 corporate events, grouped by the expiry they fall before.</p>
          {data?.fetched_at && <UpdatedTag ts={data.fetched_at} label="Fetched" />}
        </div>
      </header>

      {error && <div className="alert" role="alert"><AlertCircle size={18} aria-hidden /><span>Couldn&apos;t load the calendar ({error}).</span></div>}
      {data && !data.fetched_at && (
        <div className="alert neutral" role="status"><AlertCircle size={18} aria-hidden /><span>The calendar hasn&apos;t been fetched yet. The worker loads it within a few minutes.</span></div>
      )}
      {data?.errors?.length > 0 && (
        <div className="alert neutral" role="status"><AlertCircle size={18} aria-hidden /><span>NSE didn&apos;t return {data.errors.join(', ')} on the last refresh. Showing the previous copy.</span></div>
      )}

      <dl className="session cal-session" aria-label="Summary">
        <div>
          <dt><CalendarDays size={13} aria-hidden />Next expiry</dt>
          <dd>{next ? dayMonth(next) : '—'}</dd>
          <p>{next ? <><span className="num">{dte}</span> days, <span className="num">{inNext.length}</span> event{inNext.length === 1 ? '' : 's'} before it</> : 'Waiting for the first screen'}</p>
        </div>
        <div>
          <dt><FileChartColumn size={13} aria-hidden />Results</dt>
          <dd>{next ? <><span className="num">{results.length}</span> <small>before expiry</small></> : '—'}</dd>
          <p>{next ? names(results) : '—'}</p>
        </div>
        <div>
          <dt><Coins size={13} aria-hidden />Ex-dividend</dt>
          <dd>{next ? <><span className="num">{dividends.length}</span> <small>before expiry</small></> : '—'}</dd>
          <p>{next ? names(dividends) : '—'}</p>
        </div>
        <div>
          <dt><Wallet size={13} aria-hidden />Your positions</dt>
          <dd className={heldHit.length ? 'warn' : ''}>{held.size ? <><span className="num">{heldHit.length}</span> <small>of {held.size} with an event</small></> : '—'}</dd>
          <p>{held.size ? names(heldHit.map((symbol) => ({ symbol }))) : 'No open positions'}</p>
        </div>
        <div>
          <dt><CalendarOff size={13} aria-hidden />Next holiday</dt>
          <dd>{nextHoliday ? dayDate(nextHoliday.date) : '—'}</dd>
          <p>{nextHoliday?.description ?? 'None listed'}</p>
        </div>
      </dl>

      <section className="toolbar" aria-label="Filters">
        <div className="segmented" role="group" aria-label="Event filter">
          {FILTERS.map(([k, label]) => (
            <button key={k} type="button" className={filter === k ? 'active' : ''} aria-pressed={filter === k} onClick={() => setFilter(k)}>
              {label} <span className="count mono">{data ? counts[k] : ''}</span>
            </button>
          ))}
        </div>
        <div className="toolbar-right">
          <label className="search">
            <Search size={16} aria-hidden />
            <span className="sr-only">Search stock</span>
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search symbol" />
          </label>
        </div>
      </section>

      <div className="cal-layout">
        <div className="cal-cycles">
          {cycles.map((g) => (
            <section key={g.expiry ?? 'later'} className="card cal-cycle" aria-label={g.expiry ? `${dayMonth(g.expiry)} expiry` : 'Later'}>
              <header className="card-head">
                <h2><CalendarRange size={16} aria-hidden />{g.expiry ? `${dayMonth(g.expiry)} expiry` : `After ${dayMonth(g.from)}`}</h2>
                <span className="muted small num">
                  {g.from ? `${dayMonth(g.from)} – ${g.expiry ? dayMonth(g.expiry) : 'later'}` : `Up to ${dayMonth(g.expiry)}`} · {g.events.length} event{g.events.length === 1 ? '' : 's'}
                </span>
              </header>
              <EventTable events={g.events} held={held} label={g.expiry ? `Events before the ${dayMonth(g.expiry)} expiry` : 'Later events'} />
            </section>
          ))}
          {data && !cycles.length && (
            <div className="card empty">
              <p>{all.length ? 'No events match these filters.' : 'No upcoming corporate events listed.'}</p>
              {all.length > 0 && <button type="button" className="btn ghost" onClick={() => { setFilter('all'); setQuery('') }}>Clear filters</button>}
            </div>
          )}
        </div>

        <aside className="card cal-holidays" aria-labelledby="cal-holidays">
          <header className="card-head">
            <h2 id="cal-holidays"><CalendarOff size={16} aria-hidden />Trading holidays</h2>
            <span className="muted small">NSE equity &amp; F&amp;O</span>
          </header>
          {data && !holidays.length && <p className="muted">No upcoming holidays listed.</p>}
          {holidays.length > 0 && (
            <ul className="hol-list" aria-label="Trading holidays">
              {holidays.map((h) => (
                <li key={h.date} className={weekend(h.date) ? 'weekend' : ''}>
                  <span className="hol-date num">{dayDate(h.date)}</span>
                  <span className="hol-name">{h.description}{weekend(h.date) && <span className="hol-tag">Weekend, no session lost</span>}</span>
                </li>
              ))}
            </ul>
          )}
        </aside>
      </div>

      <EconomicCalendar />
    </>
  )
}
