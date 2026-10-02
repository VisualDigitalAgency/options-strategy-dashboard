import { useState } from 'react'
import Modal from './Modal'
import { int, rupee2 } from '../format'

// Stop-loss order on one open leg (#183). SL-M: once the price reaches the trigger, exit at the
// market. SL: once triggered, a limit order at your price (may wait if the price runs past it).
// A sold leg's stop is a BUY above the price; a bought leg's a SELL below it.
export default function StopOrderDialog({ leg, symbol, busy, error, onSubmit, onClose }) {
  const sold = leg.qty < 0
  const now = leg.mark ?? leg.ltp
  const [type, setType] = useState('slm')
  const [trigger, setTrigger] = useState('')
  const [limit, setLimit] = useState('')
  const t = Number(trigger)
  const l = Number(limit)
  const sideOk = t > 0 && (now == null || (sold ? t > now : t < now))
  const limitOk = type === 'slm' || (l > 0 && (sold ? l >= t : l <= t))
  const submit = (e) => {
    e.preventDefault()
    onSubmit({ position_id: leg.id, trigger: t, order_type: type, ...(type === 'sl' ? { limit: l } : {}) })
  }
  return (
    <Modal title={`Stop-loss: ${symbol} ${leg.strike} ${leg.side}`} onClose={onClose} width={440}>
      <form className="stop-form" onSubmit={submit}>
        <p className="muted small">
          {sold ? 'Buys back' : 'Sells'} all {int(Math.abs(leg.qty))} qty when the price {sold ? 'rises to' : 'falls to'} your
          trigger{now != null ? ` (now ${rupee2(now)})` : ''}. While it's set, the day-15 automatic stop leaves this leg to it.
        </p>
        <div className="segmented small" role="radiogroup" aria-label="Stop type">
          {[['slm', 'SL-M (market)'], ['sl', 'SL (limit)']].map(([k, label]) => (
            <button key={k} type="button" role="radio" aria-checked={type === k} className={type === k ? 'active' : ''}
              onClick={() => setType(k)}>{label}</button>
          ))}
        </div>
        <label className="field">Trigger price
          <input type="number" inputMode="decimal" step="0.05" min="0.05" value={trigger} onChange={(e) => setTrigger(e.target.value)} required />
        </label>
        {type === 'sl' && (
          <label className="field">Limit price
            <input type="number" inputMode="decimal" step="0.05" min="0.05" value={limit} onChange={(e) => setLimit(e.target.value)} required />
            <span className="muted small">{sold ? 'At or above' : 'At or below'} the trigger.</span>
          </label>
        )}
        {trigger && !sideOk && <p className="neg small" role="alert">The trigger must be {sold ? 'above' : 'below'} the current price.</p>}
        {type === 'sl' && limit && sideOk && !limitOk && <p className="neg small" role="alert">The limit must be {sold ? 'at or above' : 'at or below'} the trigger.</p>}
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy || !sideOk || !limitOk}>{busy ? 'Placing…' : 'Place stop-loss'}</button>
        </div>
      </form>
    </Modal>
  )
}
