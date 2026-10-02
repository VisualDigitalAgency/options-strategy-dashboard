import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, ChevronLeft, ChevronRight, Medal } from 'lucide-react'
import { rpc } from '../rpc'
import { useAuth } from '../auth'
import { useTitle } from '../brand'

// Paper-trading leaderboard (issue #125): monthly or quarterly, three bands from Rising (Levels 1-3)
// up. Public: signed-out visitors see it too, with a call to join. Only nicknames, levels and ratios
// ever reach the page, never rupee amounts.

const periodName = (p) => (p.includes('Q') ? `Q${p.slice(-1)} ${p.slice(0, 4)}`
  : new Date(`${p}-01T00:00:00`).toLocaleString('en-IN', { month: 'long', year: 'numeric' }))
const fix = (v, d = 2) => Number(v).toFixed(d)
const pctClass = (v) => (v < 0 ? 'neg' : 'pos')

function Stats({ r }) {
  return (
    <span className="lb-stats">
      <span className={pctClass(r.return_pct)}>{fix(r.return_pct)}% return</span>
      <span>{fix(r.max_dd_pct)}% drawdown</span>
      <span>{r.trades} trades · {fix(r.win_rate, 0)}% won</span>
    </span>
  )
}

function Board({ band, me }) {
  const podium = band.rows.slice(0, 3)
  return (
    <section className="card lb-band" aria-label={band.levels}>
      <div className="card-head"><h2>{band.levels}</h2>{band.range !== band.levels && <span className="muted small">{band.range}</span>}</div>
      <ol className="lb-podium">
        {podium.map((r) => (
          <li key={r.rank} className={`lb-place p${r.rank}${r.nickname === me ? ' me' : ''}`}>
            <span className="lb-medal" aria-label={`Rank ${r.rank}`}>{r.rank}</span>
            <strong className="lb-nick">{r.nickname}{r.nickname === me && <span className="chip">You</span>}</strong>
            <span className="chip">Level {r.level}</span>
            <span className="lb-ratio num">{fix(r.ratio)}<small>return ÷ drawdown</small></span>
            <Stats r={r} />
          </li>
        ))}
      </ol>
      {band.rows.length > 3 && (
        <ol className="lb-rows" start={4}>
          {band.rows.slice(3).map((r) => (
            <li key={r.rank} className={r.nickname === me ? 'me' : ''}>
              <span className="lb-rank num">{r.rank}</span>
              <span className="lb-who"><strong>{r.nickname}</strong> <span className="chip">L{r.level}</span>{r.nickname === me && <span className="chip">You</span>}</span>
              <Stats r={r} />
              <strong className="lb-ratio-sm num">{fix(r.ratio)}</strong>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

function Near({ rows, me }) {
  return (
    <section className="card lb-near" aria-label="Getting there">
      <div className="card-head"><h2>Getting there</h2><span className="muted small">Not ranked yet</span></div>
      <ul>
        {rows.map((r) => (
          <li key={r.nickname} className={r.nickname === me ? 'me' : ''}>
            <span className="lb-who"><strong>{r.nickname}</strong> <span className="chip">L{r.level}</span>{r.nickname === me && <span className="chip">You</span>}</span>
            <span className="lb-meter" aria-hidden><span style={{ width: `${Math.min(100, (r.trades / r.need) * 100)}%` }} /></span>
            <span className="muted small num">{r.trades} of {r.need} trades</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

export default function Leaderboard() {
  const { user } = useAuth()
  const [kind, setKind] = useState('month')
  const [period, setPeriod] = useState(null)
  const [b, setB] = useState(null)
  const [error, setError] = useState(null)
  useTitle('Leaderboard')
  useEffect(() => {
    rpc('leaderboard_get', period ? { month: period } : {}).then((r) => { setB(r); setError(null) }).catch((e) => setError(e.message))
  }, [period])

  const list = b ? (kind === 'quarter' ? b.quarters : b.months) : []
  const at = b ? list.indexOf(b.month) : -1
  const pick = (k) => { setKind(k); setPeriod(k === 'quarter' ? b?.quarters[0] : null) }
  const filled = b?.bands.filter((x) => x.rows.length) ?? []
  const empty = b?.bands.filter((x) => !x.rows.length) ?? []
  const need = b ? b.min_trades * (b.kind === 'quarter' ? 3 : 1) : 5
  const mine = user && b?.near?.find((r) => r.nickname === user.nickname)
  const onBoard = user && filled.some((x) => x.rows.some((r) => r.nickname === user.nickname))

  return (
    <div className="detail leaderboard">
      <header className="page-head">
        <div>
          <h1 className="display"><Medal size={26} aria-hidden /> Leaderboard</h1>
          <p className="lede"><span className="chip">Paper trading, educational</span> Ranked by return divided by
            max drawdown, ties by return. Virtual money only.</p>
        </div>
      </header>

      {b && (
        <div className="lb-controls">
          <div className="segmented" role="group" aria-label="Period">
            <button className={kind === 'month' ? 'active' : ''} aria-pressed={kind === 'month'} onClick={() => pick('month')}>Monthly</button>
            <button className={kind === 'quarter' ? 'active' : ''} aria-pressed={kind === 'quarter'} onClick={() => pick('quarter')}>Quarterly</button>
          </div>
          <div className="lb-stepper">
            <button className="icon-btn" aria-label="Earlier" disabled={at < 0 || at >= list.length - 1} onClick={() => setPeriod(list[at + 1])}><ChevronLeft size={18} /></button>
            <span className="lb-period">{periodName(b.month)}{b.provisional && <span className="chip">so far</span>}</span>
            <button className="icon-btn" aria-label="Later" disabled={at <= 0} onClick={() => setPeriod(list[at - 1])}><ChevronRight size={18} /></button>
          </div>
        </div>
      )}

      {!user && (
        <section className="card lb-cta">
          <p>Learn option selling with paper money and climb ten levels. Everyone ranks from Level 1.</p>
          <Link to="/register" className="btn primary small">Join free and start at Level 1</Link>
        </section>
      )}
      {user && !onBoard && (
        <p className="lb-note" role="note">
          {user.leaderboard_opt_in === false
            ? <>You've chosen not to appear here. Change it on <Link to="/progress">My progress</Link>.</>
            : <>{mine ? `You have ${mine.trades} of ${need} trades. ` : ''}Close {need} paper trades this {b?.kind === 'quarter' ? 'quarter' : 'month'} to get ranked, with the stop-loss on and the delta low.</>}
        </p>
      )}

      {error && <p className="form-error" role="alert"><AlertCircle size={15} aria-hidden /> {error}</p>}
      {b && (
        <>
          {filled.map((band) => <Board key={band.band} band={band} me={user?.nickname} />)}
          {b.near?.length > 0 && <Near rows={b.near} me={user?.nickname} />}
          {empty.length > 0 && (
            <p className="muted lb-empty">{filled.length ? 'Still open: ' : 'Nobody ranked yet this period: '}
              {empty.map((x) => x.levels).join(' · ')}. Be the first.</p>
          )}
          <p className="muted small">{b.provisional ? 'Provisional until the period ends. ' : ''}Counts players who opted in and
            closed at least {need} paper trades in the {b.kind} (each leg counts). Nicknames only.</p>
        </>
      )}
    </div>
  )
}
