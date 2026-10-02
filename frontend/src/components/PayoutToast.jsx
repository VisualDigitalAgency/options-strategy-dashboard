import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Coins, X } from 'lucide-react'
import { useAuth } from '../auth'
import { int, rupee } from '../format'
import { groupItems } from '../payouts'
import { rpc } from '../rpc'

// A reward that paid out since this browser last asked (issue #192). The server's clock is kept per
// user, so a new browser starts from "now" and never replays old rewards.
const key = (id) => `theta-payout-clock:${id}`
const SHOW_MS = 12000
const MAX_LINES = 3

const read = (id) => { try { return localStorage.getItem(key(id)) } catch { return null } }
const write = (id, v) => { try { localStorage.setItem(key(id), v) } catch { /* storage blocked */ } }

export default function PayoutToast() {
  const { user } = useAuth()
  const id = user?.id
  const [lines, setLines] = useState(null)
  const timer = useRef(null)

  const close = useCallback(() => { clearTimeout(timer.current); setLines(null) }, [])

  const ask = useCallback(() => {
    if (!id) return
    rpc('payout_news', { since: read(id) }).then((r) => {
      if (!r?.now) return
      write(id, r.now)
      const g = groupItems(r.items ?? [])
      if (!g.length) return
      setLines(g)
      clearTimeout(timer.current)
      timer.current = setTimeout(() => setLines(null), SHOW_MS)
    }).catch(() => { /* a missed toast is not worth an error: the Earn pages show everything */ })
  }, [id])

  useEffect(() => {
    ask()
    const back = () => { if (document.visibilityState === 'visible') ask() }
    document.addEventListener('visibilitychange', back)
    return () => { document.removeEventListener('visibilitychange', back); clearTimeout(timer.current) }
  }, [ask])

  if (!lines) return null
  const shown = lines.slice(0, MAX_LINES)
  return (
    <div className="payout-toast" role="status" aria-live="polite">
      <Coins size={18} aria-hidden />
      <div className="payout-body">
        <b>You earned</b>
        {shown.map((l) => (
          <p key={l.label}>
            {l.rupees > 0 && <span className="num">+{rupee(l.rupees)}</span>}
            {l.rupees > 0 && l.coins > 0 && ' · '}
            {l.coins > 0 && <span className="num">+{int(l.coins)} coin{l.coins === 1 ? '' : 's'}</span>}
            {' '}<span className="muted">{l.label}</span>
          </p>
        ))}
        {lines.length > MAX_LINES && <p className="muted">and {lines.length - MAX_LINES} more</p>}
        <Link to="/capital" onClick={close}>See what else you can earn</Link>
      </div>
      <button className="payout-x" onClick={close} aria-label="Dismiss"><X size={16} aria-hidden /></button>
    </div>
  )
}
