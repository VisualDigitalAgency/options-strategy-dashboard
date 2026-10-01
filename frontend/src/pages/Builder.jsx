import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Plus, Trash2, Wrench } from 'lucide-react'
import { rpc } from '../rpc'
import { can, useAuth } from '../auth'
import { useBudget } from '../settings'
import { useTitle } from '../brand'
import { int, num, rupee, rupee2, shortDate } from '../format'
import { GroupPayoff } from '../components/Charts'
import { TEMPLATES, greeks, makeLeg, stats, warnings } from '../strategy'

// Strategy builder (issue #137): any Nifty 50 stock, any expiry, any mix of sold and bought legs.
// Open to every account. The screening rules show as warnings only. Bought legs on their own unlock
// at Level 6 (`hedges`); before that a buy must protect a sell, which the server enforces and the
// preview explains (`buy_rule`). Orders go to the virtual account.

const money = (v) => (v === Infinity ? 'Unlimited' : v === -Infinity ? 'Unlimited' : rupee(v))

function ChainTable({ chain, onAdd }) {
  const near = useMemo(() => {
    const i = chain.rows.findIndex((r) => r.strike >= chain.spot)
    const mid = i < 0 ? chain.rows.length : i
    return chain.rows.slice(Math.max(0, mid - 12), mid + 12)
  }, [chain])
  const cell = (r, side) => {
    const q = r[side]
    if (!q) return <td colSpan={3} className="muted">—</td>
    return (
      <>
        <td className="num">{num(q.bid)} / {num(q.ask)}</td>
        <td className="num">{q.delta == null ? '—' : num(q.delta, 2)}</td>
        <td className="chain-act">
          <button className="btn tiny" onClick={() => onAdd(side, r.strike, 'SELL')} aria-label={`Sell ${r.strike} ${side}`}>S</button>
          <button className="btn tiny" onClick={() => onAdd(side, r.strike, 'BUY')} aria-label={`Buy ${r.strike} ${side}`}>B</button>
        </td>
      </>
    )
  }
  return (
    <div className="table-scroll">
      <table className="chain-table">
        <thead><tr><th colSpan={3}>Calls (CE): bid / ask · delta</th><th>Strike</th><th colSpan={3}>Puts (PE): bid / ask · delta</th></tr></thead>
        <tbody>
          {near.map((r) => (
            <tr key={r.strike} className={r.strike >= chain.spot && near.find((x) => x.strike >= chain.spot)?.strike === r.strike ? 'atm' : ''}>
              {cell(r, 'CE')}
              <th scope="row" className="num">{num(r.strike, r.strike % 1 ? 2 : 0)}</th>
              {cell(r, 'PE')}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Builder() {
  useTitle('Strategy builder')
  const { user } = useAuth()
  const budget = useBudget()
  const [params, setParams] = useSearchParams()
  const [universe, setUniverse] = useState([])
  const symbol = params.get('symbol') || ''
  const expiry = params.get('expiry') || ''
  const [chain, setChain] = useState(null)
  const [legs, setLegs] = useState([])
  const [error, setError] = useState(null)
  const [preview, setPreview] = useState(null)
  const [previewError, setPreviewError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(null)
  const [confirm, setConfirm] = useState(false)
  const debounce = useRef(null)
  const hedges = can(user, 'hedges')

  useEffect(() => { rpc('get_config').then((c) => setUniverse(c.universe)).catch((e) => setError(e.message)) }, [])
  useEffect(() => {
    if (!symbol) return
    setChain(null); setError(null); setLegs([]); setDone(null)
    rpc('builder_chain', expiry ? { symbol, expiry } : { symbol }).then(setChain).catch((e) => setError(e.message))
  }, [symbol, expiry])

  const choose = (next) => setParams(Object.fromEntries(Object.entries(next).filter(([, v]) => v)))
  const add = (side, strike, action) => {
    const leg = chain && makeLeg(chain, side, strike, action)
    if (leg) { setLegs((ls) => [...ls, leg]); setDone(null) }
  }
  const template = (key) => {
    const made = TEMPLATES[key].legs(chain).filter(([, k]) => k != null).map(([s, k, a]) => makeLeg(chain, s, k, a)).filter(Boolean)
    setLegs(made); setDone(null)
  }
  const update = (i, patch) => setLegs((ls) => ls.map((l, j) => {
    if (j !== i) return l
    const next = { ...l, ...patch }
    return makeLeg(chain, next.side, next.strike, next.action, next.lots) ?? l
  }))

  // Live preview: fills, margin, and why a buy isn't allowed yet. Debounced so editing stays smooth.
  const orderLegs = legs.map((l) => ({ side: l.side, strike: l.strike, action: l.action, lots: l.lots }))
  const key = JSON.stringify(orderLegs)
  useEffect(() => {
    clearTimeout(debounce.current)
    setPreview(null); setPreviewError(null); setConfirm(false)
    if (!chain || !legs.length) return undefined
    debounce.current = setTimeout(() => {
      rpc('va_preview_order', { symbol: chain.symbol, expiry: chain.expiry, legs: orderLegs })
        .then(setPreview).catch((e) => setPreviewError(e.message))
    }, 400)
    return () => clearTimeout(debounce.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, chain])

  const lot = chain?.lot_size || 0
  const s = useMemo(() => (chain ? stats(legs, chain.spot, lot) : null), [legs, chain, lot])
  const g = useMemo(() => (chain ? greeks(legs, chain.spot, chain.dte, lot) : null), [legs, chain, lot])
  const warn = chain ? warnings(chain, legs) : []
  const payoffLegs = legs.map((l) => ({ side: l.side, strike: l.strike, qty: (l.action === 'BUY' ? 1 : -1) * l.lots * lot, avg_price: l.premium }))
  const needsConfirm = (preview?.illiquid?.length || preview?.waiting?.length) > 0

  async function place() {
    if (needsConfirm && !confirm) { setConfirm(true); return }
    setBusy(true); setPreviewError(null)
    try {
      setDone(await rpc('va_place_order', {
        symbol: chain.symbol, expiry: chain.expiry, legs: orderLegs,
        confirm_waiting: confirm, confirm_illiquid: confirm,
      }))
      setLegs([]); budget?.refresh?.()
    } catch (e) { setPreviewError(e.message) } finally { setBusy(false); setConfirm(false) }
  }

  return (
    <div className="builder-page">
      <h1 className="page-title"><Wrench size={20} aria-hidden /> Strategy builder</h1>
      <p className="muted">Build your own strategy on any Nifty 50 stock. Orders go to your virtual account.
        {!hedges && ' Bought legs must protect a sold leg until Level 6.'}</p>

      <div className="card builder-pick">
        <div className="field">
          <label htmlFor="b-symbol">Stock</label>
          <select id="b-symbol" value={symbol} onChange={(e) => choose({ symbol: e.target.value })}>
            <option value="">Choose a stock…</option>
            {universe.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </div>
        {chain && (
          <div className="field">
            <label htmlFor="b-expiry">Expiry</label>
            <select id="b-expiry" value={chain.expiry} onChange={(e) => choose({ symbol, expiry: e.target.value })}>
              {chain.expiries.map((x) => <option key={x} value={x}>{shortDate(x)}</option>)}
            </select>
          </div>
        )}
        {chain && <p className="builder-facts num">Spot {num(chain.spot)} · {chain.dte} days · lot {int(lot)}</p>}
      </div>

      {error && <div className="alert" role="alert"><AlertTriangle size={18} aria-hidden /> {error}</div>}
      {symbol && !chain && !error && <p className="muted">Loading the option chain…</p>}

      {chain && (
        <>
          <div className="builder-templates" role="group" aria-label="Templates">
            {Object.entries(TEMPLATES).map(([k, t]) => <button key={k} className="btn" onClick={() => template(k)}>{t.label}</button>)}
            <button className="btn" onClick={() => setLegs([])}>Blank</button>
          </div>

          <section className="card" aria-label="Legs">
            <h2>Legs</h2>
            {!legs.length && <p className="muted">Pick a template, or press S (sell) or B (buy) on a strike below.</p>}
            {legs.map((l, i) => (
              <div key={i} className="builder-leg">
                <select aria-label="Buy or sell" value={l.action} onChange={(e) => update(i, { action: e.target.value })}>
                  <option value="SELL">Sell</option><option value="BUY">Buy</option>
                </select>
                <select aria-label="Strike" value={l.strike} onChange={(e) => update(i, { strike: Number(e.target.value) })}>
                  {chain.rows.filter((r) => r[l.side]).map((r) => <option key={r.strike} value={r.strike}>{r.strike}</option>)}
                </select>
                <select aria-label="Call or put" value={l.side} onChange={(e) => update(i, { side: e.target.value })}>
                  <option value="CE">CE</option><option value="PE">PE</option>
                </select>
                <input aria-label="Lots" type="number" min="1" max="50" value={l.lots}
                  onChange={(e) => update(i, { lots: Math.max(1, Math.min(50, Number(e.target.value) || 1)) })} />
                <span className="num">{rupee2(l.premium)}</span>
                <span className="num muted">Δ {l.delta == null ? '—' : num(l.delta, 2)}</span>
                <button className="icon-btn" onClick={() => setLegs((ls) => ls.filter((_, j) => j !== i))} aria-label="Remove leg"><Trash2 size={16} /></button>
              </div>
            ))}
          </section>

          {warn.length > 0 && (
            <ul className="builder-warnings" aria-label="Warnings">
              {warn.map((w) => <li key={w}><AlertTriangle size={14} aria-hidden /> {w}</li>)}
            </ul>
          )}

          {legs.length > 0 && s && (
            <section className="card" aria-label="Analysis">
              <h2>At expiry</h2>
              <dl className="builder-stats">
                <div><dt>{s.net >= 0 ? 'Credit received' : 'Debit paid'}</dt><dd className="num">{rupee(Math.abs(s.net))}</dd></div>
                <div><dt>Max profit</dt><dd className="num pos">{money(s.maxProfit)}</dd></div>
                <div><dt>Max loss</dt><dd className="num neg">{money(s.maxLoss)}</dd></div>
                <div><dt>Breakevens</dt><dd className="num">{s.breakevens.map((b) => num(b, 0)).join(' · ') || '—'}</dd></div>
                <div><dt>Margin needed</dt><dd className="num">{preview ? rupee(preview.margin_change) : '…'}</dd></div>
                <div><dt>Net delta · theta/day</dt><dd className="num">{num(g.delta, 1)} · {rupee(g.theta)}</dd></div>
              </dl>
              <GroupPayoff legs={payoffLegs} spot={chain.spot} />
            </section>
          )}

          {legs.length > 0 && (
            <section className="card builder-place" aria-label="Place">
              {preview?.buy_rule && <div className="alert" role="alert"><AlertTriangle size={18} aria-hidden /> {preview.buy_rule}</div>}
              {preview && !preview.sufficient && (
                <div className="alert" role="alert">Not enough free margin: needs {rupee(preview.margin_change)}, available {rupee(preview.available_margin)}</div>
              )}
              {confirm && preview?.illiquid?.length > 0 && <p className="neg small">Thin market on {preview.illiquid.map((x) => `${x.strike} ${x.side}`).join(', ')}. Press again to place anyway.</p>}
              {confirm && preview?.waiting?.length > 0 && <p className="neg small">An earlier order on this stock and expiry is still waiting. Press again to place another.</p>}
              {previewError && <p className="neg small" role="alert">{previewError}</p>}
              {preview?.notes?.map((n) => <p key={n} className="muted small">{n}</p>)}
              <button className="btn primary" onClick={place} disabled={busy || !preview || !!preview.buy_rule || !preview.sufficient}>
                <Plus size={15} aria-hidden /> {busy ? 'Placing…' : confirm ? 'Place anyway' : 'Place on virtual account'}
              </button>
            </section>
          )}

          {done && (
            <p className="pos" role="status"><CheckCircle2 size={16} aria-hidden /> Order placed: {done.filled.length} filled{done.open.length ? `, ${done.open.length} waiting` : ''}. <Link to="/portfolio">See it in Portfolio</Link></p>
          )}

          <section className="card" aria-label="Option chain">
            <h2>Option chain</h2>
            <ChainTable chain={chain} onAdd={add} />
          </section>
        </>
      )}
    </div>
  )
}
