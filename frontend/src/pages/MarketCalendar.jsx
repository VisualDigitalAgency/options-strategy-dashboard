import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { rpc } from '../rpc'
import { shortDate } from '../format'
import { EVENT_LABEL } from '../events'

const RANGES = [30, 60, 90, 120]
const TYPES = ['all', 'results', 'dividend', 'split', 'bonus', 'agm', 'buyback', 'board_meeting']

export default function MarketCalendar() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [symbol, setSymbol] = useState('all')
  const [type, setType] = useState('all')
  const [days, setDays] = useState(90)

  useEffect(() => { rpc('get_market_calendar').then(setData).catch((e) => setError(e.message)) }, [])

  const symbols = useMemo(() => [...new Set((data?.events ?? []).map((e) => e.symbol))].sort(), [data])
  const events = (data?.events ?? []).filter(
    (e) => e.days_away <= days && (symbol === 'all' || e.symbol === symbol) && (type === 'all' || e.type === type),
  )
  const holidays = (data?.holidays ?? []).filter((h) => !data || h.date >= data.today)

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Market calendar</h1>
          <p className="muted">NSE trading holidays and Nifty 50 corporate events. Results and ex-dividend dates can gap a stock through a short strike.</p>
        </div>
      </div>
      {error && <div className="alert" role="alert">{error}</div>}
      {data?.errors?.length > 0 && (
        <p className="muted" role="status">NSE didn&apos;t return {data.errors.join(', ')} on the last refresh; showing the previous copy.</p>
      )}
      {data && !data.fetched_at && <p className="muted" role="status">The calendar hasn&apos;t been fetched yet. The worker loads it within a few minutes.</p>}

      <section className="cal-section" aria-labelledby="cal-events">
        <h2 id="cal-events">Corporate events</h2>
        <div className="cal-filters">
          <label className="select">
            <span className="sr-only">Stock</span>
            <select value={symbol} onChange={(e) => setSymbol(e.target.value)} aria-label="Stock">
              <option value="all">All stocks</option>
              {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label className="select">
            <span className="sr-only">Event type</span>
            <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Event type">
              {TYPES.map((t) => <option key={t} value={t}>{t === 'all' ? 'All events' : EVENT_LABEL[t]}</option>)}
            </select>
          </label>
          <div className="segmented small" role="group" aria-label="Date range">
            {RANGES.map((r) => (
              <button key={r} type="button" className={days === r ? 'active' : ''} aria-pressed={days === r} onClick={() => setDays(r)}>{r}d</button>
            ))}
          </div>
        </div>
        {data && !events.length && <p className="muted">No events in this range.</p>}
        {events.length > 0 && (
          <ul className="cal-list" aria-label="Corporate events">
            {events.map((e) => (
              <li key={`${e.symbol}-${e.type}-${e.date}`} className={e.risky ? 'risky' : ''}>
                <span className="cal-date num">{shortDate(e.date)}<small>{e.days_away === 0 ? 'today' : `${e.days_away}d`}</small></span>
                <Link to={`/stock/${encodeURIComponent(e.symbol)}`} className="sym">{e.symbol}</Link>
                <span className={`chip ev-chip ${e.risky ? 'risky' : ''}`}>{EVENT_LABEL[e.type] ?? e.type}</span>
                <span className="cal-purpose muted">{e.purpose}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="cal-section" aria-labelledby="cal-holidays">
        <h2 id="cal-holidays">NSE trading holidays</h2>
        {data && !holidays.length && <p className="muted">No upcoming holidays listed.</p>}
        {holidays.length > 0 && (
          <ul className="cal-list" aria-label="Trading holidays">
            {holidays.map((h) => (
              <li key={h.date}>
                <span className="cal-date num">{shortDate(h.date)}<small>{h.day}</small></span>
                <span className="cal-purpose">{h.description}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
