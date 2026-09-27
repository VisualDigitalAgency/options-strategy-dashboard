import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Info } from 'lucide-react'
import { rpc } from '../rpc'
import { num, rupee, signedRupee } from '../format'
import { pnlClass } from './Portfolio'
import StatCard from '../components/StatCard'
import UpdatedTag from '../components/UpdatedTag'

const Fund = StatCard

/** Real Zerodha account: funds/margin and open positions exactly as the broker reports them —
 *  unlike the virtual account, this is not simulated, so figures come straight from the worker's
 *  broker_snap cache (engine/brokers/poller.py), not recomputed here. Mirrors VirtualAccount.jsx's
 *  layout (statement hero + equity bar + ledger) so the two pages look the same. When no broker
 *  is connected, engine.broker.account_summary falls back to the virtual account's own numbers so
 *  this page always shows something, clearly flagged as approximate. */
export default function BrokerAccount() {
  const [summary, setSummary] = useState(null)
  const [positions, setPositions] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const s = await rpc('broker_account_summary')
      setSummary(s)
      if (s.source === 'broker') {
        setPositions(await rpc('broker_get_positions'))
      }
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => { document.title = 'Real account · Theta Desk'; load() }, [load])

  const isReal = summary?.source === 'broker'
  const netPositions = (positions ?? []).filter((p) => p.quantity !== 0)

  return (
    <div className="detail">
      <section className="statement">
        <div className="statement-main">
          <h1 className="sr-only">Real account</h1>
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
          <div className="equity" aria-label={`Margin in use ${rupee(summary.used_margin)}, available cash ${rupee(summary.available_cash)}`}>
            <div className="equity-bar" aria-hidden>
              <span className="eq-used" style={{ flexGrow: Math.max(summary.used_margin, 0) || 0.0001 }} />
              <span className="eq-free" style={{ flexGrow: Math.max(summary.available_cash, 0) || 0.0001 }} />
            </div>
            <div className="equity-legend">
              <span><i className="eq-used" aria-hidden /> Used margin <b className="num">{rupee(summary.used_margin)}</b></span>
              <span><i className="eq-free" aria-hidden /> Available cash <b className="num">{rupee(summary.available_cash)}</b></span>
            </div>
          </div>
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
            <Fund label="Span" value={rupee(summary.span)} sub="SPAN risk margin on open positions" />
            <Fund label="Exposure" value={rupee(summary.exposure)} sub="additional exchange exposure margin" />
            <Fund label="Total collateral" value={rupee(summary.total_collateral)} sub="pledged stock/MF, before use" />
            <Fund label="Collateral (liquid funds)" value={rupee(summary.collateral_liquid_used)} sub="of your used margin, funded by liquid MF/ETF collateral" />
            <Fund label="Collateral (equity)" value={rupee(summary.collateral_equity_used)} sub="of your used margin, funded by pledged stock" />
            <Fund label="Open positions" value={summary.open_positions} sub={isReal ? 'at your broker, right now' : 'in your virtual account'} />
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
    </div>
  )
}
