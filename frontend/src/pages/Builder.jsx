import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AlertTriangle, Bookmark, CheckCircle2, Eraser, FolderOpen, Lock, Minus, Pin, PinOff, Plus, ShieldCheck, Trash2, Wrench } from 'lucide-react'
import { rpc } from '../rpc'
import { can, useAuth } from '../auth'
import { useBudget } from '../settings'
import { useTitle } from '../brand'
import { int, num, rupee, rupee2, shortDate } from '../format'
import { BuilderPayoff } from '../components/Charts'
import { sdRange } from '../bs'
import {
  SAFE_TEMPLATES, TEMPLATES, addLot, atmIv, curve, zoneAt as zoneOf, greeks, legAt, makeLeg, netLegs, pnlOn, probProfit, restoreLegs, scorecard, stats,
} from '../strategy'

// Strategy builder (issue #137): any Nifty 50 stock, any expiry, any mix of sold and bought legs.
// Open to every account. The screening rules show as a rule check that never blocks. Bought legs on their own unlock
// at Level 6 (`hedges`); before that a buy must protect a sell, which the server enforces and the
// preview explains (`buy_rule`). Orders go to the virtual account.

const money = (v) => (v === Infinity ? 'Unlimited' : v === -Infinity ? 'Unlimited' : rupee(v))
const strikeText = (k) => num(k, k % 1 ? 2 : 0)
const compact = (v) => (v >= 1e5 ? `${num(v / 1e5, 1)}L` : v >= 1e3 ? `${num(v / 1e3, 1)}k` : int(v))
const pct = (v) => (v == null ? '—' : `${num(v * 100, 0)}%`)

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

function ChainTable({ chain, legs, onAdd, levels }) {
  const [view, setView] = useState('CE') // phones show one side at a time
  const [wide, setWide] = useState(false) // ±12 strikes, or the whole chain
  const maxOi = useMemo(() => Math.max(1, ...chain.rows.flatMap((r) => [r.CE?.oi ?? 0, r.PE?.oi ?? 0])), [chain])
  const atm = useMemo(() => chain.rows.find((r) => r.strike >= chain.spot)?.strike, [chain])
  const near = useMemo(() => {
    const i = chain.rows.findIndex((r) => r.strike >= chain.spot)
    const mid = i < 0 ? chain.rows.length : i
    return wide ? chain.rows : chain.rows.slice(Math.max(0, mid - 12), mid + 12)
  }, [chain, wide])
  // A strike in the strategy shows its leg here (#144): tinted red for a sell, blue for a buy, with
  // the lot count and -/+ in place of Sell/Buy. Minus on the last lot drops the leg.
  const zoneAt = (k) => zoneOf(levels, k)
  const acts = (r, side, leg) => {
    const name = `${strikeText(r.strike)} ${side}`
    if (leg) {
      const less = leg.action === 'SELL' ? 'BUY' : 'SELL'
      return (
        <td className={`chain-act ${side.toLowerCase()} ${leg.action === 'SELL' ? 'leg-sell' : 'leg-buy'}`}>
          <span className="chain-lots" role="group" aria-label={`${leg.action === 'SELL' ? 'Sold' : 'Bought'} ${name}`}>
            <button type="button" onClick={() => onAdd(side, r.strike, less)} aria-label={`One lot less of ${name}`}><Minus size={13} /></button>
            <b className="num">{leg.action === 'SELL' ? 'S' : 'B'}&thinsp;{leg.lots}</b>
            <button type="button" onClick={() => onAdd(side, r.strike, leg.action)} aria-label={`One lot more of ${name}`}><Plus size={13} /></button>
          </span>
        </td>
      )
    }
    return (
      <td className={`chain-act ${side.toLowerCase()}`}>
        <button className="act sell" onClick={() => onAdd(side, r.strike, 'SELL')} aria-label={`Sell ${r.strike} ${side}`}>Sell</button>
        <button className="act buy" onClick={() => onAdd(side, r.strike, 'BUY')} aria-label={`Buy ${r.strike} ${side}`}>Buy</button>
      </td>
    )
  }
  const cells = (r, side) => {
    const q = r[side]
    const leg = legAt(legs, side, r.strike)
    const s = `${side.toLowerCase()}${leg ? (leg.action === 'SELL' ? ' leg-sell' : ' leg-buy') : ''}`
    const itm = side === 'CE' ? r.strike < chain.spot : r.strike > chain.spot
    if (!q) return <td colSpan={5} className={`muted ${s}`}>—</td>
    const parts = [
      <td key="p" className={`num chain-px ${s}${itm ? ' itm' : ''}`}><span>{num(q.bid)}</span><small>{num(q.ask)}</small></td>,
      <td key="d" className={`num chain-d ${s}${itm ? ' itm' : ''}`}>{q.delta == null ? '—' : num(q.delta, 2)}</td>,
      <td key="i" className={`num chain-iv ${s}`}>{q.iv > 0 ? num(q.iv, 1) : '—'}</td>,
      <td key="o" className={`num chain-oi ${s}`} title={`Open interest ${int(q.oi)}`}>
        <span className="oi-bar" style={{ width: `${Math.round((q.oi / maxOi) * 100)}%` }} aria-hidden /><span>{compact(q.oi)}</span>
      </td>,
      <Fragment key="a">{acts(r, side, leg)}</Fragment>,
    ]
    return side === 'CE' ? parts.reverse() : parts
  }
  return (
    <>
      <div className="chain-toolbar">
        <h2>Option chain</h2>
        <button type="button" className="btn small" aria-pressed={wide} onClick={() => setWide((w) => !w)}>{wide ? 'Near strikes' : 'All strikes'}</button>
        <Seg label="Show calls or puts" value={view} onChange={setView} options={[['CE', 'Calls'], ['PE', 'Puts']]} />
      </div>
      <div className={`chain-wrap show-${view.toLowerCase()}`}>
        <table className="chain-table">
          <thead>
            <tr className="chain-sides"><th colSpan={5} className="ce">Calls</th><th /><th colSpan={5} className="pe">Puts</th></tr>
            <tr className="chain-cols">
              <th className="ce" />
              <th className="ce chain-oi">OI</th>
              <th className="ce chain-iv">IV</th>
              <th className="ce">Δ</th>
              <th className="ce">Bid <small>ask</small></th>
              <th className="chain-k">Strike</th>
              <th className="pe">Bid <small>ask</small></th>
              <th className="pe">Δ</th>
              <th className="pe chain-iv">IV</th>
              <th className="pe chain-oi">OI</th>
              <th className="pe" />
            </tr>
          </thead>
          <tbody>
            {near.map((r) => (
              <tr key={r.strike} className={r.strike === atm ? 'atm' : ''}>
                {cells(r, 'CE')}
                <th scope="row" className={`num chain-k${zoneAt(r.strike) ? ` in-zone ${zoneAt(r.strike).type}` : ''}`}
                  title={zoneAt(r.strike) ? `In a ${zoneAt(r.strike).type} zone` : undefined}>
                  {strikeText(r.strike)}{r.strike === atm && <span className="spot-tag">Spot {num(chain.spot)}</span>}
                </th>
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
  const [levels, setLevels] = useState(null) // monthly pivots + S/R zones; the page works without them
  const [daysAhead, setDaysAhead] = useState(0)
  const [ivShift, setIvShift] = useState(0)
  const [baseline, setBaseline] = useState(null) // { legs, stats, margin } pinned for comparison
  const [safe, setSafe] = useState(false) // templates pick rule-safe strikes

  useEffect(() => { rpc('get_config').then((c) => setUniverse(c.universe)).catch((e) => setError(e.message)) }, [])

  // Saved strategies (#150), unlocked at Level 5.
  const canSave = can(user, 'saved_strategies')
  const [saved, setSaved] = useState([])
  const [saveName, setSaveName] = useState('')
  const [saveMsg, setSaveMsg] = useState(null)
  const [pending, setPending] = useState(null) // a strategy to load once its chain arrives
  const [notice, setNotice] = useState(null)
  const loadSaved = () => { if (canSave) rpc('strategy_list').then(setSaved).catch(() => {}) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(loadSaved, [canSave])
  useEffect(() => {
    if (!symbol) return
    setChain(null); setError(null); setLegs([]); setDone(null); setBaseline(null); setDaysAhead(0); setIvShift(0)
    // `asked` records which request a chain answers, so a saved strategy waits for the right one.
    rpc('builder_chain', expiry ? { symbol, expiry } : { symbol }).then((c) => setChain({ ...c, asked: expiry })).catch((e) => setError(e.message))
  }, [symbol, expiry])

  useEffect(() => {
    setLevels(null)
    if (symbol) rpc('builder_levels', { symbol }).then(setLevels).catch(() => {})
  }, [symbol])

  const choose = (next) => setParams(Object.fromEntries(Object.entries(next).filter(([, v]) => v)))

  const openSaved = (st) => {
    setNotice(null); setDone(null); setPending(st)
    // An expired strategy always goes to the default live expiry (the first at least 30 days out).
    const here = chain && chain.symbol === st.symbol && (st.expired ? !expiry : chain.expiry === st.expiry)
    if (!here) choose({ symbol: st.symbol, expiry: st.expired ? '' : st.expiry })
  }
  useEffect(() => {
    if (!pending || !chain || chain.symbol !== pending.symbol || chain.asked !== expiry
      || (pending.expired ? expiry : chain.expiry !== pending.expiry)) return
    const { legs: made, missing } = restoreLegs(chain, pending, pending.expired)
    setLegs(made)
    setNotice(pending.expired
      ? `"${pending.name}" was for ${pending.expiry}, which has passed. Moved to ${chain.expiry}, with each strike matched by delta. Check the legs before placing.`
      : missing ? `${missing} leg${missing > 1 ? 's' : ''} of "${pending.name}" had no price today and ${missing > 1 ? 'were' : 'was'} left out.` : null)
    setSaveName(pending.name)
    setPending(null)
  }, [pending, chain, expiry])

  async function saveStrategy() {
    setSaveMsg(null)
    try {
      const r = await rpc('strategy_save', {
        name: saveName, symbol: chain.symbol, expiry: chain.expiry,
        legs: legs.map((l) => ({ side: l.side, strike: l.strike, action: l.action, lots: l.lots, ...(l.delta != null ? { delta: l.delta } : {}) })),
      })
      setSaveMsg({ ok: true, text: r.replaced ? `Updated "${r.name}"` : `Saved "${r.name}"` })
      loadSaved()
    } catch (e) { setSaveMsg({ ok: false, text: e.message }) }
  }
  const removeSaved = async (st) => {
    try { await rpc('strategy_delete', { strategy_id: st.id }); loadSaved() } catch (e) { setSaveMsg({ ok: false, text: e.message }) }
  }
  // One leg per strike and type: S or B again adds a lot, the opposite takes one off (#144).
  const add = (side, strike, action) => {
    if (chain) { setLegs((ls) => addLot(chain, ls, side, strike, action)); setDone(null) }
  }
  const template = (key) => {
    const made = (safe && SAFE_TEMPLATES[key] ? SAFE_TEMPLATES[key](chain, levels) : TEMPLATES[key].legs(chain)).filter(([, k]) => k != null).map(([s, k, a]) => makeLeg(chain, s, k, a)).filter(Boolean)
    setLegs(netLegs(chain, made)); setDone(null)
  }
  // Editing a leg into one that already exists merges them, so the chain and the list agree.
  const update = (i, patch) => setLegs((ls) => netLegs(chain, ls.map((l, j) => {
    if (j !== i) return l
    const next = { ...l, ...patch }
    return makeLeg(chain, next.side, next.strike, next.action, next.lots) ?? l
  })))

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
  const iv = chain ? atmIv(chain) : 0
  const g = useMemo(() => (chain ? greeks(legs, chain.spot, chain.dte, lot, iv) : null), [legs, chain, lot, iv])
  const card = chain ? scorecard(chain, legs, levels) : []
  const failing = card.filter((r) => !r.ok).length
  const pop = useMemo(() => (chain ? probProfit(legs, chain) : null), [legs, chain])
  const days = chain ? Math.min(daysAhead, chain.dte) : 0
  const points = useMemo(() => (chain && legs.length ? curve(legs, chain, { daysAhead: days, ivShift, baseline: baseline?.legs }) : []),
    [legs, chain, days, ivShift, baseline])
  const sd = chain && iv > 0 ? sdRange(chain.spot, iv, chain.dte, 1) : null
  const nowLabel = days === 0 ? 'Today' : days >= (chain?.dte ?? 0) ? 'Expiry' : `In ${days} day${days > 1 ? 's' : ''}`
  const pnlThen = chain && legs.length ? pnlOn(legs, chain.spot, chain.dte, lot, chain.spot, Math.max(chain.dte - days, 0), ivShift, iv) : 0
  const margin = preview?.margin_change
  const rom = s && margin > 0 && Number.isFinite(s.maxProfit) ? s.maxProfit / margin : null
  const pin = () => setBaseline({ legs, stats: s, margin, pop })
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


  const delta = (a, b, f) => (a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b) ? '—' : `${a - b >= 0 ? '+' : '−'}${f(Math.abs(a - b))}`)

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

      {canSave && saved.length > 0 && (
        <section className="card builder-saved" aria-label="My strategies">
          <div className="card-head"><h2>My strategies</h2><span className="muted small">{saved.length}</span></div>
          <ul>
            {saved.map((st) => (
              <li key={st.id}>
                <div className="saved-name">
                  <b>{st.name}</b>
                  <span className="muted small num">{st.symbol} · {shortDate(st.expiry)} · {st.legs.map((l) => `${l.action === 'SELL' ? 'S' : 'B'}${l.lots > 1 ? l.lots : ''} ${strikeText(l.strike)}${l.side}`).join(', ')}</span>
                  {st.expired && <span className="chip small">Expired: opens on a live expiry</span>}
                </div>
                <button className="btn small" onClick={() => openSaved(st)} aria-label={`Open ${st.name}`}><FolderOpen size={15} aria-hidden /> Open</button>
                <button className="icon-btn" onClick={() => removeSaved(st)} aria-label={`Delete ${st.name}`}><Trash2 size={16} /></button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {chain && (
        <div className="builder-grid">
          <div className="b-main">
            <div className="builder-templates" role="group" aria-label="Templates">
              {Object.entries(TEMPLATES).map(([k, t]) => (
                <button key={k} className="tpl" onClick={() => template(k)}><Shape d={SHAPES[k]} />{t.label}</button>
              ))}
              <button className="tpl" onClick={() => setLegs([])}><Eraser size={16} aria-hidden />Blank</button>
            </div>
            <label className="safe-toggle small">
              <input type="checkbox" checked={safe} onChange={(e) => setSafe(e.target.checked)} />
              <ShieldCheck size={15} aria-hidden /> Rule-safe strikes: sold strikes under delta {chain.rules.delta_max_abs}{levels ? ' and clear of S/R zones' : ''}, most premium first
            </label>
            {notice && <p className="alert builder-notice" role="status"><AlertTriangle size={16} aria-hidden /> {notice}</p>}

            <section className="card builder-legs" aria-label="Legs">
              <div className="card-head"><h2>Legs</h2>{legs.length > 0 && <span className="muted small">{legs.length} leg{legs.length > 1 ? 's' : ''}</span>}</div>
              {!legs.length && <p className="muted">Pick a template, or tap Sell or Buy on a strike in the chain.</p>}
              <ul className="leg-list">
                {legs.map((l, i) => (
                  <li key={`${l.side}${l.strike}`} className={`builder-leg ${l.action === 'BUY' ? 'is-buy' : 'is-sell'}`}>
                    <div className="leg-top">
                      <span className="side-pill">{l.action === 'BUY' ? 'Buy' : 'Sell'}</span>
                      <span className="leg-name num">{strikeText(l.strike)} {l.side}</span>
                      <span className="leg-px num">{rupee2(l.premium)}<small>Δ {l.delta == null ? '—' : num(l.delta, 2)} · IV {l.iv > 0 ? num(l.iv, 1) : '—'}</small></span>
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

            {legs.length > 0 && (
              <section className="card builder-score" aria-label="Rule check">
                <div className="card-head">
                  <h2>Rule check</h2>
                  <span className={`chip small ${failing ? 'neg' : 'pos'}`}>{failing ? `${failing} to review` : 'All clear'}</span>
                </div>
                <ul>
                  {card.map((r) => (
                    <li key={r.label} className={r.ok ? 'ok' : 'warn'}>
                      {r.ok ? <CheckCircle2 size={15} aria-hidden /> : <AlertTriangle size={15} aria-hidden />}
                      <div><b>{r.label}</b><span className="small">{r.detail}</span></div>
                    </li>
                  ))}
                </ul>
                <p className="muted small">The rules never block an order here; they are what the screener and auto-trade follow.</p>
              </section>
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
                  <div><dt title="Chance the position is in profit at expiry, from the ATM implied volatility">Probability of profit</dt><dd className="num">{pct(pop)}</dd></div>
                  <div><dt title="Max profit as a share of the margin blocked">Return on margin</dt><dd className="num">{rom == null ? '—' : pct(rom)}</dd></div>
                  <div><dt>Net delta</dt><dd className="num">{num(g.delta, 1)}</dd></div>
                  <div><dt>Theta / day</dt><dd className="num">{rupee(g.theta)}</dd></div>
                  <div><dt>Gamma</dt><dd className="num">{num(g.gamma, 2)}</dd></div>
                  <div><dt title="P&L for a 1-point rise in implied volatility">Vega / IV pt</dt><dd className="num">{rupee(g.vega)}</dd></div>
                  {sd && <div><dt>1σ move by expiry</dt><dd className="num">±{num(sd.pct, 1)}% ({num(sd.low, 0)}–{num(sd.high, 0)})</dd></div>}
                  <div><dt>ATM IV</dt><dd className="num">{iv > 0 ? `${num(iv, 1)}%` : '—'}</dd></div>
                </dl>
                <BuilderPayoff points={points} spot={chain.spot} sd={sd} levels={levels} nowLabel={nowLabel} />
                <div className="whatif" role="group" aria-label="What if">
                  <label>
                    <span>Date: <b className="num">{nowLabel}</b>{days > 0 && days < chain.dte && <span className="muted"> ({chain.dte - days} days left)</span>}</span>
                    <input type="range" min="0" max={chain.dte} step="1" value={days} aria-label="Days from today"
                      onChange={(e) => setDaysAhead(Number(e.target.value))} />
                  </label>
                  <label>
                    <span>IV change: <b className="num">{ivShift > 0 ? '+' : ''}{ivShift} pts</b></span>
                    <input type="range" min="-15" max="15" step="1" value={ivShift} aria-label="IV change in points"
                      onChange={(e) => setIvShift(Number(e.target.value))} />
                  </label>
                  <p className="small">P&L at today's spot, {nowLabel.toLowerCase()}: <b className={`num ${pnlThen >= 0 ? 'pos' : 'neg'}`}>{rupee(pnlThen)}</b>
                    {(days || ivShift) ? <button type="button" className="link-btn" onClick={() => { setDaysAhead(0); setIvShift(0) }}>Reset</button> : null}</p>
                </div>
                <div className="baseline">
                  {baseline ? (
                    <>
                      <div className="card-head"><h3>Against the pinned version</h3>
                        <button type="button" className="btn small" onClick={() => setBaseline(null)}><PinOff size={14} aria-hidden /> Unpin</button></div>
                      <dl className="builder-stats">
                        <div><dt>Net credit</dt><dd className="num">{delta(s.net, baseline.stats.net, rupee)}</dd></div>
                        <div><dt>Max loss</dt><dd className="num">{delta(s.maxLoss, baseline.stats.maxLoss, rupee)}</dd></div>
                        <div><dt>Margin</dt><dd className="num">{delta(margin, baseline.margin, rupee)}</dd></div>
                        <div><dt>Probability of profit</dt><dd className="num">{delta(pop, baseline.pop, (v) => `${num(v * 100, 0)} pts`)}</dd></div>
                      </dl>
                    </>
                  ) : (
                    <button type="button" className="btn small" onClick={pin} disabled={!preview}>
                      <Pin size={14} aria-hidden /> Pin to compare an adjustment
                    </button>
                  )}
                </div>
                <div className="builder-save">
                  {canSave ? (
                    <>
                      <label className="sr-only" htmlFor="b-save-name">Strategy name</label>
                      <input id="b-save-name" value={saveName} maxLength={40} placeholder="Name this strategy"
                        onChange={(e) => setSaveName(e.target.value)} />
                      <button className="btn" onClick={saveStrategy} disabled={!saveName.trim()}><Bookmark size={15} aria-hidden /> Save</button>
                    </>
                  ) : (
                    <button className="btn" disabled title="Saved strategies unlock at Level 5"><Lock size={15} aria-hidden /> Save · unlocks at Level 5</button>
                  )}
                  {saveMsg && <p className={`small ${saveMsg.ok ? 'pos' : 'neg'}`} role="status">{saveMsg.text}</p>}
                </div>
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
            <ChainTable chain={chain} legs={legs} onAdd={add} levels={levels} />
          </section>
        </div>
      )}

      {chain && legs.length > 0 && s && (
        <div className="builder-dock" aria-label="Order summary">
          <div className="dock-info">
            <span className="num"><strong>{rupee(Math.abs(s.net))}</strong> {s.net >= 0 ? 'credit' : 'debit'}</span>
            <small className={preview?.buy_rule || (preview && !preview.sufficient) ? 'neg' : 'muted'}>{dockNote}</small>
          </div>
          <button className="btn primary" onClick={place} disabled={blocked}>{busy ? 'Placing…' : confirm ? 'Place anyway' : 'Place virtual order'}</button>
        </div>
      )}
    </div>
  )
}
