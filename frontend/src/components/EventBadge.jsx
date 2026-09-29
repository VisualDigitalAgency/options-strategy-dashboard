import { useId, useLayoutEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'
import { EVENT_LABEL, awayText, dayDate, dayMonth, eventNote } from '../events'

// The stock's corporate events up to this row's expiry, as one chip: the next event and its date,
// "+n" for the rest. Hover or focus opens the list; a tap toggles it (touch has no hover). Clicks
// inside never reach the row or card link it sits in.
export default function EventBadge({ events, expiry }) {
  const [open, setOpen] = useState(false)
  const [place, setPlace] = useState({ up: false, shift: 0 })
  const ref = useRef(null)
  // A tap fires hover, then focus, then click: judge the click by the state before the tap began,
  // or the tap would open the list and close it again.
  const wasOpen = useRef(null)
  const id = useId()
  const navigate = useNavigate()

  // Open upward near the bottom of the viewport, and shift sideways so the panel stays on screen.
  useLayoutEffect(() => {
    if (!open || !ref.current) return
    const r = ref.current.getBoundingClientRect()
    const w = Math.min(300, window.innerWidth - 32)
    const left = Math.max(16, Math.min(r.left, window.innerWidth - 16 - w))
    setPlace({ up: window.innerHeight - r.bottom < 240 && r.top > 240, shift: Math.round(left - r.left) })
  }, [open])

  if (!events?.length) return null
  const risky = events.some((e) => e.risky)
  const first = events[0]
  const more = events.length - 1
  const label = `${events.length} event${more ? 's' : ''} before expiry. Next: ${EVENT_LABEL[first.type] ?? first.type} ${dayMonth(first.date)}`
  const stop = (e) => { e.preventDefault(); e.stopPropagation() }

  return (
    <span className="ev-wrap" ref={ref} onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
      onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget)) setOpen(false) }}>
      <button type="button" className={`chip ev-badge ${risky ? 'risky' : ''}`} aria-label={label} aria-expanded={open} aria-controls={id}
        onPointerDown={() => { wasOpen.current = open }} onFocus={() => setOpen(true)}
        onClick={(e) => { stop(e); const was = wasOpen.current; wasOpen.current = null; setOpen(was == null ? (o) => !o : !was) }}>
        {EVENT_LABEL[first.type] ?? first.type} <span className="num">{dayMonth(first.date)}</span>
        {more > 0 && <span className="ev-more num">+{more}</span>}
      </button>
      {open && (
        // Clicks inside must not open the row behind it.
        <div id={id} className={`ev-pop ${place.up ? 'up' : ''}`} style={{ left: place.shift }} onClick={stop}>
          <div className="ev-panel">
            <p className="ev-pop-head">{expiry ? `Before the ${dayMonth(expiry)} expiry` : 'Upcoming events'}</p>
            <ul>
              {events.map((e) => {
                const note = eventNote(e)
                return (
                  <li key={`${e.type}-${e.date}`}>
                    <span className="ev-pop-date num">{dayDate(e.date)}</span>
                    <span className="ev-pop-what">
                      <b className={e.risky ? 'risky' : ''}>{EVENT_LABEL[e.type] ?? e.type}</b>
                      {note && <small>{note}</small>}
                    </span>
                    <span className="ev-pop-away num">{awayText(e.days_away)}</span>
                  </li>
                )
              })}
            </ul>
            <button type="button" className="link-btn ev-pop-link" onClick={(e) => { stop(e); navigate('/calendar') }}>
              Market calendar <ArrowRight size={13} aria-hidden />
            </button>
          </div>
        </div>
      )}
    </span>
  )
}
