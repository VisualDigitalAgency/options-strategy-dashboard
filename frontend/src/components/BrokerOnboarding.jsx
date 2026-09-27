import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import Modal from './Modal'
import BrokerCard from './BrokerCard'
import { BROKERS } from '../brokers'
import { rpc } from '../rpc'

// Login sets this right after a successful sign-in (not on page refresh), so the popup
// shows once per login rather than on every route change or reload.
export const SHOW_KEY = 'td_show_broker_popup'

export default function BrokerOnboarding() {
  const nav = useNavigate()
  const [open, setOpen] = useState(false)
  const [summary, setSummary] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    try {
      if (sessionStorage.getItem(SHOW_KEY)) {
        sessionStorage.removeItem(SHOW_KEY)
        setOpen(true)
      }
    } catch { /* storage blocked: just skip the popup */ }
  }, [])

  useEffect(() => {
    if (!open) return
    rpc('broker_account_summary').then(setSummary).catch((e) => setError(e.message))
  }, [open])

  const connect = useCallback(async () => {
    setBusy(true)
    setError(null)
    try {
      const { url, state } = await rpc('broker_connect_url')
      try { sessionStorage.setItem('broker_oauth_state', state) } catch { /* ignore */ }
      window.location.href = url
    } catch (e) {
      setError(e.message)
      setBusy(false)
    }
  }, [])

  const connectable = summary?.connectable ?? []

  if (!open) return null
  return (
    <Modal title="Connect your broker" onClose={() => setOpen(false)} width={640}>
      <p className="confirm-body">
        {connectable.length
          ? 'Zerodha is connectable now, real money and all — every order still needs your explicit confirmation. Other brokers are previews for now.'
          : "Theta Desk is virtual-only for now. Once broker execution is wired up, you'll connect one of these accounts to place real orders — no setup needed today."}
      </p>
      {error && <div className="alert" role="alert"><AlertTriangle size={18} aria-hidden /> {error}</div>}
      <div className="broker-grid broker-grid-popup">
        {BROKERS.map((b) => (
          <BrokerCard
            key={b.id}
            b={b}
            connectable={connectable.includes(b.id)}
            connection={summary}
            busy={busy}
            onConnect={connect}
            onDisconnect={() => { setOpen(false); nav('/broker') }}
          />
        ))}
      </div>
      <div className="modal-actions">
        <button className="btn ghost" onClick={() => setOpen(false)}>Maybe later</button>
        <Link className="btn primary" to="/broker" onClick={() => setOpen(false)}>Explore brokers</Link>
      </div>
    </Modal>
  )
}
