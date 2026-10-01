import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, Medal } from 'lucide-react'
import { rpc } from '../rpc'
import { useAuth } from '../auth'
import { useTitle } from '../brand'

// Monthly paper-trading leaderboard (issue #125). Public: signed-out visitors see it too, with a
// call to join. Only nicknames, levels and ratios ever reach the page, never rupee amounts.

const monthName = (m) => new Date(`${m}-01T00:00:00`).toLocaleString('en-IN', { month: 'long', year: 'numeric' })
const fix = (v, d = 2) => Number(v).toFixed(d)

function Board({ band }) {
  return (
    <section className="card">
      <div className="card-head"><h2>{band.levels}</h2></div>
      {band.rows.length ? (
        <table className="admin-table leaderboard-table">
          <thead>
            <tr><th>#</th><th>Nickname</th><th>Level</th><th>Return ÷ drawdown</th><th>Return</th>
              <th>Max drawdown</th><th>Trades</th><th>Win rate</th></tr>
          </thead>
          <tbody>
            {band.rows.map((r) => (
              <tr key={r.rank}>
                <td className="num" data-label="Rank">{r.rank}</td>
                <td data-label="Nickname"><strong>{r.nickname}</strong></td>
                <td data-label="Level"><span className="chip">L{r.level}</span></td>
                <td className="num" data-label="Return ÷ drawdown"><strong>{fix(r.ratio)}</strong></td>
                <td className={`num ${r.return_pct < 0 ? 'neg' : 'pos'}`} data-label="Return">{fix(r.return_pct)}%</td>
                <td className="num" data-label="Max drawdown">{fix(r.max_dd_pct)}%</td>
                <td className="num" data-label="Trades">{r.trades}</td>
                <td className="num" data-label="Win rate">{fix(r.win_rate, 1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="muted">Nobody qualifies in this band yet.</p>}
    </section>
  )
}

export default function Leaderboard() {
  const { user } = useAuth()
  const [month, setMonth] = useState(null)
  const [b, setB] = useState(null)
  const [error, setError] = useState(null)
  useTitle('Leaderboard')
  useEffect(() => {
    rpc('leaderboard_get', month ? { month } : {}).then((r) => { setB(r); setError(null) }).catch((e) => setError(e.message))
  }, [month])

  return (
    <div className="detail leaderboard">
      <header className="page-head">
        <div>
          <h1 className="display"><Medal size={26} aria-hidden /> Monthly leaderboard</h1>
          <p className="lede"><span className="chip">Paper trading, educational</span> Ranked by return divided by
            max drawdown, ties by return. Virtual money only, never real-money figures.</p>
        </div>
        {b && (
          <select aria-label="Month" value={b.month} onChange={(e) => setMonth(e.target.value)}>
            {b.months.map((m, i) => <option key={m} value={m}>{monthName(m)}{i === 0 ? ' (so far)' : ''}</option>)}
          </select>
        )}
      </header>

      {!user && (
        <section className="card">
          <p>Learn option selling with paper money and climb ten levels. <Link to="/register" className="btn primary small">Join free and start at Level 1</Link></p>
        </section>
      )}
      {user && user.level < (b?.min_level ?? 4) && (
        <section className="card" role="note">
          <p>Reach Level {b?.min_level ?? 4} to compete. You're at Level {user.level}: keep the stop-loss on and the
            delta low. <Link to="/progress">See what's next</Link></p>
        </section>
      )}
      {user && user.leaderboard_opt_in === false && (
        <p className="muted small">You've chosen not to appear here. Change it on <Link to="/progress">My progress</Link>.</p>
      )}

      {error && <p className="form-error" role="alert"><AlertCircle size={15} aria-hidden /> {error}</p>}
      {b && (
        <>
          {b.provisional && <p className="muted" role="status">{monthName(b.month)} so far: provisional, final on the 1st.</p>}
          {b.bands.map((band) => <Board key={band.band} band={band} />)}
          <p className="muted small">Counts players who opted in, reached Level {b.min_level} and closed at least {b.min_trades} paper
            trades (each leg counts) in the month. Nicknames only.</p>
        </>
      )}
    </div>
  )
}
