import { useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import Modal from './Modal'
import { rupee, rupee2 } from '../format'

/** Distinct, deliberately alarming styling from the virtual ConfirmDialog: this one sends a real
 *  order to a real broker with real money. No "don't ask again" — every order gets this. */
export default function RealOrderConfirmDialog({ symbol, expiry, preview, onConfirm, onClose }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function confirm() {
    setBusy(true)
    setError(null)
    try {
      await onConfirm(preview.confirm_token)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal title="Place a REAL order" onClose={onClose} width={520}>
      <div className="real-order-warning" role="alert">
        <AlertTriangle size={20} aria-hidden />
        <p>This sends a real SELL order to your connected Zerodha account with real money. It is
          not reversible by cancelling here once the broker accepts it.</p>
      </div>
      <table className="legs">
        <thead><tr><th>Instrument</th><th className="num">Qty</th><th className="num">Limit</th></tr></thead>
        <tbody>
          {preview.legs.map((l, i) => (
            <tr key={i}>
              <td>{symbol} {expiry} <b className="mono">{l.strike}</b> {l.side}</td>
              <td className="num mono">{l.qty}</td>
              <td className="num mono">{rupee2(l.limit_price)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="confirm-body">Estimated margin required: <b>{rupee(preview.margin.total)}</b></p>
      {preview.legs.length > 1 && (
        <p className="muted small">Legs are placed one at a time; your broker has no all-or-nothing
          multi-leg order. If a later leg is rejected, earlier ones already placed stay live in
          your Zerodha account and must be managed there.</p>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="modal-actions">
        <button className="btn ghost" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn danger" onClick={confirm} disabled={busy}>
          {busy ? 'Sending to broker…' : 'Yes, place this real order'}
        </button>
      </div>
    </Modal>
  )
}
