import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, Circle, Rocket, X } from 'lucide-react'
import { rpc } from '../rpc'
import { useAuth } from '../auth'

// New-user checklist (#167): what leaving Level 1 takes, with live values from the level gate itself,
// so it always matches what the server decides. Shown on Portfolio and Progress until Level 2 (#198);
// dismissing hides it for this level only (per browser).
const LINKS = [[/lesson|quiz/i, '/learn'], [/trade/i, '/builder'], [/XP|days/i, '/progress']]
const key = (level) => `gs:dismissed:${level}`

export default function GettingStarted() {
  const user = useAuth()?.user
  const level = user?.level ?? 1
  const [p, setP] = useState(null)
  const [hidden, setHidden] = useState(() => { try { return !!localStorage.getItem(key(level)) } catch { return false } })
  const show = user && level === 1 && !hidden
  useEffect(() => { if (show) rpc('progress_get').then(setP).catch(() => {}) }, [show])
  if (!show || !p?.next) return null
  const steps = [{ label: 'Pick your nickname', ok: true }, ...p.next.checks]
  const done = steps.filter((s) => s.ok).length
  const dismiss = () => { try { localStorage.setItem(key(level), '1') } catch { /* no storage */ } setHidden(true) }
  return (
    <section className="card getting-started" aria-labelledby="gs-h">
      <header>
        <h2 id="gs-h"><Rocket size={18} aria-hidden /> Getting started · {done} of {steps.length}</h2>
        <button className="icon-btn" onClick={dismiss} aria-label="Hide getting started"><X size={16} aria-hidden /></button>
      </header>
      <p className="muted small">Finish these to reach Level 2 · {p.next.title}.</p>
      <div className="gs-bar" aria-hidden><span style={{ width: `${(100 * done) / steps.length}%` }} /></div>
      <ol>
        {steps.map((s) => {
          const to = !s.ok && LINKS.find(([re]) => re.test(s.label))?.[1]
          return (
            <li key={s.label} className={s.ok ? 'ok' : ''}>
              {s.ok ? <CheckCircle2 size={16} aria-hidden /> : <Circle size={16} aria-hidden />}
              {to ? <Link to={to}>{s.label}</Link> : <span>{s.label}</span>}
              {s.value != null && !s.ok && <span className="muted small">{String(s.value)}</span>}
              <span className="sr-only">{s.ok ? 'done' : 'to do'}</span>
            </li>
          )
        })}
      </ol>
    </section>
  )
}
