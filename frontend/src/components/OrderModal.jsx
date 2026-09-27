import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Info, RotateCw } from 'lucide-react'
import { rpc } from '../rpc'
import { useBudget } from '../settings'
import { rupee, rupee2, int, shortDate, dateTime } from '../format'
import Modal from './Modal'
import SLModeSwitch, { slHelp } from './SLModeSwitch'
import RealOrderConfirmDialog from './RealOrderConfirmDialog'

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
  // An earlier order on this stock and expiry is still waiting: ask before placing another.
  const [confirming, setConfirming] = useState(false)
  const [reload, setReload] = useState(0)
  const { refresh } = useBudget()

  // Real broker (phase 1: Zerodha, admin-only). null until checked; a non-admin or anyone
  // without a connection just never sees this become active — the button stays disabled.
  const [brokerConnected, setBrokerConnected] = useState(false)
  const [realSummary, setRealSummary] = useState(null)
  const [realPreview, setRealPreview] = useState(null)
  const [realError, setRealError] = useState(null)
  const [realBusy, setRealBusy] = useState(false)
  useEffect(() => {
    (async () => {
      try {
        const s = await rpc('broker_account_summary')
        setBrokerConnected(s.status === 'active')
        if (s.status === 'active') setRealSummary(s)
      } catch { /* treated the same as "no broker connected" */ }
    })()
  }, [])

  async function previewReal() {
    setRealError(null)
    setRealBusy(true)
    try {
      setRealPreview(await rpc('broker_preview_order', { symbol: d.symbol, expiry: d.expiry, legs }))
    } catch (e) {
      setRealError(e.message)
    } finally {
      setRealBusy(false)
    }
  }

  async function placeReal(confirmToken) {
    await rpc('broker_place_order', { confirm_token: confirmToken })
    setRealPreview(null)
    refresh()
  }

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
  }, [d.symbol, d.expiry, lots, JSON.stringify(limits), reload])

  const waiting = preview?.waiting ?? []

  // Reload one leg's limit with the current best price: a fresh preview priced at the default
  // (the bid for a sell), leaving the other legs as typed. A failure keeps the typed value.
  const [pricing, setPricing] = useState({})
  const [priceError, setPriceError] = useState({})
  async function refreshPrice(side) {
    setPricing((m) => ({ ...m, [side]: true }))
    setPriceError((m) => ({ ...m, [side]: null }))
    try {
      const p = await rpc('va_preview_order', {
        symbol: d.symbol, expiry: d.expiry,
        legs: legs.map((l) => (l.side === side ? { side: l.side, strike: l.strike, action: l.action, lots: l.lots } : l)),
      })
      const f = p.fills.find((x) => x.side === side)
      if (!(f?.limit > 0)) throw new Error('No live price for this strike right now')
      setLimits((m) => ({ ...m, [side]: toTick(f.limit).toFixed(2) }))
    } catch (e) {
      setPriceError((m) => ({ ...m, [side]: `Couldn't refresh the price: ${e.message}` }))
    } finally {
      setPricing((m) => ({ ...m, [side]: false }))
    }
  }

  async function place(confirmWaiting = false) {
    if (waiting.length && !confirmWaiting) {
      setConfirming(true)
      return
    }
    setBusy(true)
    setError(null)
    try {
      setDone(await rpc('va_place_order', {
        symbol: d.symbol, expiry: d.expiry, legs, sl_mode: slMode, confirm_waiting: confirmWaiting,
      }))
      refresh()
    } catch (e) {
      setError(e.message)
      setConfirming(false)
      setReload((n) => n + 1) // another tab may have placed an order since the preview; show it
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
                  <span className="limit-cell">
                    <input className="limit-input mono" type="number" inputMode="decimal" step={TICK} min={TICK}
                      aria-label={`Limit price for ${l.strike} ${l.side}`}
                      value={limits[l.side] ?? (f ? f.limit.toFixed(2) : '')}
                      onChange={(e) => setLimits((m) => ({ ...m, [l.side]: e.target.value }))} />
                    <button type="button" className={`icon-btn ${priceError[l.side] ? 'failed' : ''}`}
                      aria-label="Refresh price" onClick={() => refreshPrice(l.side)}
                      disabled={!(preview?.market_open && f?.bid > 0) || pricing[l.side]}
                      title={priceError[l.side] || (preview?.market_open ? 'Fetch the current best price' : 'Market is closed')}>
                      <RotateCw size={14} aria-hidden className={pricing[l.side] ? 'spin' : ''} />
                    </button>
                  </span>
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
      {realError && <p className="form-error" role="alert">{realError}</p>}
      {confirming && (
        <div className="alert warn-alert confirm-waiting" role="alert">
          <AlertTriangle size={18} aria-hidden />
          <div>
            <b>Your previous order is not yet executed.</b>
            <ul>
              {waiting.map((w) => (
                <li key={w.id} className="mono">
                  {w.action} {w.strike} {w.side} × {int(w.qty)} at {rupee2(w.limit_price)}
                  <span className="muted"> · placed {dateTime(w.created_at)}{w.reason === 'auto' ? ' by auto-trade' : ''}</span>
                </li>
              ))}
            </ul>
            <p>Placing this order adds to it, so both can fill. Do you want to proceed?</p>
          </div>
        </div>
      )}
      {!brokerConnected && (
        <p className="notice muted-notice">
          <AlertTriangle size={16} aria-hidden /> Live broker not connected. Virtual orders use live NSE prices but no real money.
        </p>
      )}

      {confirming ? (
        <div className="modal-actions">
          <Link className="btn ghost" to="/portfolio">Review open orders</Link>
          <button className="btn ghost" onClick={() => setConfirming(false)} disabled={busy}>Don't place</button>
          <button className="btn primary" onClick={() => place(true)} disabled={!preview || !preview.sufficient || busy}>
            {busy ? 'Placing…' : 'Yes, place another'}
          </button>
        </div>
      ) : (
        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Cancel</button>
          <button className="btn" onClick={previewReal} disabled={!brokerConnected || realBusy}
            title={brokerConnected ? 'Places a real order at your connected broker' : 'Connect a broker on the Broker page first'}>
            {realBusy ? 'Checking…' : 'Place live order'}
          </button>
          <button className="btn primary" onClick={() => place()} disabled={!preview || !preview.sufficient || busy}>
            {busy ? 'Placing…' : 'Place virtual limit order'}
          </button>
        </div>
      )}
      {brokerConnected && realSummary && (
        <p className="muted small">
          Real available margin: <b className="mono">{rupee(realSummary.available_margin_total)}</b>
          {' '}(your broker's own figure: {rupee(realSummary.available_cash)} cash + {rupee(realSummary.total_collateral)} collateral,
          less margin already in use)
        </p>
      )}

      {realPreview && (
        <RealOrderConfirmDialog symbol={d.symbol} expiry={shortDate(d.expiry)} preview={realPreview}
          onConfirm={placeReal} onClose={() => setRealPreview(null)} />
      )}
    </Modal>
  )
}
