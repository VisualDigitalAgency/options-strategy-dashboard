import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, ArrowRightLeft, CircleDollarSign } from 'lucide-react'
import { rpc } from '../rpc'
import { int, rupee, shortDate } from '../format'
import { useBudget } from '../settings'
import { useTitle } from '../brand'

// Coins (#47): a reward on top of the capital grants, earned for discipline and exchanged one way
// into virtual capital. The server checks every coin; this page only shows them.
export default function Coins() {
  const [s, setS] = useState(null)
  const [error, setError] = useState(null)
  const [amount, setAmount] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(null)
  const budget = useBudget()
  useTitle('Coins')
  const load = () => rpc('coins_status').then(setS).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  const n = Number(amount)
  const valid = Number.isInteger(n) && n > 0 && s && n <= s.balance
  const exchange = async () => {
    setBusy(true); setError(null); setDone(null)
    try {
      const r = await rpc('coins_exchange', { coins: n })
      setDone(r); setAmount(''); budget?.refresh?.(); await load()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  return (
    <div className="detail coins-page">
      <header className="page-head">
        <div>
          <h1 className="display"><CircleDollarSign size={26} aria-hidden /> Coins</h1>
          <p className="lede">Earned for trading with discipline, on top of the capital you earn. Exchange them for
            virtual capital at {s ? rupee(s.rupees_per_coin) : '₹100'} a coin. Exchanges are one way.</p>
        </div>
        {s && <div className="capital-now"><span className="muted small">Your coins</span><b className="mono">{int(s.balance)}</b></div>}
      </header>
      {error && <div className="alert" role="alert"><AlertCircle size={18} aria-hidden /> {error}</div>}
      {!s && !error && <p className="muted">Loading…</p>}
      {s && (
        <>
          <section className="card coins-exchange" aria-labelledby="cx-h">
            <h2 id="cx-h"><ArrowRightLeft size={18} aria-hidden /> Exchange for virtual capital</h2>
            <div className="coins-row">
              <label htmlFor="cx-n" className="sr-only">Coins to exchange</label>
              <input id="cx-n" className="input" type="number" inputMode="numeric" min="1" max={s.balance} step="1" placeholder="Coins"
                value={amount} onChange={(e) => setAmount(e.target.value)} />
              <span className="muted">= {valid ? rupee(n * s.rupees_per_coin) : '₹0'}</span>
              <button className="btn primary" disabled={!valid || busy} onClick={exchange}>{busy ? 'Exchanging…' : 'Exchange'}</button>
            </div>
            {done && <p className="pos small" role="status">Added {rupee(done.rupees)} to your virtual account.</p>}
            <p className="muted small">Exchanged capital adds to your account, not to your profit, and stays after a reset.
              It can't be turned back into coins.</p>
          </section>
          <section className="card capital-tasks" aria-labelledby="ce-h">
            <h2 id="ce-h">How to earn coins</h2>
            <ol>
              {s.rules.map((r) => (
                <li key={r.key}><span />
                  <span className="ct-label">{r.label}
                    {r.max && <span className="muted small"> · up to {r.max}{r.per ? ` a ${r.per}` : ''}{r.done != null ? ` (${r.done} this month)` : ''}</span>}
                  </span>
                  <b className="mono ct-reward">+{r.coins}</b>
                </li>
              ))}
              <li><span /><span className="ct-label">Reach a level ({s.levels.map((l) => `${l.level}: ${l.coins}`).join(' · ')})</span><b className="mono ct-reward">+25–100</b></li>
            </ol>
            <p className="muted small">Capital rewards for the same tasks are on <Link to="/capital">Earn capital</Link>.</p>
          </section>
          <section className="card" aria-labelledby="ch-h">
            <div className="card-head"><h2 id="ch-h">History</h2></div>
            {s.history.length ? (
              <ul className="capital-grants">
                {s.history.map((h) => (
                  <li key={`${h.kind}:${h.ref}`}><span>{h.label}</span><span className="muted small">{shortDate(h.created_at)}</span>
                    <b className={`mono ${h.coins > 0 ? 'pos' : 'neg'}`}>{h.coins > 0 ? '+' : '−'}{Math.abs(h.coins)}</b></li>
                ))}
              </ul>
            ) : <p className="muted">No coins yet. Pass the Level 1 lessons to earn your first.</p>}
          </section>
        </>
      )}
    </div>
  )
}
