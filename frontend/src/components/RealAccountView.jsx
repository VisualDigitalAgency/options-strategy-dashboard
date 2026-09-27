import { Link } from 'react-router-dom'
import { AlertTriangle, Info } from 'lucide-react'
import { num, pnlClass, rupee, rupee2, shortDate, signedRupee } from '../format'
import StatCard from './StatCard'
import UpdatedTag from './UpdatedTag'
import EquityBar from './EquityBar'

/** The real (broker) account's margin, positions and stop-alert state — the same content on the
 *  Real account page (BrokerAccount.jsx) and, toggled into view, on the Portfolio page. Broker
 *  positions come flat from the broker (no strategy/expiry grouping, greeks or virtual-account-
 *  style risk figures), so this shows what the data actually supports rather than forcing it into
 *  the virtual account's Group layout. When no broker is connected, `summary.source === 'approx'`
 *  and the figures fall back to the virtual account's own numbers, clearly flagged. */
export default function RealAccountView({ summary, positions, stops, error, heading }) {
  const isReal = summary?.source === 'broker'
  const netPositions = (positions ?? []).filter((p) => p.quantity !== 0)

  return (
    <>
      <section className="statement">
        <div className="statement-main">
          {heading && <h1 className="sr-only">{heading}</h1>}
          <p className="statement-label">Available margin (cash + collateral)</p>
          {isReal && <UpdatedTag ts={summary.synced_at} label="Synced" />}
          {summary ? (
            <>
              <p className="statement-value display-num">{rupee(summary.available_margin_total)}</p>
              <p className="lede">
                {rupee(summary.available_cash)} cash + {rupee(summary.total_collateral)} collateral.
                Real orders are still checked against cash only — the exchange caps how much of a
                trade collateral can fund.
              </p>
            </>
          ) : (
            <span className="skeleton" style={{ width: 260, height: 56 }} />
          )}
        </div>
        {summary && (
          <EquityBar used={summary.used_margin} free={summary.available_cash} usedLabel="Used margin" freeLabel="Available cash" />
        )}
      </section>

      {error && <div className="alert" role="alert"><AlertTriangle size={18} aria-hidden /> {error}</div>}

      {summary && !isReal && (
        <p className="notice muted-notice">
          <Info size={16} aria-hidden />
          {summary.status === 'expired'
            ? ' Your Zerodha connection expired — showing approximate figures from your virtual account until you reconnect. '
            : ' No broker is connected — showing approximate figures from your virtual account. '}
          <Link to="/broker">{summary.status === 'expired' ? 'Reconnect' : 'Connect a broker'} →</Link>
        </p>
      )}

      <section className="ledger" aria-label="Real broker margin detail">
        {summary ? (
          <>
            <StatCard label="Span" value={rupee(summary.span)} sub="SPAN risk margin on open positions" />
            <StatCard label="Exposure" value={rupee(summary.exposure)} sub="additional exchange exposure margin" />
            <StatCard label="Total collateral" value={rupee(summary.total_collateral)} sub="pledged stock/MF, before use" />
            <StatCard label="Collateral (liquid funds)" value={rupee(summary.collateral_liquid_used)} sub="of your used margin, funded by liquid MF/ETF collateral" />
            <StatCard label="Collateral (equity)" value={rupee(summary.collateral_equity_used)} sub="of your used margin, funded by pledged stock" />
            <StatCard label="Open positions" value={summary.open_positions} sub={isReal ? 'at your broker, right now' : 'in your virtual account'} />
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

      <section className="card">
        <header className="card-head"><h2>Open positions</h2></header>
        <div className="table-scroll">
          {isReal ? (
            netPositions.length ? (
              <table className="legs history">
                <thead>
                  <tr><th>Instrument</th><th className="num">Qty</th><th className="num">Avg price</th><th className="num">LTP</th><th className="num">P&amp;L</th></tr>
                </thead>
                <tbody>
                  {netPositions.map((p, i) => (
                    <tr key={p.tradingsymbol ?? i}>
                      <td data-label="Instrument">{p.tradingsymbol}</td>
                      <td data-label="Qty" className="num mono">{num(p.quantity)}</td>
                      <td data-label="Avg price" className="num mono">{num(p.average_price)}</td>
                      <td data-label="LTP" className="num mono">{num(p.last_price)}</td>
                      <td data-label="P&L" className={`num mono ${pnlClass(p.pnl)}`}>{signedRupee(p.pnl)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="empty">{positions ? 'No open positions at your broker right now.' : 'Loading…'}</p>
            )
          ) : (
            <p className="empty">
              {summary ? <>See your virtual open positions on the <Link to="/portfolio">Portfolio page</Link>.</> : 'Loading…'}
            </p>
          )}
        </div>
      </section>

      {isReal && stops?.length > 0 && (
        <section className="card">
          <header className="card-head"><h2>Stop losses at your broker</h2></header>
          <p className="muted small">
            From day 15 of a filled leg, a Kite alert buys it back if its price reaches the premium you sold at.
            The alert sits at Zerodha, so it works even when Theta Desk is offline.
          </p>
          <div className="table-scroll">
            <table className="legs history">
              <thead>
                <tr><th>Leg</th><th className="num">Qty</th><th className="num">Sold at</th><th className="num">Stop</th><th>Status</th></tr>
              </thead>
              <tbody>
                {stops.map((s) => (
                  <tr key={s.id}>
                    <td data-label="Leg">{s.symbol} {shortDate(s.expiry)} {num(s.strike)} {s.side}</td>
                    <td data-label="Qty" className="num mono">{num(s.qty)}</td>
                    <td data-label="Sold at" className="num mono">{s.average_price != null ? rupee2(s.average_price) : '—'}</td>
                    <td data-label="Stop" className="num mono">{s.sl_price != null ? rupee2(s.sl_price) : '—'}</td>
                    <td data-label="Status" title={s.sl_alert_error ?? undefined}>{stopStatus(s)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  )
}

function stopStatus(s) {
  if (s.status === 'open') return 'Waiting for the entry to fill'
  switch (s.sl_alert_status) {
    case 'pending': return s.sl_alert_error ? `Install failed, retrying: ${s.sl_alert_error}` : `Installs on ${shortDate(s.sl_activates_on)}`
    case 'enabled': return 'Installed at Zerodha'
    case 'triggered': return 'Triggered: buy-back order placed'
    case 'cancelled': return 'Removed: position closed first'
    case 'skipped': return s.sl_alert_error ?? 'Not installed'
    default: return `Alert ${s.sl_alert_status} at Zerodha`
  }
}
