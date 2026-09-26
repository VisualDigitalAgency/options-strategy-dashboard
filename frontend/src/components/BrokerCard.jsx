import { CheckCircle2, Loader2 } from 'lucide-react'

const STATUS_LABEL = { active: 'Connected', expired: 'Reconnect needed', disconnected: 'Not connected' }

/** b: {id, name, logo}. connection: this broker's live status (only passed for the connectable
 *  one in phase 1); every other broker still shows the static "Coming soon" preview. */
export default function BrokerCard({ b, connectable, connection, busy, onConnect, onDisconnect }) {
  const status = connectable ? connection?.status ?? 'disconnected' : null
  return (
    <div className="broker-card">
      {status ? (
        <span className={`chip broker-status-${status}`}>{STATUS_LABEL[status]}</span>
      ) : (
        <span className="chip broker-soon">Coming soon</span>
      )}
      <div className="broker-logo"><img src={b.logo} alt="" /></div>
      <b className="broker-name">{b.name}</b>
      {!connectable && <button className="btn small ghost" disabled>Connect</button>}
      {connectable && status !== 'active' && (
        <button className="btn small primary" onClick={onConnect} disabled={busy}>
          {busy ? <Loader2 size={14} className="spin" aria-hidden /> : null}
          {status === 'expired' ? 'Reconnect' : 'Connect'}
        </button>
      )}
      {connectable && status === 'active' && (
        <button className="btn small ghost danger-text" onClick={onDisconnect} disabled={busy}>
          Disconnect
        </button>
      )}
      {connectable && status === 'active' && (
        <span className="broker-connected-note"><CheckCircle2 size={13} aria-hidden /> Real account linked</span>
      )}
    </div>
  )
}
