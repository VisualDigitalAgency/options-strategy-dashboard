import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Info } from 'lucide-react'
import { rpc } from '../rpc'
import { useBudget } from '../settings'
import { rupee, rupee2, int, shortDate } from '../format'
import Modal from './Modal'
import SLModeSwitch, { slHelp } from './SLModeSwitch'

const TICK = 0.05
const toTick = (v) => Math.round(v / TICK) * TICK

export default function OrderModal({ d, lots, onClose }) {
  // Limit prices typed on the ticket, by leg. Empty means the default: the bid for a sell.
  const [limits, setLimits] = useState({})
  const legs = d.legs.map((l) => ({
    side: l.side, strike: l.strike, action: 'SELL', lots,
    ...(Number(limits[l.side]) > 0 ? { price: toTick(Number(limits[l.side])) } : {}),
  }))
  const debounce = useRef(null)
  const [preview, setPreview] = useState(null)
  const [slMode, setSlMode] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(null)
  const { refresh } = useBudget()

  useEffect(() => {
    clearTimeout(debounce.current)
    debounce.current = setTimeout(() => {
      rpc('va_preview_order', { symbol: d.symbol, expiry: d.expiry, legs })
        .then((p) => {
          setPreview(p)
          setError(null)
          setSlMode((m) => m ?? p.sl_mode_default)
        })
        .catch((e) => setError(e.message))
    }, 350)
    return () => clearTimeout(debounce.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d.symbol, d.expiry, lots, JSON.stringify(limits)])

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
      <Modal title={done.open.length ? 'Virtual limit order placed' : 'Virtual order filled'} onClose={onClose} width={480}>
        <div className="success">
          <CheckCircle2 size={28} aria-hidden />
          <p>
            {done.filled.length > 0 && <>Sold {done.filled.map((f) => `${f.strike} ${f.side} @ ${rupee2(f.price)}`).join(' and ')}. </>}
            {done.open.length > 0 && (
              <>Waiting to sell {done.open.map((f) => `${f.strike} ${f.side} at ${rupee2(f.limit)}`).join(' and ')}. It fills when the bid
                reaches your limit, or expires at the close. Improve or cancel it on the Portfolio page. </>
            )}
            {done.open.length === 0 && <>Premium received <b className="mono">{rupee(done.premium)}</b>.</>}
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
            <th className="num">Bid / ask</th>
            <th className="num">Limit</th>
            <th className="num">Qty</th>
            <th className="num">SL from {shortDate(d.sl.activates_on)}</th>
          </tr>
        </thead>
        <tbody>
          {d.legs.map((l, i) => {
            const f = preview?.fills[i]
            return (
              <tr key={l.side}>
                <td>
                  <b>SELL</b> {d.symbol} {shortDate(d.expiry)} {l.strike} {l.side}
                  {f && <span className={`fill-tag ${f.fills_now ? 'now' : 'waits'}`}>{f.fills_now ? `Fills now at ${rupee2(f.price)}` : 'Waits for the bid'}</span>}
                </td>
                <td className="num mono">{f ? `${rupee2(f.bid)} / ${rupee2(f.ask)}` : <span className="skeleton sk-right" style={{ width: 80 }} />}</td>
                <td className="num">
                  <input className="limit-input mono" type="number" inputMode="decimal" step={TICK} min={TICK}
                    aria-label={`Limit price for ${l.strike} ${l.side}`}
                    value={limits[l.side] ?? (f ? f.limit.toFixed(2) : '')}
                    onChange={(e) => setLimits((m) => ({ ...m, [l.side]: e.target.value }))} />
                </td>
                <td className="num mono">{f ? int(f.qty) : int(d.lot_size * lots)}</td>
                <td className="num mono">{f ? rupee2(f.price) : '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <dl className="ticket-sum">
        <div><dt>Premium at your limits</dt><dd className="mono">{preview ? rupee(preview.premium) : '—'}</dd></div>
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
          {busy ? 'Placing…' : 'Place virtual limit order'}
        </button>
      </div>
    </Modal>
  )
}
