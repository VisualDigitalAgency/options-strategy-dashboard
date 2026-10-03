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

  const exit = preview.exit // closing a position group: BUY LIMIT at the ask per short, SELL LIMIT at the bid per long
  return (
    <Modal title={exit ? 'Exit with REAL orders' : 'Place a REAL order'} onClose={onClose} width={520}>
      <div className="real-order-warning" role="alert">
        <AlertTriangle size={20} aria-hidden />
        <p>{exit
          ? 'This sends real orders to your connected Zerodha account with real money, to close every leg of this position. They are limit orders and may not fill today. Once the broker accepts them they are not reversible by cancelling here.'
          : 'This sends a real SELL order to your connected Zerodha account with real money. It is not reversible by cancelling here once the broker accepts it.'}</p>
      </div>
      <table className="legs">
        <thead><tr><th>Instrument</th><th className="num">Qty</th><th className="num">Limit</th></tr></thead>
        <tbody>
          {preview.legs.map((l, i) => (
            <tr key={i}>
              <td>{exit && <b>{l.action} </b>}{symbol} {expiry} <b className="mono">{l.strike}</b> {l.side}</td>
              <td className="num mono">{l.qty}</td>
              <td className="num mono">
                {rupee2(l.limit_price)}
                {!exit && l.market_price != null && l.limit_price !== l.market_price && (
                  <div className="muted small">your limit · bid {rupee2(l.market_price)}</div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {!exit && preview.legs.some((l) => l.market_price != null && l.limit_price > l.market_price) && (
        <p className="muted small">A limit above the bid waits in your Zerodha order book until a buyer
          pays it, and may not fill today.</p>
      )}
      {!exit && <p className="confirm-body">Estimated margin required: <b>{rupee(preview.margin.total)}</b></p>}
      {preview.legs.length > 1 && (
        <p className="muted small">Legs are placed one at a time; your broker has no all-or-nothing
          multi-leg order. If a later leg is rejected, earlier ones already placed stay live in
          your Zerodha account and must be managed there.</p>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
      <div className="modal-actions">
        <button className="btn ghost" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn danger" onClick={confirm} disabled={busy}>
          {busy ? 'Sending to broker…' : exit ? 'Yes, place these real exit orders' : 'Yes, place this real order'}
        </button>
      </div>
    </Modal>
  )
}
