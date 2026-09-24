import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Info } from 'lucide-react'
import { rpc } from '../rpc'
import { useBudget } from '../settings'
import { rupee, rupee2, int, shortDate } from '../format'
import Modal from './Modal'
import SLModeSwitch, { slHelp } from './SLModeSwitch'

export default function OrderModal({ d, lots, onClose }) {
  const legs = d.legs.map((l) => ({ side: l.side, strike: l.strike, action: 'SELL', lots }))
  const [preview, setPreview] = useState(null)
  const [slMode, setSlMode] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(null)
  const { refresh } = useBudget()

  useEffect(() => {
    rpc('va_preview_order', { symbol: d.symbol, expiry: d.expiry, legs })
      .then((p) => {
        setPreview(p)
        setSlMode(p.sl_mode_default)
      })
      .catch((e) => setError(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d.symbol, d.expiry, lots])

  async function place() {
    setBusy(true)
    setError(null)
    try {
      setDone(await rpc('va_place_order', { symbol: d.symbol, expiry: d.expiry, legs, sl_mode: slMode }))
      refresh()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (done)
    return (
      <Modal title="Virtual order filled" onClose={onClose} width={480}>
        <div className="success">
          <CheckCircle2 size={28} aria-hidden />
          <p>
            Sold {done.filled.map((f) => `${f.strike} ${f.side} @ ${rupee2(f.price)}`).join(' and ')}.
            Premium received <b className="mono">{rupee(done.premium)}</b>.
          </p>
        </div>
        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Stay here</button>
          <Link className="btn primary" to="/portfolio">View in portfolio</Link>
        </div>
      </Modal>
    )

  return (
    <Modal title={`Order ticket · ${d.symbol}`} onClose={onClose}>
      <table className="ticket">
        <thead>
          <tr>
            <th>Leg</th>
            <th className="num">Fill (bid)</th>
            <th className="num">Qty</th>
            <th className="num">SL from {shortDate(d.sl.activates_on)}</th>
          </tr>
        </thead>
        <tbody>
          {d.legs.map((l, i) => {
            const f = preview?.fills[i]
            return (
              <tr key={l.side}>
                <td><b>SELL</b> {d.symbol} {shortDate(d.expiry)} {l.strike} {l.side}</td>
                <td className="num mono">{f ? rupee2(f.price) : <span className="skeleton sk-right" style={{ width: 56 }} />}</td>
                <td className="num mono">{f ? int(f.qty) : int(d.lot_size * lots)}</td>
                <td className="num mono">{f ? rupee2(f.price) : '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <dl className="ticket-sum">
        <div><dt>Premium received</dt><dd className="mono">{preview ? rupee(preview.premium) : '—'}</dd></div>
        <div><dt>Margin needed</dt><dd className="mono">{preview ? rupee(preview.margin_change) : '—'}</dd></div>
        <div>
          <dt>Virtual funds free</dt>
          <dd className={`mono ${preview && !preview.sufficient ? 'down' : ''}`}>{preview ? rupee(preview.available_margin) : '—'}</dd>
        </div>
      </dl>

      <div className="ticket-sl">
        <span className="field-label">Stop loss for these legs</span>
        <SLModeSwitch value={slMode} onChange={setSlMode} disabled={!preview} />
        <p className="helper">{slHelp(slMode)}</p>
      </div>

      {preview?.notes.map((n) => (
        <p key={n} className="notice"><Info size={16} aria-hidden /> {n}</p>
      ))}
      {preview && !preview.sufficient && (
        <p className="form-error" role="alert">Not enough virtual funds. Exit a position or reset the account with more capital.</p>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}
      <p className="notice muted-notice">
        <AlertTriangle size={16} aria-hidden /> Live broker not connected. Virtual orders use live NSE prices but no real money.
      </p>

      <div className="modal-actions">
        <button className="btn ghost" onClick={onClose}>Cancel</button>
        <button className="btn" disabled title="Enabled once a broker API is connected">Place live order</button>
        <button className="btn primary" onClick={place} disabled={!preview || !preview.sufficient || busy}>
          {busy ? 'Placing…' : 'Place virtual order'}
        </button>
      </div>
    </Modal>
  )
}
