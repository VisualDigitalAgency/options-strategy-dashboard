import { useState } from 'react'
import { CalendarClock } from 'lucide-react'
import { shortDate } from '../format'
import { EVENT_LABEL } from '../events'

const away = (d) => (d === 0 ? 'today' : d === 1 ? 'tomorrow' : `in ${d} days`)

// Corporate events on or before this row's expiry. Hover or focus shows the details; a tap toggles
// them (touch has no hover), and the tap never opens the row or card it sits in.
export default function EventBadge({ events }) {
  const [open, setOpen] = useState(false)
  if (!events?.length) return null
  const risky = events.some((e) => e.risky)
  const first = events[0]
  const label = `${events.length} event${events.length > 1 ? 's' : ''} before expiry, next: ${EVENT_LABEL[first.type] ?? first.type} ${away(first.days_away)}`
  const toggle = (e) => { e.preventDefault(); e.stopPropagation(); setOpen((o) => !o) }
  return (
    <span className="ev-wrap" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
      <button type="button" className={`ev-badge ${risky ? 'risky' : ''}`} aria-label={label} aria-expanded={open}
        onClick={toggle} onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}>
        <CalendarClock size={12} aria-hidden />
        {events.length > 1 ? events.length : EVENT_LABEL[first.type] ?? first.type}
      </button>
      {open && (
        <span className="ev-tip" role="tooltip">
          {events.map((e) => (
            <span key={`${e.type}-${e.date}`} className={`ev-line ${e.risky ? 'risky' : ''}`}>
              <b>{EVENT_LABEL[e.type] ?? e.type}</b> <span className="num">{shortDate(e.date)}</span>{' '}
              <span className="muted">({away(e.days_away)})</span>
              {e.purpose && <small>{e.purpose}</small>}
            </span>
          ))}
        </span>
      )}
    </span>
  )
}
