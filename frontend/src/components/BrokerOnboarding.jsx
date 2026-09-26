import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import Modal from './Modal'
import BrokerCard from './BrokerCard'
import { BROKERS } from '../brokers'

// Login sets this right after a successful sign-in (not on page refresh), so the popup
// shows once per login rather than on every route change or reload.
export const SHOW_KEY = 'td_show_broker_popup'

export default function BrokerOnboarding() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    try {
      if (sessionStorage.getItem(SHOW_KEY)) {
        sessionStorage.removeItem(SHOW_KEY)
        setOpen(true)
      }
    } catch { /* storage blocked: just skip the popup */ }
  }, [])

  if (!open) return null
  return (
    <Modal title="Connect your broker" onClose={() => setOpen(false)} width={640}>
      <p className="confirm-body">
        Theta Desk is virtual-only for now. Once broker execution is wired up, you'll connect one of
        these accounts to place real orders — no setup needed today.
      </p>
      <div className="broker-grid broker-grid-popup">
        {BROKERS.map((b) => <BrokerCard key={b.id} b={b} />)}
      </div>
      <div className="modal-actions">
        <button className="btn ghost" onClick={() => setOpen(false)}>Maybe later</button>
        <Link className="btn primary" to="/broker" onClick={() => setOpen(false)}>Explore brokers</Link>
      </div>
    </Modal>
  )
}
