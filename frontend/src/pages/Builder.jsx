import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AlertTriangle, CheckCircle2, Eraser, Minus, Plus, Trash2, Wrench } from 'lucide-react'
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
const strikeText = (k) => num(k, k % 1 ? 2 : 0)

// A tiny payoff-at-expiry sketch per template, so the shapes read at a glance.
const SHAPES = {
  short_strangle: 'M1 15 L9 4 L23 4 L31 15',
  short_straddle: 'M1 15 L16 3 L31 15',
  iron_condor: 'M1 13 L7 13 L12 4 L20 4 L25 13 L31 13',
  bull_put_spread: 'M1 13 L11 13 L21 4 L31 4',
  bear_call_spread: 'M1 4 L11 4 L21 13 L31 13',
}
const Shape = ({ d }) => (
  <svg viewBox="0 0 32 18" width="32" height="18" aria-hidden><path d="M1 9 H31" className="shape-axis" /><path d={d} className="shape-line" /></svg>
)

function Seg({ label, value, options, onChange, tone }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} type="button" aria-pressed={value === v} className={tone ? `tone-${v.toLowerCase()}` : ''}
          onClick={() => value !== v && onChange(v)}>{text}</button>
      ))}
    </div>
  )
}

function ChainTable({ chain, onAdd }) {
  const [view, setView] = useState('CE') // phones show one side at a time
  const atm = useMemo(() => chain.rows.find((r) => r.strike >= chain.spot)?.strike, [chain])
  const near = useMemo(() => {
    const i = chain.rows.findIndex((r) => r.strike >= chain.spot)
    const mid = i < 0 ? chain.rows.length : i
    return chain.rows.slice(Math.max(0, mid - 12), mid + 12)
  }, [chain])
  const acts = (r, side) => (
    <td className={`chain-act ${side.toLowerCase()}`}>
      <button className="act sell" onClick={() => onAdd(side, r.strike, 'SELL')} aria-label={`Sell ${r.strike} ${side}`}>Sell</button>
      <button className="act buy" onClick={() => onAdd(side, r.strike, 'BUY')} aria-label={`Buy ${r.strike} ${side}`}>Buy</button>
    </td>
  )
  const cells = (r, side) => {
    const q = r[side]
    const s = side.toLowerCase()
    const itm = side === 'CE' ? r.strike < chain.spot : r.strike > chain.spot
    if (!q) return <td colSpan={3} className={`muted ${s}`}>—</td>
    const parts = [
      <td key="p" className={`num chain-px ${s}${itm ? ' itm' : ''}`}><span>{num(q.bid)}</span><small>{num(q.ask)}</small></td>,
      <td key="d" className={`num chain-d ${s}${itm ? ' itm' : ''}`}>{q.delta == null ? '—' : num(q.delta, 2)}</td>,
      <Fragment key="a">{acts(r, side)}</Fragment>,
    ]
    return side === 'CE' ? parts.reverse() : parts
  }
  return (
    <>
      <div className="chain-toolbar">
        <h2>Option chain</h2>
        <Seg label="Show calls or puts" value={view} onChange={setView} options={[['CE', 'Calls'], ['PE', 'Puts']]} />
      </div>
      <div className={`chain-wrap show-${view.toLowerCase()}`}>
        <table className="chain-table">
          <thead>
            <tr className="chain-sides"><th colSpan={3} className="ce">Calls</th><th /><th colSpan={3} className="pe">Puts</th></tr>
            <tr className="chain-cols">
              <th className="ce" />
              <th className="ce">Δ</th>
              <th className="ce">Bid <small>ask</small></th>
              <th className="chain-k">Strike</th>
              <th className="pe">Bid <small>ask</small></th>
              <th className="pe">Δ</th>
              <th className="pe" />
            </tr>
          </thead>
          <tbody>
            {near.map((r) => (
              <tr key={r.strike} className={r.strike === atm ? 'atm' : ''}>
                {cells(r, 'CE')}
                <th scope="row" className="num chain-k">{strikeText(r.strike)}{r.strike === atm && <span className="spot-tag">Spot {num(chain.spot)}</span>}</th>
                {cells(r, 'PE')}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
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


  const blocked = busy || !preview || !!preview.buy_rule || !preview.sufficient
  const placeLabel = busy ? 'Placing…' : confirm ? 'Place anyway' : 'Place on virtual account'
  const dockNote = preview?.buy_rule ? 'Buy leg not allowed yet'
    : preview && !preview.sufficient ? 'Not enough free margin'
      : confirm ? 'Check the note above, then press again'
        : previewError || (preview ? `Margin ${rupee(preview.margin_change)}` : 'Checking margin…')

  return (
    <div className={`builder-page${legs.length ? ' has-dock' : ''}`}>
      <header className="builder-hero">
        <div>
          <h1 className="page-title"><Wrench size={20} aria-hidden /> Strategy builder</h1>
          <p className="muted">Build your own strategy on any Nifty 50 stock. Orders go to your virtual account.
            {!hedges && ' Bought legs must protect a sold leg until Level 6.'}</p>
        </div>
        <div className="builder-pick">
          <label className="pick">
            <span>Stock</span>
            <select id="b-symbol" value={symbol} onChange={(e) => choose({ symbol: e.target.value })}>
              <option value="">Choose a stock…</option>
              {universe.map((u) => <option key={u} value={u}>{u}</option>)}
            </select>
          </label>
          {chain && (
            <label className="pick">
              <span>Expiry</span>
              <select id="b-expiry" value={chain.expiry} onChange={(e) => choose({ symbol, expiry: e.target.value })}>
                {chain.expiries.map((x) => <option key={x} value={x}>{shortDate(x)}</option>)}
              </select>
            </label>
          )}
        </div>
        {chain && (
          <dl className="builder-facts">
            <div><dt>Spot</dt><dd className="num">{num(chain.spot)}</dd></div>
            <div><dt>Days left</dt><dd className="num">{chain.dte}</dd></div>
            <div><dt>Lot</dt><dd className="num">{int(lot)}</dd></div>
          </dl>
        )}
      </header>

      {error && <div className="alert" role="alert"><AlertTriangle size={18} aria-hidden /> {error}</div>}
      {symbol && !chain && !error && <p className="muted">Loading the option chain…</p>}
      {!symbol && <p className="builder-empty muted">Choose a stock to load its option chain.</p>}

      {chain && (
        <div className="builder-grid">
          <div className="b-main">
            <div className="builder-templates" role="group" aria-label="Templates">
              {Object.entries(TEMPLATES).map(([k, t]) => (
                <button key={k} className="tpl" onClick={() => template(k)}><Shape d={SHAPES[k]} />{t.label}</button>
              ))}
              <button className="tpl" onClick={() => setLegs([])}><Eraser size={16} aria-hidden />Blank</button>
            </div>

            <section className="card builder-legs" aria-label="Legs">
              <div className="card-head"><h2>Legs</h2>{legs.length > 0 && <span className="muted small">{legs.length} leg{legs.length > 1 ? 's' : ''}</span>}</div>
              {!legs.length && <p className="muted">Pick a template, or tap Sell or Buy on a strike in the chain.</p>}
              <ul className="leg-list">
                {legs.map((l, i) => (
                  <li key={i} className={`builder-leg ${l.action === 'BUY' ? 'is-buy' : 'is-sell'}`}>
                    <div className="leg-top">
                      <span className="side-pill">{l.action === 'BUY' ? 'Buy' : 'Sell'}</span>
                      <span className="leg-name num">{strikeText(l.strike)} {l.side}</span>
                      <span className="leg-px num">{rupee2(l.premium)}<small>Δ {l.delta == null ? '—' : num(l.delta, 2)}</small></span>
                      <button className="icon-btn" onClick={() => setLegs((ls) => ls.filter((_, j) => j !== i))} aria-label="Remove leg"><Trash2 size={16} /></button>
                    </div>
                    <div className="leg-controls">
                      <Seg label="Buy or sell" value={l.action} tone onChange={(v) => update(i, { action: v })} options={[['SELL', 'Sell'], ['BUY', 'Buy']]} />
                      <select aria-label="Strike" value={l.strike} onChange={(e) => update(i, { strike: Number(e.target.value) })}>
                        {chain.rows.filter((r) => r[l.side]).map((r) => <option key={r.strike} value={r.strike}>{strikeText(r.strike)}</option>)}
                      </select>
                      <Seg label="Call or put" value={l.side} onChange={(v) => update(i, { side: v })} options={[['CE', 'CE'], ['PE', 'PE']]} />
                      <div className="lots" role="group" aria-label="Lots">
                        <button type="button" onClick={() => update(i, { lots: Math.max(1, l.lots - 1) })} disabled={l.lots <= 1} aria-label="Fewer lots"><Minus size={14} /></button>
                        <input aria-label="Lots" type="number" inputMode="numeric" min="1" max="50" value={l.lots}
                          onChange={(e) => update(i, { lots: Math.max(1, Math.min(50, Number(e.target.value) || 1)) })} />
                        <button type="button" onClick={() => update(i, { lots: Math.min(50, l.lots + 1) })} disabled={l.lots >= 50} aria-label="More lots"><Plus size={14} /></button>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </section>

            {warn.length > 0 && (
              <ul className="builder-warnings" aria-label="Warnings">
                {warn.map((w) => <li key={w}><AlertTriangle size={14} aria-hidden /> {w}</li>)}
              </ul>
            )}
          </div>

          <aside className="card b-side" aria-label="Analysis">
            <div className="card-head"><h2>At expiry</h2></div>
            {legs.length > 0 && s ? (
              <>
                <div className="b-net">
                  <span>{s.net >= 0 ? 'Net credit' : 'Net debit'}</span>
                  <strong className="num">{rupee(Math.abs(s.net))}</strong>
                </div>
                <dl className="b-pl">
                  <div><dt>Max profit</dt><dd className="num pos">{money(s.maxProfit)}</dd></div>
                  <div><dt>Max loss</dt><dd className="num neg">{money(s.maxLoss)}</dd></div>
                </dl>
                <dl className="builder-stats">
                  <div><dt>Breakevens</dt><dd className="num">{s.breakevens.map((b) => num(b, 0)).join(' · ') || '—'}</dd></div>
                  <div><dt>Margin needed</dt><dd className="num">{preview ? rupee(preview.margin_change) : '…'}</dd></div>
                  <div><dt>Net delta</dt><dd className="num">{num(g.delta, 1)}</dd></div>
                  <div><dt>Theta / day</dt><dd className="num">{rupee(g.theta)}</dd></div>
                </dl>
                <GroupPayoff legs={payoffLegs} spot={chain.spot} />
                <div className="builder-place">
                  {preview?.buy_rule && <div className="alert" role="alert"><AlertTriangle size={18} aria-hidden /> {preview.buy_rule}</div>}
                  {preview && !preview.sufficient && (
                    <div className="alert" role="alert">Not enough free margin: needs {rupee(preview.margin_change)}, available {rupee(preview.available_margin)}</div>
                  )}
                  {confirm && preview?.illiquid?.length > 0 && <p className="neg small">Thin market on {preview.illiquid.map((x) => `${x.strike} ${x.side}`).join(', ')}. Press again to place anyway.</p>}
                  {confirm && preview?.waiting?.length > 0 && <p className="neg small">An earlier order on this stock and expiry is still waiting. Press again to place another.</p>}
                  {previewError && <p className="neg small" role="alert">{previewError}</p>}
                  {preview?.notes?.map((n) => <p key={n} className="muted small">{n}</p>)}
                  <button className="btn primary" onClick={place} disabled={blocked}>
                    <Plus size={15} aria-hidden /> {placeLabel}
                  </button>
                </div>
              </>
            ) : <p className="muted">Add legs to see the payoff, margin and Greeks.</p>}
            {done && (
              <p className="pos b-done" role="status"><CheckCircle2 size={16} aria-hidden /> Order placed: {done.filled.length} filled{done.open.length ? `, ${done.open.length} waiting` : ''}. <Link to="/portfolio">See it in Portfolio</Link></p>
            )}
          </aside>

          <section className="card b-chain" aria-label="Option chain">
            <ChainTable chain={chain} onAdd={add} />
          </section>
        </div>
      )}

      {chain && legs.length > 0 && s && (
        <div className="builder-dock" aria-label="Order summary">
          <div className="dock-info">
            <span className="num"><strong>{rupee(Math.abs(s.net))}</strong> {s.net >= 0 ? 'credit' : 'debit'}</span>
            <small className={preview?.buy_rule || (preview && !preview.sufficient) ? 'neg' : 'muted'}>{dockNote}</small>
          </div>
          <button className="btn primary" onClick={place} disabled={blocked}>{busy ? 'Placing…' : confirm ? 'Place anyway' : 'Place order'}</button>
        </div>
      )}
    </div>
  )
}
