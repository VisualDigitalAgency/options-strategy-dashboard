import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertCircle, CheckCircle2, Circle, Clock, Copy, Medal, PartyPopper, Share2, Trophy, UserPlus } from 'lucide-react'
import { rpc } from '../rpc'
import { useAuth } from '../auth'
import { markSeen, seenLevel } from '../levelSeen'
import ShareCard from '../components/ShareCard'
import { useTitle } from '../brand'

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

// Readers (#163): a signed-out visitor sees the levels and what each unlocks, with a way to join.
function LevelLadder() {
  const [levels, setLevels] = useState(null)
  const [error, setError] = useState(null)
  useTitle('Levels')
  useEffect(() => { rpc('levels_overview').then(setLevels).catch((e) => setError(e.message)) }, [])
  return (
    <div className="detail progress">
      <header className="page-head">
        <div>
          <h1 className="display"><Trophy size={26} aria-hidden /> Ten levels, from Learner to Theta Master</h1>
          <p className="lede">Every account climbs by trading safely on a virtual account: stop-loss on, delta low, drawdown small.
            Each level unlocks more of the app.</p>
        </div>
      </header>
      {error && <div className="alert" role="alert"><AlertCircle size={18} aria-hidden /> {error}</div>}
      {levels && (
        <ol className="card level-ladder">
          {levels.map((l) => (
            <li key={l.level}>
              <b>Level {l.level} · {l.title}</b>
              {l.min_days && <span className="muted small"> · at least {l.min_days} days</span>}
              {l.unlocks.map((u) => <span key={u} className="muted small block">Unlocks: {u}</span>)}
            </li>
          ))}
        </ol>
      )}
      <section className="card quiz-cta">
        <h2>Start at Level 1 for free</h2>
        <p>Create a free account to trade on a ₹2 lakh virtual account (earn more as you go), take the lesson quizzes and track your climb.</p>
        <div className="quiz-cta-actions">
          <Link to="/register" className="btn primary">Join free</Link>
          <Link to="/login?next=%2Fprogress" className="btn ghost">Sign in</Link>
        </div>
      </section>
    </div>
  )
}

export default function Progress() {
  return useAuth().user ? <MyProgress /> : <LevelLadder />
}

function MyProgress() {
  const { user, refresh } = useAuth()
  const [p, setP] = useState(null)
  const [hist, setHist] = useState([])
  const [error, setError] = useState(null)
  const [party, setParty] = useState(false)
  const [courses, setCourses] = useState([])
  const [share, setShare] = useState(null)
  const [invite, setInvite] = useState(null)
  const [copied, setCopied] = useState(false)
  const [optBusy, setOptBusy] = useState(false)

  useTitle('My progress')
  useEffect(() => {
    rpc('progress_get').then((r) => {
      setP(r)
      const seen = seenLevel()
      if (r.leveled_up || (seen && r.level > seen)) setParty(true)
      else markSeen(r.level)
      if (r.level !== user?.level) refresh()
    }).catch((e) => setError(e.message))
    rpc('progress_history', { limit: 50 }).then(setHist).catch(() => {})
    rpc('referral_get').then(setInvite).catch(() => {})
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

          {invite && (
            <section className="card">
              <div className="card-head"><h2><UserPlus size={16} aria-hidden /> Invite friends</h2>
                <span className="muted small">{invite.joined} joined through your link</span></div>
              <div className="invite-row">
                <input className="mono" readOnly value={invite.url} aria-label="Your invite link" onFocus={(e) => e.target.select()} />
                <button className="btn" onClick={async () => {
                  try { await navigator.clipboard.writeText(invite.url); setCopied(true) } catch { /* clipboard blocked */ }
                }}><Copy size={15} aria-hidden /> {copied ? 'Copied' : 'Copy'}</button>
              </div>
              <p className="muted small">Your share cards carry this link too.</p>
            </section>
          )}

          <section className="card">
            <div className="card-head"><h2><Medal size={16} aria-hidden /> Leaderboard</h2>
              <Link to="/leaderboard" className="muted small">See the board</Link></div>
            <label className="check-row">
              <input type="checkbox" checked={!!user?.leaderboard_opt_in} disabled={optBusy} onChange={async (e) => {
                setOptBusy(true)
                try { await rpc('profile_set', { leaderboard_opt_in: e.target.checked }); await refresh() } catch { /* stays as it was */ }
                setOptBusy(false)
              }} />
              Show me on the monthly paper-trading leaderboard (nickname only)
            </label>
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
