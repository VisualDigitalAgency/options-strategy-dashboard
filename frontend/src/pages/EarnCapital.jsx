import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, CheckCircle2, Circle, Coins } from 'lucide-react'
import { rpc } from '../rpc'
import { dateTime, rupee } from '../format'
import { useTitle } from '../brand'

// Virtual capital milestones (#47): every account starts at ₹2 lakh and grows only by completing
// these tasks. The server checks each one from its own data and pays it once.
export default function EarnCapital() {
  const [s, setS] = useState(null)
  const [error, setError] = useState(null)
  useTitle('Earn virtual capital')
  useEffect(() => { rpc('capital_status').then(setS).catch((e) => setError(e.message)) }, [])

  return (
    <div className="detail capital-page">
      <header className="page-head">
        <div>
          <h1 className="display"><Coins size={26} aria-hidden /> Earn virtual capital</h1>
          <p className="lede">Every account starts with {s ? rupee(s.start) : '₹2,00,000'}. More capital is earned, not given:
            trade with discipline, finish the courses and bring in traders who stick with it.</p>
        </div>
        {s?.capital != null && <div className="capital-now"><span className="muted small">Your capital</span><b className="mono">{rupee(s.capital)}</b></div>}
      </header>
      {error && <div className="alert" role="alert"><AlertCircle size={18} aria-hidden /> {error}</div>}
      {!s && !error && <p className="muted">Loading…</p>}
      {s && (
        <>
          <section className="card capital-tasks" aria-labelledby="ct-h">
            <h2 id="ct-h">Tasks</h2>
            <ol>
              {s.tasks.map((t) => {
                const full = t.done >= t.max
                return (
                  <li key={t.key} className={full ? 'ok' : ''}>
                    {full ? <CheckCircle2 size={16} aria-hidden /> : <Circle size={16} aria-hidden />}
                    <span className="ct-label">{full ? t.label : <Link to={t.link}>{t.label}</Link>}
                      {t.progress && !full && <span className="muted small"> · {t.progress}</span>}
                      {t.max > 1 && <span className="muted small"> · paid {t.done} of {t.max}</span>}
                    </span>
                    <b className="mono ct-reward">+{rupee(t.reward)}</b>
                  </li>
                )
              })}
            </ol>
          </section>
          <section className="card capital-tasks" aria-labelledby="cl-h">
            <h2 id="cl-h">Levels</h2>
            <ol>
              {s.levels.map((l) => (
                <li key={l.level} className={l.done ? 'ok' : ''}>
                  {l.done ? <CheckCircle2 size={16} aria-hidden /> : <Circle size={16} aria-hidden />}
                  <span className="ct-label">{l.done ? `Reach Level ${l.level}` : <Link to="/progress">Reach Level {l.level}</Link>}</span>
                  <b className="mono ct-reward">+{rupee(l.reward)}</b>
                </li>
              ))}
            </ol>
          </section>
          <section className="card" aria-labelledby="cg-h">
            <div className="card-head"><h2 id="cg-h">Earned so far</h2></div>
            {s.grants.length ? (
              <ul className="capital-grants">
                {s.grants.map((g) => (
                  <li key={`${g.task}:${g.ref}`}><span>{g.label}{g.ref && g.task !== 'level' ? <span className="muted small"> · {g.ref}</span> : null}</span>
                    <span className="muted small">{dateTime(g.created_at)}</span>
                    {g.revoked ? <b className="mono muted" title="Taken back by the owner">Revoked</b> : <b className="mono pos">+{rupee(g.amount)}</b>}</li>
                ))}
              </ul>
            ) : <p className="muted">Nothing yet. Start with the Level 1 lessons and a first trade with its stop-loss on.</p>}
            <p className="muted small">Earned capital adds to your account, not to your profit: return % and the leaderboard measure trading only.</p>
          </section>
        </>
      )}
    </div>
  )
}
