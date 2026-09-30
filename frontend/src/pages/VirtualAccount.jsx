import { useCallback, useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { AlertTriangle, RotateCcw } from 'lucide-react'
import { rpc } from '../rpc'
import { useBudget } from '../settings'
import { dateTime, int, num, pct, pnlClass, rupee, rupee2, shortDate, signedRupee } from '../format'
import SLModeSwitch, { slHelp } from '../components/SLModeSwitch'
import { ConfirmDialog } from '../components/Modal'
import AutoTradePanel from '../components/AutoTrade'
import { useCan } from '../auth'
import UpdatedTag from '../components/UpdatedTag'
import PalettePicker from '../components/PalettePicker'
import StatCard from '../components/StatCard'
import EquityBar from '../components/EquityBar'

const REASON = { manual: 'Manual', auto: 'Auto-trade', sl_auto: 'Group SL', time_exit: 'Time exit', target_exit: 'Profit target', expiry: 'Expiry' }

/** XIRR for one deposit (starting capital) and today's value, no withdrawals: the annual rate r
 *  that solves capital x (1 + r)^(days/365) = value. Annualising under a week turns tiny moves
 *  into huge rates, so it waits for MIN_XIRR_DAYS of history. */
const MIN_XIRR_DAYS = 7
function xirr(acct) {
  const days = (Date.now() - new Date(acct.created_at.replace(' ', 'T') + '+05:30')) / 86400000
  if (days < MIN_XIRR_DAYS || acct.account_value <= 0) return { days, rate: null }
  return { days, rate: (Math.pow(acct.account_value / acct.starting_capital, 365 / days) - 1) * 100 }
}

export default function VirtualAccount() {
  const autoOk = useCan('autotrade')
  const [acct, setAcct] = useState(null)
  const [orders, setOrders] = useState(null)
  const [closed, setClosed] = useState(null)
  const [tab, setTab] = useState('orders')
  const [error, setError] = useState(null)
  const [capital, setCapital] = useState(1000000)
  const [confirmReset, setConfirmReset] = useState(false)
  const [busy, setBusy] = useState(false)
  const [resetError, setResetError] = useState(null)
  const { refresh: refreshBudget } = useBudget()

  const load = useCallback(async () => {
    try {
      const [a, o, c] = await Promise.all([rpc('va_get_account'), rpc('va_get_orders'), rpc('va_get_closed')])
      setAcct(a)
      setOrders(o)
      setClosed(c)
      setCapital(a.starting_capital)
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => {
    document.title = 'Virtual account · Theta Desk'
    load()
  }, [load])

  const { hash } = useLocation()
  useEffect(() => {
    if (hash === '#auto') document.getElementById('auto')?.scrollIntoView({ block: 'start' })
  }, [hash])

  async function setDefault(mode) {
    setAcct((a) => ({ ...a, sl_mode_default: mode }))
    try {
      await rpc('va_set_sl_mode', { mode })
    } catch (e) {
      setError(e.message)
      load()
    }
  }

  async function doReset() {
    setBusy(true)
    setResetError(null)
    try {
      await rpc('va_reset', { starting_capital: Number(capital) })
      setConfirmReset(false)
      await load()
      refreshBudget()
    } catch (e) {
      setResetError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const winners = closed?.filter((c) => c.realized_pnl > 0).length ?? 0

  return (
    <div className="detail">
      <section className="statement">
        <div className="statement-main">
          <h1 className="sr-only">Virtual account</h1>
          <p className="statement-label">Virtual account value</p>
          {acct && <UpdatedTag ts={acct.updated_at} label="Marked" />}
          {acct ? (
            <>
              <p className="statement-value display-num">{rupee(acct.account_value)}</p>
              <p className="lede">
                <span className={pnlClass(acct.account_value - acct.starting_capital)}>
                  {signedRupee(acct.account_value - acct.starting_capital)} ({pct(acct.return_pct, 2)})
                </span>{' '}
                since you started with {rupee(acct.starting_capital)} on {dateTime(acct.created_at)}.
              </p>
            </>
          ) : (
            <span className="skeleton" style={{ width: 260, height: 56 }} />
          )}
        </div>
        {acct && (
          <EquityBar used={acct.used_margin} free={acct.available_margin} usedLabel="Margin in use" freeLabel="Free for new trades">
            <Link className="btn" to="/portfolio">View {acct.open_positions} open leg{acct.open_positions === 1 ? '' : 's'}</Link>
          </EquityBar>
        )}
      </section>

      {error && <div className="alert" role="alert"><AlertTriangle size={18} aria-hidden /> {error}</div>}

      <section className="ledger" aria-label="Performance">
        {acct ? (
          <>
            <StatCard label="Overall profit" value={pct(acct.return_pct, 2)} tone={pnlClass(acct.return_pct)}
              sub={`${signedRupee(acct.account_value - acct.starting_capital)} on ${rupee(acct.starting_capital)}, booked + unbooked`} />
            {(() => {
              const x = xirr(acct)
              const d = Math.max(1, Math.floor(x.days))
              return (
                <StatCard label="XIRR" value={x.rate == null ? '—' : pct(x.rate, 1)} tone={x.rate == null ? '' : pnlClass(x.rate)}
                  sub={x.rate == null
                    ? `Annual rate shows after ${MIN_XIRR_DAYS} days; day ${d} now`
                    : `Annualised over ${d} days${d < 30 ? '; swings a lot in the first month' : ''}`} />
              )
            })()}
            <StatCard label="Booked P&L" value={signedRupee(acct.realized_pnl)} tone={pnlClass(acct.realized_pnl)} sub="locked in from closed trades" />
            <StatCard label="Unbooked P&L" value={signedRupee(acct.unrealized_pnl)} tone={pnlClass(acct.unrealized_pnl)} sub={`${acct.open_positions} open leg${acct.open_positions === 1 ? '' : 's'} at last price; moves until you exit`} />
            <StatCard label="Win rate" value={closed?.length ? pct((winners / closed.length) * 100, 0) : '—'} sub={closed ? `${winners} of ${closed.length} closed legs in profit` : ''} />
            <StatCard label="Orders placed" value={orders ? orders.length : '—'} sub={orders ? `${orders.filter((o) => o.reason === 'auto').length} by auto-trade, ${orders.filter((o) => o.reason === 'sl_auto').length} by stop loss, ${orders.filter((o) => o.reason === 'time_exit').length} by time exit, ${orders.filter((o) => o.reason === 'target_exit').length} at profit target` : ''} />
          </>
        ) : (
          Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="stat">
              <span className="skeleton" style={{ width: '50%', height: 12 }} />
              <span className="skeleton" style={{ width: '70%', height: 26, margin: '6px 0' }} />
            </div>
          ))
        )}
      </section>

      {autoOk && <AutoTradePanel onRun={load} />}

      <PalettePicker />

      <div className="two-col">
        <section className="card">
          <header className="card-head"><h2>Default stop loss</h2><span className="muted small">Applies to new short legs</span></header>
          {acct ? <SLModeSwitch value={acct.sl_mode_default} onChange={setDefault} /> : <span className="skeleton" style={{ height: 40 }} />}
          <p className="helper">{acct && slHelp(acct.sl_mode_default)} Change it per leg anytime on the Portfolio page.</p>
          <p className="muted small">Stop losses are checked every minute during market hours (9:15–15:30 IST), even with this page closed, as long as the server is running.</p>
        </section>

        <section className="card">
          <header className="card-head"><h2>Reset account</h2><span className="muted small">Clears all positions and history</span></header>
          <div className="reset-row">
            <div className="field">
              <label htmlFor="reset-cap">Starting capital (₹)</label>
              <input id="reset-cap" type="number" inputMode="numeric" min="10000" step="100000" value={capital} onChange={(e) => setCapital(e.target.value)} />
            </div>
            <button className="btn danger-ghost" onClick={() => { setResetError(null); setConfirmReset(true) }}>
              <RotateCcw size={16} aria-hidden /> Reset
            </button>
          </div>
        </section>
      </div>

      <section className="card">
        <header className="card-head">
          <div className="segmented small" role="tablist" aria-label="History">
            <button role="tab" aria-selected={tab === 'orders'} className={tab === 'orders' ? 'active' : ''} onClick={() => setTab('orders')}>
              Order history <span className="count mono">{orders?.length ?? ''}</span>
            </button>
            <button role="tab" aria-selected={tab === 'closed'} className={tab === 'closed' ? 'active' : ''} onClick={() => setTab('closed')}>
              Closed positions <span className="count mono">{closed?.length ?? ''}</span>
            </button>
          </div>
        </header>

        <div className="table-scroll" role="tabpanel">
          {tab === 'orders' && (
            orders?.length ? (
              <table className="legs history">
                <thead>
                  <tr><th>Time</th><th>Instrument</th><th>Side</th><th className="num">Qty</th><th className="num">Limit</th><th className="num">Filled at</th><th className="num">Realised</th><th>Source</th></tr>
                </thead>
                <tbody>
                  {orders.map((o) => (
                    <tr key={o.id}>
                      <td data-label="Time" className="mono small">{dateTime(o.ts)}</td>
                      <td data-label="Instrument">{o.symbol} {shortDate(o.expiry)} <b className="mono">{o.strike}</b> {o.side}</td>
                      <td data-label="Side"><span className={`side-tag ${o.action.toLowerCase()}`}>{o.action}</span></td>
                      <td data-label="Qty" className="num mono">{int(o.qty)}</td>
                      <td data-label="Limit" className="num mono">{o.limit_price == null ? '—' : rupee2(o.limit_price)}</td>
                      <td data-label="Filled at" className="num mono">{rupee2(o.price)}</td>
                      <td data-label="Realised" className={`num mono ${pnlClass(o.realized_pnl)}`}>{o.realized_pnl ? signedRupee(o.realized_pnl) : '—'}</td>
                      <td data-label="Source">
                        <span className={`reason reason-${o.reason}`}>{REASON[o.reason] ?? o.reason}</span>
                        {o.note && <span className="sub">{o.note}</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="empty">{orders ? 'No orders yet. Place a virtual order from any setup in the screener.' : 'Loading…'}</p>
            )
          )}
          {tab === 'closed' && (
            closed?.length ? (
              <table className="legs history">
                <thead>
                  <tr><th>Closed</th><th>Instrument</th><th className="num">Entry</th><th className="num">Exit</th><th className="num">Booked P&L</th></tr>
                </thead>
                <tbody>
                  {closed.map((c) => (
                    <tr key={c.id}>
                      <td data-label="Closed" className="mono small">{dateTime(c.closed_at)}</td>
                      <td data-label="Instrument">{c.symbol} {shortDate(c.expiry)} <b className="mono">{c.strike}</b> {c.side}</td>
                      <td data-label="Entry" className="num mono">{num(c.avg_price)}</td>
                      <td data-label="Exit" className="num mono">{num(c.exit_price)}</td>
                      <td data-label="Booked P&L" className={`num mono ${pnlClass(c.realized_pnl)}`}>{signedRupee(c.realized_pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="empty">{closed ? 'No closed positions yet.' : 'Loading…'}</p>
            )
          )}
        </div>
      </section>

      {confirmReset && (
        <ConfirmDialog
          title="Reset virtual account?"
          body={`All ${acct?.open_positions ?? 0} open positions, order history and P&L will be deleted. The account restarts with ${rupee(Number(capital))}. This can't be undone.`}
          confirmLabel="Reset account"
          danger
          busy={busy}
          error={resetError}
          onConfirm={doReset}
          onClose={() => setConfirmReset(false)}
        />
      )}
    </div>
  )
}
