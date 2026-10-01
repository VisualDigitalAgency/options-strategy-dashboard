import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, BellRing, ChartCandlestick, ChevronDown, Hourglass, LineChart, LogOut, RefreshCw, SlidersHorizontal } from 'lucide-react'
import { rpc } from '../rpc'
import UpdatedTag from '../components/UpdatedTag'
import { useBudget } from '../settings'
import { num, pct, pnlClass, rupee, rupee2, int, shortDate, signed, signedRupee, todayIso } from '../format'
import DecayCurve from '../components/DecayCurve'
import { LegTag } from '../components/Badges'
import { GroupPayoff } from '../components/Charts'
import PivotLevels from '../components/PivotLevels'
import SLModeSwitch from '../components/SLModeSwitch'
import RealAccountView from '../components/RealAccountView'
import { ConfirmDialog } from '../components/Modal'
import { useTitle } from '../brand'

const POLL_MS = 30000

// Expiry payoff of the whole group at spot S: sum of qty x (intrinsic - entry price).
const payoff = (legs, S) =>
  legs.reduce((t, l) => t + l.qty * (Math.max(0, l.side === 'CE' ? S - l.strike : l.strike - S) - l.avg_price), 0)

/** Max profit and max loss at expiry, and the premium still left to decay.
 *  Payoff is piecewise linear, so its extremes sit at spot 0, a strike, or run off to infinity
 *  when the net call quantity is non-zero (short calls: unlimited loss; long calls: unlimited profit). */
/** A leg's fair value: the server's bid/ask mid (or last in-session mid after the close), never
 *  a stale last trade. Falls back to LTP only for snapshots from before marks existed. */
const legMark = (l) => l.mark ?? l.ltp

const MARK_NOTE = { mid: 'bid/ask mid', close: 'last in-session mid', ltp: 'last trade, held inside bid/ask' }

export function riskFigures(legs) {
  const points = [0, ...legs.map((l) => l.strike)].map((S) => payoff(legs, S))
  const netCalls = legs.filter((l) => l.side === 'CE').reduce((t, l) => t + l.qty, 0)
  const left = legs.every((l) => legMark(l) != null) ? legs.reduce((t, l) => t - l.qty * legMark(l), 0) : null
  return {
    maxProfit: netCalls > 0 ? Infinity : Math.max(...points),
    maxLoss: netCalls < 0 ? -Infinity : Math.min(...points),
    left, // cost to close now; for a short book this is the profit still to be earned
  }
}

/** Loss if every short leg is bought back exactly at its stop, and longs expire worthless.
 *  Stops sit at the entry premium, so this is about breakeven. Gaps and slippage are extra. */
export function stopFigures(legs, today = todayIso()) {
  const shorts = legs.filter((l) => l.qty < 0)
  if (!shorts.length) return { state: 'none' }
  if (shorts.some((l) => l.sl_mode !== 'auto' || l.sl_price == null)) return { state: 'manual' }
  const liveFrom = shorts.map((l) => l.sl_activates_on).sort().at(-1)
  if (liveFrom > today) return { state: 'waiting', liveFrom }
  const value = legs.reduce((t, l) => t + (l.qty < 0 ? (l.avg_price - l.sl_price) * -l.qty : -l.qty * l.avg_price), 0)
  return { state: 'live', value: Math.min(0, value) }
}

const stopText = (s) =>
  s.state === 'live' ? signedRupee(s.value)
    : s.state === 'waiting' ? `Live from ${shortDate(s.liveFrom)}`
      : s.state === 'manual' ? 'No auto exit' : '—'

const money = (v) => (v === Infinity || v === -Infinity ? 'Unlimited' : signedRupee(v))

function RiskRow({ r, s, className = '' }) {
  return (
    <dl className={`pos-risk ${className}`}>
      <div><dt>Max profit</dt><dd className={`mono ${pnlClass(r.maxProfit)}`}>{money(r.maxProfit)}</dd></div>
      <div><dt>Max loss</dt><dd className={`mono ${pnlClass(r.maxLoss)}`}>{money(r.maxLoss)}</dd></div>
      <div title="If every leg is bought back at its stop price. Gaps and slippage are extra.">
        <dt>Loss at stop</dt>
        <dd className={`mono ${s.state === 'live' ? pnlClass(s.value) : 'muted'}`}>{stopText(s)}</dd>
      </div>
      <div>
        <dt>Profit left</dt>
        <dd className="mono">{r.left == null ? '—' : rupee(r.left)}</dd>
      </div>
    </dl>
  )
}

function SLStatus({ leg, onDismiss }) {
  switch (leg.sl_status) {
    case 'waiting':
      return <span className="sl-badge waiting">Live from {shortDate(leg.sl_activates_on)}</span>
    case 'armed':
      return <span className="sl-badge armed">Live @ {rupee2(leg.sl_price)}</span>
    case 'alert':
      return (
        <span className="sl-badge alert">
          <BellRing size={12} aria-hidden /> Hit @ {rupee2(leg.sl_price)}
          <button className="link-btn" onClick={onDismiss}>Dismiss</button>
        </span>
      )
    case 'off':
      return <span className="sl-badge off">No SL</span>
    default:
      return <span className="muted small">—</span>
  }
}

function Group({ g, onAction }) {
  const [open, setOpen] = useState(false)
  const [levels, setLevels] = useState(false)
  const lotsLabel = (l) => `${Math.abs(l.lots)} lot${Math.abs(l.lots) > 1 ? 's' : ''}`
  const shorts = g.legs.filter((l) => l.qty < 0 && legMark(l) != null)
  const collected = shorts.reduce((t, l) => t + l.avg_price * -l.qty, 0)
  const theta = {
    start: g.legs.map((l) => l.opened_at?.slice(0, 10)).sort()[0],
    sl: shorts.map((l) => l.sl_activates_on).filter(Boolean).sort()[0],
    captured: collected ? shorts.reduce((t, l) => t + (l.avg_price - legMark(l)) * -l.qty, 0) / collected : null,
  }
  return (
    <section className="card pos-group">
      <header className="pos-head">
        <div className="pos-title">
          <Link to={`/stock/${encodeURIComponent(g.symbol)}${g.expiry ? `?expiry=${g.expiry}` : ''}`} className="sym-lg">{g.symbol}</Link>
          <span className="chip action-strangle">{g.strategy}</span>
          <span className="muted small">
            Expires {shortDate(g.expiry)}, {g.dte} days left. Time exit <b>{shortDate(g.time_exit_on)}</b>. Profit exit at <b>90%</b> decay. Spot <span className="num">{num(g.spot)}</span>
          </span>
        </div>
        <div className="pos-figures">
          <div>
            <span className="stat-label">Unbooked</span>
            <span className={`mono big ${pnlClass(g.pnl)}`}>{signedRupee(g.pnl)}</span>
          </div>
          <div title="Buying every short back at the ask (and selling longs at the bid) right now">
            <span className="stat-label">If closed now</span>
            <span className={`mono ${pnlClass(g.pnl_exit)}`}>{g.pnl_exit != null ? signedRupee(g.pnl_exit) : '—'}</span>
          </div>
          <div>
            <span className="stat-label">Margin</span>
            <span className="mono">{g.margin ? rupee(g.margin.total) : '—'}</span>
          </div>
          <div>
            <span className="stat-label">Theta / day</span>
            <span className="mono pos">{rupee(g.greeks.theta)}</span>
          </div>
        </div>
      </header>

      <RiskRow r={riskFigures(g.legs)} s={stopFigures(g.legs)} />

      {theta.start && (
        <DecayCurve compact start={theta.start} slDate={theta.sl} expiry={g.expiry} today={todayIso()} captured={theta.captured} />
      )}

      {g.error && <p className="form-error">Live data issue: {g.error}</p>}

      <div className="table-scroll">
        <table className="legs pos-legs">
          <thead>
            <tr>
              <th>Instrument</th><th className="num">Qty</th><th className="num">Avg</th><th className="num" title="Fair value: the bid/ask mid">Mark</th>
              <th className="num">P&L</th><th className="num">Delta</th><th>Stop loss</th><th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {g.legs.map((l) => (
              <tr key={l.id} className={l.sl_status === 'alert' ? 'row-alert' : ''}>
                <td data-label="Instrument">
                  <LegTag action={l.qty < 0 ? 'SELL' : 'BUY'} side={l.side} />
                  <b className="mono">{l.strike}</b>
                </td>
                <td data-label="Qty" className="num mono">{int(l.qty)} <span className="muted">({lotsLabel(l)})</span></td>
                <td data-label="Avg" className="num mono">{num(l.avg_price)}</td>
                <td data-label="Mark" className="num mono" title={`${MARK_NOTE[l.mark_src] ?? 'last trade'} · Bid ${num(l.bid)} · Ask ${num(l.ask)} · LTP ${num(l.ltp)}`}>
                  {num(legMark(l))}
                  {l.ltp_gap_pct > 15 && (
                    <AlertTriangle size={13} className="stale-ltp" role="img"
                      aria-label={`Last trade ${num(l.ltp)} is outside the ${num(l.bid)}/${num(l.ask)} bid/ask (stale); valued at the mid`} />
                  )}
                  <span className="sub">{l.mark_src === 'close' ? 'at close' : l.mark_src === 'mid' ? 'mid' : l.mark_src === 'ltp' ? 'LTP' : ''}</span>
                </td>
                <td data-label="P&L" className={`num mono ${pnlClass(l.pnl)}`}>{signedRupee(l.pnl)}</td>
                <td data-label="Delta" className="num mono">{signed(l.delta, 1)}</td>
                <td data-label="Stop loss">
                  {l.qty < 0 ? (
                    <div className="sl-cell">
                      <SLModeSwitch compact value={l.sl_mode} onChange={(m) => onAction('sl', { mode: m, position_id: l.id })} label={`Stop loss for ${l.strike} ${l.side}`} />
                      <SLStatus leg={l} onDismiss={() => onAction('dismiss', { position_id: l.id })} />
                    </div>
                  ) : (
                    <span className="muted small">Long leg</span>
                  )}
                </td>
                <td className="num">
                  <button className="btn small" onClick={() => onAction('exitLeg', l, g)}>Exit</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <footer className="pos-foot">
        <button className="btn ghost small" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          <LineChart size={15} aria-hidden /> {open ? 'Hide payoff' : 'Show payoff & Greeks'}
          <ChevronDown size={15} aria-hidden className={open ? 'rot' : ''} />
        </button>
        <button className="btn ghost small" onClick={() => setLevels((o) => !o)} aria-expanded={levels}>
          <ChartCandlestick size={15} aria-hidden /> {levels ? 'Hide price chart' : 'Price & pivot levels'}
          <ChevronDown size={15} aria-hidden className={levels ? 'rot' : ''} />
        </button>
        <Link className="btn ghost small" to={`/builder?symbol=${encodeURIComponent(g.symbol)}&expiry=${g.expiry}&adjust=1`}
          title="Try a roll, a hedge or a close in the builder and see the position before and after">
          <SlidersHorizontal size={15} aria-hidden /> Adjust
        </Link>
        <button className="btn danger-ghost small" onClick={() => onAction('exitGroup', null, g)}>
          <LogOut size={15} aria-hidden /> Exit all
        </button>
      </footer>

      {open && (
        <div className="pos-detail">
          <GroupPayoff legs={g.legs} spot={g.spot} />
          <dl className="greek-row">
            <div><dt>Net delta</dt><dd className="mono">{signed(g.greeks.delta, 1)}</dd></div>
            <div><dt>Gamma</dt><dd className="mono">{signed(g.greeks.gamma, 2)}</dd></div>
            <div><dt>Theta / day</dt><dd className="mono pos">{rupee(g.greeks.theta)}</dd></div>
            <div><dt>Vega / IV pt</dt><dd className="mono">{rupee(g.greeks.vega)}</dd></div>
            <div><dt>Premium collected</dt><dd className="mono">{rupee(g.net_premium)}</dd></div>
            <div><dt>SPAN + exposure</dt><dd className="mono">{g.margin ? `${rupee(g.margin.span)} + ${rupee(g.margin.exposure)}` : '—'}</dd></div>
          </dl>
        </div>
      )}

      {levels && (
        <div className="pos-detail">
          <PivotLevels symbol={g.symbol} spot={g.spot} legs={g.legs} />
        </div>
      )}
    </section>
  )
}

const TICK = 0.05

function OpenOrders({ rows, busy, onImprove, onCancel }) {
  if (!rows?.length) return null
  return (
    <section className="card open-orders" aria-label="Open limit orders">
      <header className="card-head">
        <h2><Hourglass size={16} aria-hidden /> Open limit orders</h2>
        <span className="muted small">Fill when the market reaches your limit. Day orders expire at 15:30.</span>
      </header>
      <div className="table-scroll">
        <table className="oo-table">
          <thead><tr><th>Order</th><th className="num">Limit</th><th className="num">Bid / ask now</th><th>Valid for</th><th /></tr></thead>
          <tbody>
            {rows.map((o) => {
              const better = o.action === 'SELL' ? o.limit_price - TICK : o.limit_price + TICK
              return (
                <tr key={o.id}>
                  <td>
                    <b>{o.action}</b> {o.symbol} {shortDate(o.expiry)} {o.strike} {o.side}
                    <span className="muted small block">{o.lots} lot{o.lots > 1 ? 's' : ''} ({int(o.qty)} qty){o.reason !== 'manual' ? `, ${o.reason.replace('_', ' ')}` : ''}</span>
                  </td>
                  <td className="num mono">{rupee2(o.limit_price)}</td>
                  <td className="num mono">{o.bid == null ? '—' : `${rupee2(o.bid)} / ${rupee2(o.ask)}`}</td>
                  <td className="mono small">{shortDate(o.valid_until)}</td>
                  <td className="oo-actions">
                    <button className="btn small ghost" disabled={busy || better <= 0} onClick={() => onImprove(o, better)}
                      title={`Move the limit to ${rupee2(better)}`}>Improve 1 tick</button>
                    <button className="btn small ghost danger-text" disabled={busy} onClick={() => onCancel(o)}>Cancel</button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function PortfolioSkeleton() {
  return (
    <>
      <section className="stats">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="stat">
            <span className="skeleton" style={{ width: '50%', height: 12 }} />
            <span className="skeleton" style={{ width: '70%', height: 24, margin: '4px 0' }} />
          </div>
        ))}
      </section>
      {[0, 1].map((i) => (
        <section key={i} className="card">
          <span className="skeleton" style={{ width: 200, height: 20, marginBottom: 16 }} />
          <span className="skeleton" style={{ height: 96 }} />
        </section>
      ))}
    </>
  )
}

export default function Portfolio() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [refreshing, setRefreshing] = useState(false)
  const [confirm, setConfirm] = useState(null)
  const [busy, setBusy] = useState(false)
  const [actionError, setActionError] = useState(null)
  const [openOrders, setOpenOrders] = useState(null)
  const [notice, setNotice] = useState(null)
  // Virtual vs. real (broker) account view (issue #52). Only the active mode's data is polled —
  // switching modes starts that loader and lets the other one's pending timer lapse.
  const [mode, setMode] = useState('virtual')
  const [brokerConnected, setBrokerConnected] = useState(false)
  const [real, setReal] = useState(null)
  const [realError, setRealError] = useState(null)
  const [realRefreshing, setRealRefreshing] = useState(false)
  const timer = useRef(null)
  const timerReal = useRef(null)
  const alive = useRef(true)
  const modeRef = useRef('virtual')
  const { refresh: refreshBudget } = useBudget()

  const load = useCallback(async (reprice = false) => {
    clearTimeout(timer.current)
    if (reprice) setRefreshing(true)
    try {
      const [res, oo] = await Promise.all([
        rpc(reprice === true ? 'va_refresh_positions' : 'va_get_positions'),
        rpc('va_get_open_orders').catch(() => null),
      ])
      if (!alive.current) return
      setData(res)
      if (oo) setOpenOrders(oo)
      setError(null)
    } catch (e) {
      if (alive.current) setError(e.message)
    } finally {
      if (alive.current) {
        setRefreshing(false)
        if (modeRef.current === 'virtual') timer.current = setTimeout(load, POLL_MS)
      }
    }
  }, [])

  const loadReal = useCallback(async (preSummary) => {
    clearTimeout(timerReal.current)
    setRealRefreshing(true)
    try {
      const s = preSummary ?? await rpc('broker_account_summary')
      if (!alive.current) return
      const connected = s.source === 'broker'
      setBrokerConnected(connected)
      let positions = null, stops = null
      if (connected) [positions, stops] = await Promise.all([rpc('broker_get_positions'), rpc('broker_stop_alerts')])
      if (!alive.current) return
      setReal({ summary: s, positions, stops })
      setRealError(null)
    } catch (e) {
      if (alive.current) setRealError(e.message)
    } finally {
      if (alive.current) {
        setRealRefreshing(false)
        if (modeRef.current === 'real') timerReal.current = setTimeout(loadReal, POLL_MS)
      }
    }
  }, [])

  function switchMode(next) {
    if (next === mode || (next === 'real' && !brokerConnected)) return
    modeRef.current = next
    setMode(next)
    clearTimeout(timer.current)
    clearTimeout(timerReal.current)
    if (next === 'virtual') load()
    else loadReal()
  }

  useTitle('Portfolio')
  useEffect(() => {
    alive.current = true
    ;(async () => {
      // One cheap check decides both the default view and whether "Real" is even selectable —
      // the same call the Broker/connect-banner pages already make.
      const s = await rpc('broker_account_summary').catch(() => null)
      if (!alive.current) return
      const initialMode = s?.source === 'broker' ? 'real' : 'virtual'
      modeRef.current = initialMode
      setMode(initialMode)
      setBrokerConnected(s?.source === 'broker')
      if (initialMode === 'real') loadReal(s)
      else load()
    })()
    return () => {
      alive.current = false
      clearTimeout(timer.current)
      clearTimeout(timerReal.current)
    }
  }, [load, loadReal])

  async function run(method, params) {
    setBusy(true)
    setActionError(null)
    setNotice(null)
    try {
      const out = await rpc(method, params)
      const waiting = Array.isArray(out) ? out.filter((x) => x.status === 'open').length : 0
      const already = Array.isArray(out) ? out.filter((x) => x.status === 'already_open').length : 0
      if (waiting) setNotice(`${waiting} exit order${waiting > 1 ? 's are' : ' is'} waiting as a limit order (market closed or no live price). See Open limit orders.`)
      else if (already) setNotice('An exit order for this position is already waiting. See Open limit orders to change its price or cancel it.')
      if (method === 'va_modify_order' && out?.filled) setNotice('Filled at the new limit.')
      setConfirm(null)
      await load()
      refreshBudget()
    } catch (e) {
      setActionError(e.message)
    } finally {
      setBusy(false)
    }
  }

  function onAction(kind, arg, g) {
    if (kind === 'sl') return run('va_set_sl_mode', arg)
    if (kind === 'dismiss') return run('va_dismiss_alert', arg)
    setActionError(null)
    if (kind === 'exitLeg')
      setConfirm({
        title: `Exit ${g.symbol} ${arg.strike} ${arg.side}?`,
        body: `${arg.qty < 0 ? 'Buys back' : 'Sells'} ${int(Math.abs(arg.qty))} qty with a limit at the ${arg.qty < 0 ? 'ask' : 'bid'} (now ${rupee2(arg.qty < 0 ? arg.ask : arg.bid)}). With the market closed it waits for the next session. Current P&L on this leg: ${signedRupee(arg.pnl)}.`,
        label: 'Exit leg',
        go: () => run('va_exit_position', { position_id: arg.id }),
      })
    if (kind === 'exitGroup')
      setConfirm({
        title: `Exit all ${g.symbol} legs?`,
        body: `Closes ${g.legs.length} leg${g.legs.length > 1 ? 's' : ''} with limits at the live bid/ask and releases ${g.margin ? rupee(g.margin.total) : 'the'} margin. With the market closed they wait for the next session. Current P&L: ${signedRupee(g.pnl)}.`,
        label: 'Exit all',
        go: () => run('va_exit_group', { symbol: g.symbol, expiry: g.expiry }),
      })
  }

  const a = data?.account
  const alerts = data?.groups.flatMap((g) => g.legs.filter((l) => l.sl_status === 'alert').map((l) => `${g.symbol} ${l.strike} ${l.side}`)) ?? []

  return (
    <div className="detail">
      <section className="page-head">
        <div>
          <h1 className="display">Portfolio</h1>
          <p className="lede">
            {mode === 'virtual'
              ? (data?.groups.length
                ? `${data.groups.length} position${data.groups.length > 1 ? 's' : ''} open, earning ${rupee(data.totals.theta)} a day from time decay.`
                : 'Your virtual positions, priced live from NSE.')
              : 'Your real broker positions, synced from your connected account.'}{' '}
            {mode === 'virtual' && data && <span className={`market ${data.market_open ? 'open' : ''}`}>{data.market_open ? 'Market is open.' : 'Market is closed.'}</span>}
          </p>
          <UpdatedTag ts={mode === 'virtual' ? data?.updated_at : real?.summary?.synced_at} refreshing={mode === 'virtual' ? refreshing : realRefreshing} label={mode === 'virtual' ? 'Prices updated' : 'Synced'} />
        </div>
        <div className="page-head-actions">
          <div className="segmented account-mode-switch small" role="radiogroup" aria-label="Account view">
            <button type="button" role="radio" aria-checked={mode === 'virtual'} className={mode === 'virtual' ? 'active' : ''} onClick={() => switchMode('virtual')}>Virtual</button>
            <button type="button" role="radio" aria-checked={mode === 'real'} className={mode === 'real' ? 'active' : ''} disabled={!brokerConnected}
              title={brokerConnected ? undefined : 'Connect a broker on the Broker page first'} onClick={() => switchMode('real')}>Real</button>
          </div>
          <button className="btn" onClick={() => (mode === 'virtual' ? load(true) : loadReal())} disabled={mode === 'virtual' ? refreshing : realRefreshing}
            title={mode === 'virtual' ? 'Re-price every position from NSE now' : 'Refresh from your broker'}>
            <RefreshCw size={16} className={(mode === 'virtual' ? refreshing : realRefreshing) ? 'spin' : ''} aria-hidden /> <span className="btn-label">Refresh</span>
          </button>
        </div>
      </section>

      {mode === 'real' && (
        <RealAccountView summary={real?.summary} positions={real?.positions} stops={real?.stops} error={realError} />
      )}

      {mode === 'virtual' && error && <div className="alert" role="alert"><AlertTriangle size={18} aria-hidden /> {error}</div>}

      {mode === 'virtual' && alerts.length > 0 && (
        <div className="alert warn-alert" role="alert">
          <BellRing size={18} aria-hidden />
          <span>Stop loss hit on {alerts.join(', ')}. Exit the whole position with Exit all, or dismiss the alert.</span>
        </div>
      )}

      {mode === 'virtual' && !data && !error && <PortfolioSkeleton />}

      {mode === 'virtual' && a && (
        <section className="ledger" aria-label="Account summary">
          <div className="stat">
            <span className="stat-label">Unbooked P&L</span>
            <span className={`stat-value mono ${pnlClass(a.unrealized_pnl)}`}>{signedRupee(a.unrealized_pnl)}</span>
            {data.totals.pnl_exit != null && (
              <span className="stat-sub" title="Buying every short back at the ask right now: the spread is the difference">If closed now {signedRupee(data.totals.pnl_exit)}</span>
            )}
          </div>
          <div className="stat"><span className="stat-label">Booked P&L</span><span className={`stat-value mono ${pnlClass(a.realized_pnl)}`}>{signedRupee(a.realized_pnl)}</span></div>
          <div className="stat"><span className="stat-label">Margin used</span><span className="stat-value mono">{rupee(a.used_margin)}</span></div>
          <div className="stat"><span className="stat-label">Funds free</span><span className="stat-value mono">{rupee(a.available_margin)}</span></div>
          <div className="stat"><span className="stat-label">Theta / day</span><span className="stat-value mono pos">{rupee(data.totals.theta)}</span></div>
          <div className="stat"><span className="stat-label">Net delta</span><span className="stat-value mono">{signed(data.totals.delta, 1)}</span><span className="stat-sub">Return {pct(a.return_pct, 2)}</span></div>
        </section>
      )}
      {mode === 'virtual' && a && data.groups.length > 0 && (() => {
        const rs = data.groups.map((g) => riskFigures(g.legs))
        const sum = (k) => rs.reduce((t, r) => t + r[k], 0) // Infinity propagates: one naked call makes the total unlimited
        const left = rs.some((r) => r.left == null) ? null : sum('left')
        const ss = data.groups.map((g) => stopFigures(g.legs))
        const live = ss.filter((s) => s.state === 'live')
        const next = ss.filter((s) => s.state === 'waiting').map((s) => s.liveFrom).sort()[0]
        return (
          <section className="ledger ledger-risk" aria-label="Risk at expiry, all positions">
            <div className="stat"><span className="stat-label">Max profit</span><span className="stat-value mono pos">{money(sum('maxProfit'))}</span><span className="stat-sub">If every position expires worthless</span></div>
            <div className="stat"><span className="stat-label">Max loss</span><span className="stat-value mono neg">{money(sum('maxLoss'))}</span><span className="stat-sub">{sum('maxLoss') === -Infinity ? 'Short calls have no ceiling on loss' : 'Worst case at expiry'}</span></div>
            <div className="stat">
              <span className="stat-label">Loss at stop</span>
              <span className={`stat-value mono ${live.length ? 'neg' : 'muted'}`}>{live.length ? signedRupee(live.reduce((t, s) => t + s.value, 0)) : 'Not live yet'}</span>
              <span className="stat-sub">
                {live.length === ss.length ? 'All positions on auto stop. Gaps are extra'
                  : `${live.length} of ${ss.length} covered${next ? `, next from ${shortDate(next)}` : ''}`}
              </span>
            </div>
            <div className="stat"><span className="stat-label">Profit left</span><span className="stat-value mono">{left == null ? '—' : rupee(left)}</span><span className="stat-sub">{left == null ? 'Waiting for prices' : `${pct((left / sum('maxProfit')) * 100, 0)} of max profit still to decay`}</span></div>
          </section>
        )
      })()}

      {mode === 'virtual' && data && data.groups.length === 0 && (
        <div className="card empty-state">
          <h2>No open positions</h2>
          <p className="muted">Pick a setup from the screener and place a virtual order to start paper trading your strategy.</p>
          <Link className="btn primary" to="/">Open screener</Link>
        </div>
      )}

      {mode === 'virtual' && notice && <p className="notice" role="status"><Hourglass size={16} aria-hidden /> {notice}</p>}
      {mode === 'virtual' && (
        <OpenOrders rows={openOrders} busy={busy}
          onImprove={(o, price) => run('va_modify_order', { order_id: o.id, price: Math.round(price * 100) / 100 })}
          onCancel={(o) => run('va_cancel_order', { order_id: o.id })} />
      )}

      {mode === 'virtual' && data?.groups.map((g) => <Group key={`${g.symbol}-${g.expiry}`} g={g} onAction={onAction} />)}

      {actionError && !confirm && <p className="form-error" role="alert">{actionError}</p>}

      {confirm && (
        <ConfirmDialog
          title={confirm.title}
          body={confirm.body}
          confirmLabel={confirm.label}
          danger
          busy={busy}
          error={actionError}
          onConfirm={confirm.go}
          onClose={() => setConfirm(null)}
        />
      )}
    </div>
  )
}
