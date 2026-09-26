import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Plug } from 'lucide-react'
import { rpc } from '../rpc'
import { num, rupee, signedRupee } from '../format'
import { pnlClass } from './Portfolio'

function Fund({ label, value, sub, tone }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <span className={`stat-value mono ${tone ?? ''}`}>{value}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  )
}

/** Real Zerodha account: funds/margin and open positions exactly as the broker reports them —
 *  unlike the virtual account, this is not simulated, so figures come straight from the worker's
 *  broker_snap cache (engine/brokers/poller.py), not recomputed here. */
export default function BrokerAccount() {
  const [connection, setConnection] = useState(null)
  const [margins, setMargins] = useState(null)
  const [positions, setPositions] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    try {
      const s = await rpc('broker_status')
      setConnection(s)
      if (s.status === 'active') {
        const [m, p] = await Promise.all([rpc('broker_get_margins'), rpc('broker_get_positions')])
        setMargins(m)
        setPositions(p)
      }
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])

  useEffect(() => { document.title = 'Real account · Theta Desk'; load() }, [load])

  if (connection && connection.status !== 'active') {
    return (
      <div className="detail">
        <header className="page-head"><h1 className="display">Real account</h1></header>
        <div className="card empty-state">
          <Plug size={22} aria-hidden />
          <p>{connection.status === 'expired'
            ? 'Your Zerodha connection expired (broker sessions reset daily). Reconnect to see your real account.'
            : 'No broker is connected yet.'}</p>
          <Link className="btn primary" to="/broker">Go to Broker</Link>
        </div>
      </div>
    )
  }

  const netPositions = (positions ?? []).filter((p) => p.quantity !== 0)

  return (
    <div className="detail">
      <header className="page-head">
        <div>
          <h1 className="display">Real account</h1>
          <p className="lede">Live figures from your connected Zerodha account — real funds, real positions.</p>
        </div>
      </header>

      {error && <div className="alert" role="alert"><AlertTriangle size={18} aria-hidden /> {error}</div>}

      <section className="ledger" aria-label="Real broker funds">
        {margins ? (
          <>
            <Fund label="Available margin" value={rupee(margins.available_margin)} sub="free to place new real orders" />
            <Fund label="Cash margin" value={rupee(margins.cash_margin)} sub="your own funds" />
            <Fund label="Collateral margin" value={rupee(margins.collateral_margin)} sub="from pledged stock/MF, can't be withdrawn" />
            <Fund label="Open positions" value={netPositions.length} sub="at your broker, right now" />
          </>
        ) : (
          Array.from({ length: 4 }, (_, i) => (
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
          {netPositions.length ? (
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
          )}
        </div>
      </section>
    </div>
  )
}
