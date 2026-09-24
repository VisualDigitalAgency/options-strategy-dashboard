import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, BellRing, ChevronDown, LineChart, LogOut, RefreshCw } from 'lucide-react'
import { rpc } from '../rpc'
import { useBudget } from '../settings'
import { num, pct, rupee, rupee2, int, shortDate, signed, signedRupee, todayIso } from '../format'
import DecayCurve from '../components/DecayCurve'
import { GroupPayoff } from '../components/Charts'
import SLModeSwitch from '../components/SLModeSwitch'
import { ConfirmDialog } from '../components/Modal'

const POLL_MS = 30000

export const pnlClass = (v) => (v > 0 ? 'pos' : v < 0 ? 'neg' : '')

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
  const lotsLabel = (l) => `${Math.abs(l.lots)} lot${Math.abs(l.lots) > 1 ? 's' : ''}`
  const shorts = g.legs.filter((l) => l.qty < 0 && l.ltp != null)
  const collected = shorts.reduce((t, l) => t + l.avg_price * -l.qty, 0)
  const theta = {
    start: g.legs.map((l) => l.opened_at?.slice(0, 10)).sort()[0],
    sl: shorts.map((l) => l.sl_activates_on).filter(Boolean).sort()[0],
    captured: collected ? shorts.reduce((t, l) => t + (l.avg_price - l.ltp) * -l.qty, 0) / collected : null,
  }
  return (
    <section className="card pos-group">
      <header className="pos-head">
        <div className="pos-title">
          <Link to={`/stock/${encodeURIComponent(g.symbol)}`} className="sym-lg">{g.symbol}</Link>
          <span className="chip action-strangle">{g.strategy}</span>
          <span className="muted small">
            Expires {shortDate(g.expiry)}, {g.dte} days left. Spot <span className="num">{num(g.spot)}</span>
          </span>
        </div>
        <div className="pos-figures">
          <div>
            <span className="stat-label">P&L</span>
            <span className={`mono big ${pnlClass(g.pnl)}`}>{signedRupee(g.pnl)}</span>
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

      {theta.start && (
        <DecayCurve compact start={theta.start} slDate={theta.sl} expiry={g.expiry} today={todayIso()} captured={theta.captured} />
      )}

      {g.error && <p className="form-error">Live data issue: {g.error}</p>}

      <div className="table-scroll">
        <table className="legs pos-legs">
          <thead>
            <tr>
              <th>Instrument</th><th className="num">Qty</th><th className="num">Avg</th><th className="num">LTP</th>
              <th className="num">P&L</th><th className="num">Delta</th><th>Stop loss</th><th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {g.legs.map((l) => (
              <tr key={l.id} className={l.sl_status === 'alert' ? 'row-alert' : ''}>
                <td data-label="Instrument">
                  <span className={`leg-tag ${l.side.toLowerCase()}`}>{l.qty < 0 ? 'SELL' : 'BUY'} {l.side}</span>
                  <b className="mono">{l.strike}</b>
                </td>
                <td data-label="Qty" className="num mono">{int(l.qty)} <span className="muted">({lotsLabel(l)})</span></td>
                <td data-label="Avg" className="num mono">{num(l.avg_price)}</td>
                <td data-label="LTP" className="num mono">{num(l.ltp)}</td>
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
  const timer = useRef(null)
  const alive = useRef(true)
  const { refresh: refreshBudget } = useBudget()

  const load = useCallback(async () => {
    clearTimeout(timer.current)
    setRefreshing(true)
    try {
      const res = await rpc('va_get_positions')
      if (!alive.current) return
      setData(res)
      setError(null)
    } catch (e) {
      if (alive.current) setError(e.message)
    } finally {
      if (alive.current) {
        setRefreshing(false)
        timer.current = setTimeout(load, POLL_MS)
      }
    }
  }, [])

  useEffect(() => {
    alive.current = true
    document.title = 'Portfolio · Theta Desk'
    load()
    return () => {
      alive.current = false
      clearTimeout(timer.current)
    }
  }, [load])

  async function run(method, params) {
    setBusy(true)
    setActionError(null)
    try {
      await rpc(method, params)
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
        body: `${arg.qty < 0 ? 'Buys back' : 'Sells'} ${int(Math.abs(arg.qty))} qty at the live ${arg.qty < 0 ? 'ask' : 'bid'} (now ${rupee2(arg.qty < 0 ? arg.ask : arg.bid)}). Current P&L on this leg: ${signedRupee(arg.pnl)}.`,
        label: 'Exit leg',
        go: () => run('va_exit_position', { position_id: arg.id }),
      })
    if (kind === 'exitGroup')
      setConfirm({
        title: `Exit all ${g.symbol} legs?`,
        body: `Closes ${g.legs.length} leg${g.legs.length > 1 ? 's' : ''} at live prices and releases ${g.margin ? rupee(g.margin.total) : 'the'} margin. Current P&L: ${signedRupee(g.pnl)}.`,
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
            {data?.groups.length
              ? `${data.groups.length} position${data.groups.length > 1 ? 's' : ''} open, earning ${rupee(data.totals.theta)} a day from time decay.`
              : 'Your virtual positions, priced live from NSE.'}{' '}
            {data && <span className={`market ${data.market_open ? 'open' : ''}`}>{data.market_open ? 'Market is open.' : 'Market is closed.'}</span>}
          </p>
        </div>
        <button className="btn" onClick={load} disabled={refreshing}>
          <RefreshCw size={16} className={refreshing ? 'spin' : ''} aria-hidden /> <span className="btn-label">Refresh</span>
        </button>
      </section>

      {error && <div className="alert" role="alert"><AlertTriangle size={18} aria-hidden /> {error}</div>}

      {alerts.length > 0 && (
        <div className="alert warn-alert" role="alert">
          <BellRing size={18} aria-hidden />
          <span>Stop loss hit on {alerts.join(', ')}. Review and exit, or dismiss the alert.</span>
        </div>
      )}

      {!data && !error && <PortfolioSkeleton />}

      {a && (
        <section className="ledger" aria-label="Account summary">
          <div className="stat"><span className="stat-label">Open P&L</span><span className={`stat-value mono ${pnlClass(a.unrealized_pnl)}`}>{signedRupee(a.unrealized_pnl)}</span></div>
          <div className="stat"><span className="stat-label">Realised P&L</span><span className={`stat-value mono ${pnlClass(a.realized_pnl)}`}>{signedRupee(a.realized_pnl)}</span></div>
          <div className="stat"><span className="stat-label">Margin used</span><span className="stat-value mono">{rupee(a.used_margin)}</span></div>
          <div className="stat"><span className="stat-label">Funds free</span><span className="stat-value mono">{rupee(a.available_margin)}</span></div>
          <div className="stat"><span className="stat-label">Theta / day</span><span className="stat-value mono pos">{rupee(data.totals.theta)}</span></div>
          <div className="stat"><span className="stat-label">Net delta</span><span className="stat-value mono">{signed(data.totals.delta, 1)}</span><span className="stat-sub">Return {pct(a.return_pct, 2)}</span></div>
        </section>
      )}

      {data && data.groups.length === 0 && (
        <div className="card empty-state">
          <h2>No open positions</h2>
          <p className="muted">Pick a setup from the screener and place a virtual order to start paper trading your strategy.</p>
          <Link className="btn primary" to="/">Open screener</Link>
        </div>
      )}

      {data?.groups.map((g) => <Group key={`${g.symbol}-${g.expiry}`} g={g} onAction={onAction} />)}

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
