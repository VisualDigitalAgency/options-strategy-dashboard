import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, Plug } from 'lucide-react'
import { rpc } from '../rpc'
import { useAuth } from '../auth'
import { BROKERS } from '../brokers'
import BrokerCard from '../components/BrokerCard'
import { ConfirmDialog } from '../components/Modal'

export default function Broker() {
  const { user } = useAuth() ?? {}
  const isAdmin = user?.role === 'admin'
  const [connection, setConnection] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [confirmDisconnect, setConfirmDisconnect] = useState(false)

  const load = useCallback(async () => {
    if (!isAdmin) return // phase 1: connecting is admin-only; other accounts never have a real connection
    try {
      setConnection(await rpc('broker_status'))
    } catch (e) {
      setError(e.message)
    }
  }, [isAdmin])

  useEffect(() => { document.title = 'Broker · Theta Desk'; load() }, [load])

  async function connect() {
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
  }

  async function disconnect() {
    setBusy(true)
    setError(null)
    try {
      await rpc('broker_disconnect')
      setConfirmDisconnect(false)
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="detail">
      <header className="page-head">
        <div>
          <h1 className="display">Connect a broker</h1>
          <p className="lede">
            {isAdmin
              ? 'Zerodha is connectable now, real money and all — every order still needs your explicit confirmation. Other brokers are previews for now.'
              : "Broker execution is being rolled out to admin accounts first. This is a preview of the brokers Theta Desk will support for placing real orders."}
          </p>
        </div>
      </header>

      {error && <div className="alert" role="alert"><AlertTriangle size={18} aria-hidden /> {error}</div>}

      {isAdmin && connection?.status === 'active' && (
        <p className="broker-linked-banner">
          <Plug size={14} aria-hidden /> Connected to Zerodha. <Link to="/broker/account">View real account →</Link>
        </p>
      )}

      <div className="card broker-grid">
        {BROKERS.map((b) => (
          <BrokerCard
            key={b.id}
            b={b}
            connectable={isAdmin && b.id === 'zerodha'}
            connection={connection}
            busy={busy}
            onConnect={connect}
            onDisconnect={() => setConfirmDisconnect(true)}
          />
        ))}
      </div>
      <p className="muted small broker-note">
        <Plug size={14} aria-hidden /> {isAdmin
          ? 'Every real order needs a fresh, explicit confirmation before it reaches Zerodha — nothing here is automated.'
          : 'Nothing you do in the screener, portfolio or virtual account sends orders to a real broker.'}
      </p>

      {confirmDisconnect && (
        <ConfirmDialog
          title="Disconnect Zerodha?"
          body="You'll stop seeing your real Zerodha positions and margin here, and won't be able to place real orders until you reconnect."
          confirmLabel="Disconnect"
          danger
          busy={busy}
          error={error}
          onConfirm={disconnect}
          onClose={() => setConfirmDisconnect(false)}
        />
      )}
    </div>
  )
}
