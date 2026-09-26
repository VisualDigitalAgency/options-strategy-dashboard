import { useEffect, useState } from 'react'
import { Clock, RefreshCw } from 'lucide-react'
import { istNow } from '../market'

/** Accepts epoch seconds (screen) or an IST 'YYYY-MM-DD HH:MM:SS' string (positions). Returns an IST Date. */
function toIst(ts) {
  if (ts == null) return null
  if (typeof ts === 'number') return istNow(new Date(ts * 1000))
  const d = new Date(ts.replace(' ', 'T'))
  return Number.isNaN(d.getTime()) ? null : d
}

const two = (n) => String(n).padStart(2, '0')
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function ago(d) {
  const mins = Math.max(0, Math.round((istNow() - d) / 60000))
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  const h = Math.floor(mins / 60)
  return h < 24 ? `${h} h ago` : `${Math.floor(h / 24)} d ago`
}

/**
 * "Updated 11:42:05, 25 Sep" with a live "3 min ago" on hover. While the backend is fetching,
 * a small spinner says so; the data on screen stays until the new data lands.
 */
export default function UpdatedTag({ ts, refreshing = false, label = 'Updated' }) {
  const [, tick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 30000)
    return () => clearInterval(id)
  }, [])
  const d = toIst(ts)
  return (
    <span className={`updated-tag ${refreshing ? 'is-refreshing' : ''}`} title={d ? `${ago(d)}, IST` : undefined} role="status" aria-live="polite">
      {refreshing ? <RefreshCw size={13} className="spin" aria-hidden /> : <Clock size={13} aria-hidden />}
      {d ? (
        <>
          {label} <span className="num">{two(d.getHours())}:{two(d.getMinutes())}:{two(d.getSeconds())}, {d.getDate()} {MONTHS[d.getMonth()]}</span>
        </>
      ) : (
        'Waiting for first update'
      )}
      {refreshing && <span className="updated-note">Updating in the background</span>}
    </span>
  )
}
