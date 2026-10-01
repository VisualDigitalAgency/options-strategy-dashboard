import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, CheckCircle2, Circle, Clock, PartyPopper, Share2, Trophy } from 'lucide-react'
import { rpc } from '../rpc'
import { useAuth } from '../auth'
import { markSeen, seenLevel } from '../levelSeen'
import ShareCard from '../components/ShareCard'

// Learning-path progress (issue #126): level, XP bar, the next level's checks and the XP ledger.
// The checks are the gate output itself, so the page always matches what evaluate() decides.

const REASONS = {
  trade_ok: 'Trade closed with stop-loss on and a safe delta',
  profit_bonus: 'Profit bonus',
  no_sl: 'Trade closed with the stop-loss off',
  high_delta: 'Sold too close to the money (high delta)',
  lesson: 'Lesson quiz passed',
}
const reasonText = (r) => REASONS[r] ?? r
const refText = (ref) => (ref?.startsWith('lesson:') ? ref.slice(7).replaceAll('-', ' ') : '')

function Celebration({ level, title, onClose, onShare }) {
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-labelledby="lvl-up">
      <div className="modal levelup">
        <PartyPopper size={40} aria-hidden />
        <h2 id="lvl-up">Level {level} · {title}</h2>
        <p className="muted">You moved up a level. Keep the stop-loss on and the delta low to keep climbing.</p>
        <div className="modal-actions">
          <button className="btn" onClick={onShare}><Share2 size={15} aria-hidden /> Share</button>
          <button className="btn primary" onClick={onClose} autoFocus>Keep going</button>
        </div>
      </div>
    </div>
  )
}

export default function Progress() {
  const { user, refresh } = useAuth()
  const [p, setP] = useState(null)
  const [hist, setHist] = useState([])
  const [error, setError] = useState(null)
  const [party, setParty] = useState(false)
  const [courses, setCourses] = useState([])
  const [share, setShare] = useState(null)

  useEffect(() => {
    document.title = 'My progress · Theta Desk'
    rpc('progress_get').then((r) => {
      setP(r)
      const seen = seenLevel()
      if (r.leveled_up || (seen && r.level > seen)) setParty(true)
      else markSeen(r.level)
      if (r.level !== user?.level) refresh()
    }).catch((e) => setError(e.message))
    rpc('progress_history', { limit: 50 }).then(setHist).catch(() => {})
    // A course is every lesson of one level; finished ones can be shared.
    Promise.all([rpc('lessons_list'), rpc('lesson_progress')]).then(([list, done]) => {
      const passed = new Set(done.filter((d) => d.passed_at).map((d) => d.slug))
      const levels = [...new Set(list.map((l) => l.level))]
      setCourses(levels.filter((lv) => list.filter((l) => l.level === lv).every((l) => passed.has(l.slug))))
    }).catch(() => {})
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const close = () => { markSeen(p.level); setParty(false); refresh() }
  const n = p?.next
  const pct = n ? Math.min(1, Math.max(0, (p.xp - n.xp_from) / (n.xp_needed - n.xp_from))) : 1
  const daysLeft = n ? Math.max(0, n.min_days - n.days) : 0

  return (
    <div className="detail progress-page">
      <header className="page-head">
        <div>
          <h1 className="display"><Trophy size={26} aria-hidden /> My progress</h1>
          <p className="lede">Paper trading only. XP comes from discipline: stop-loss on, low delta, lessons passed.</p>
        </div>
      </header>
      {error && <div className="alert" role="alert"><AlertCircle size={18} aria-hidden /> {error}</div>}
      {p && (
        <>
          <section className="card">
            <div className="level-head">
              <span className="level-badge num">{p.level}</span>
              <div><b>Level {p.level} · {p.title}</b><div className="muted small num">{p.xp.toLocaleString('en-IN')} XP</div></div>
            </div>
            {n ? (
              <div className="progress">
                <div className="progress-text"><span>To Level {n.level} · {n.title}</span>
                  <b className="num">{p.xp.toLocaleString('en-IN')} / {n.xp_needed.toLocaleString('en-IN')} XP</b></div>
                <div className="progress-track" role="progressbar" aria-valuenow={Math.round(pct * 100)} aria-valuemin={0} aria-valuemax={100}>
                  <div className="progress-fill" style={{ transform: `scaleX(${pct})` }} />
                </div>
                <span className="muted small"><Clock size={13} aria-hidden />{' '}
                  {daysLeft ? `At least ${daysLeft} more day${daysLeft === 1 ? '' : 's'} at this level` : 'Minimum time at this level done'}</span>
              </div>
            ) : <p className="muted">Top level reached.</p>}
          </section>

          {n && (
            <section className="card">
              <div className="card-head"><h2>What Level {n.level} needs</h2></div>
              <ul className="checklist">
                {n.checks.map((c, i) => (
                  <li key={i} className={c.ok ? 'ok' : ''}>
                    {c.ok ? <CheckCircle2 size={16} aria-label="done" /> : <Circle size={16} aria-label="not yet" />}
                    <span>{c.label}</span>
                    {c.value != null && <span className="muted num">{typeof c.value === 'number' ? c.value.toLocaleString('en-IN') : c.value}</span>}
                  </li>
                ))}
              </ul>
              <p className="muted small">Trade checks count legs closed since you reached this level (or your last account reset). <Link to="/learn">Lessons</Link> add XP too.</p>
            </section>
          )}

          <section className="card">
            <div className="card-head"><h2><Share2 size={16} aria-hidden /> Share</h2></div>
            <div className="share-list">
              <button className="btn" onClick={() => setShare({ kind: 'level', refNo: p.level, label: `Level ${p.level} · ${p.title}` })}>
                Level {p.level} · {p.title}
              </button>
              {courses.map((c) => (
                <button key={c} className="btn" onClick={() => setShare({ kind: 'course', refNo: c, label: `Level ${c} course complete` })}>
                  Level {c} course complete
                </button>
              ))}
            </div>
          </section>

          <section className="card">
            <div className="card-head"><h2>XP history</h2></div>
            {hist.length ? (
              <ul className="xp-list">
                {hist.map((h, i) => (
                  <li key={i}>
                    <span>{reasonText(h.reason)} <span className="muted small">{refText(h.ref)}</span></span>
                    <span className={`num ${h.points < 0 ? 'neg' : 'pos'}`}>{h.points > 0 ? '+' : ''}{h.points}</span>
                  </li>
                ))}
              </ul>
            ) : <p className="muted">No XP yet. Pass a <Link to="/learn">lesson</Link> or close a paper trade to start.</p>}
          </section>
        </>
      )}
      {party && p && <Celebration level={p.level} title={p.title} onClose={close}
        onShare={() => { close(); setShare({ kind: 'level', refNo: p.level, label: `Level ${p.level} · ${p.title}` }) }} />}
      {share && <ShareCard {...share} onClose={() => setShare(null)} />}
    </div>
  )
}
