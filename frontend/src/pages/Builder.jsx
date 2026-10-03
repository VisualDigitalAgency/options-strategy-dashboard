import { Fragment, cloneElement, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { AlertTriangle, Bookmark, UserPlus, CheckCircle2, Eraser, FolderOpen, Lock, Minus, Pin, PinOff, Plus, ShieldCheck, Trash2, Wrench } from 'lucide-react'
import { rpc } from '../rpc'
import { can, useAuth } from '../auth'
import { useBudget } from '../settings'
import { useTitle } from '../brand'
import { int, num, rupee, rupee2, shortDate, signedRupee, todayIso } from '../format'
import { BuilderPayoff } from '../components/Charts'
import { bsGreeks, sdRange } from '../bs'
import {
  SAFE_TEMPLATES, TEMPLATES, addLot, atmIv, closeOrRoll, curve, heldLegs, resulting, zoneAt as zoneOf, greeks, legAt, makeLeg, netLegs, pnlOn, probProfit, restoreLegs, scorecard, stats,
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

const pctText = (v) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${num(Math.abs(v), 2)}%`
const weeksText = (dte) => (dte < 14 ? `${dte} d` : dte < 56 ? `${Math.round(dte / 7)} wk` : `${Math.round(dte / 30)} mo`)

// Broker-style option chain (#158): calls on the left, puts on the right, the strike in the middle
// with a bar of call OI (red) vs put OI (green). Two tabs: OI and Greeks. Buy/Sell stay hidden until
// a strike row is tapped; a strike already in the strategy keeps its tint and its lot count.
function ChainTable({ chain, legs, onAdd, levels, onExpiry }) {
  const [tab, setTab] = useState('oi')
  const [wide, setWide] = useState(false) // ±12 strikes, or the whole chain
  const [open, setOpen] = useState(null) // the strike whose Buy/Sell strip is showing
  const maxOi = useMemo(() => Math.max(1, ...chain.rows.flatMap((r) => [r.CE?.oi ?? 0, r.PE?.oi ?? 0])), [chain])
  const maxPair = useMemo(() => Math.max(1, ...chain.rows.map((r) => (r.CE?.oi ?? 0) + (r.PE?.oi ?? 0))), [chain])
  const atm = chain.summary?.atm_strike ?? chain.rows.find((r) => r.strike >= chain.spot)?.strike
  const near = useMemo(() => {
    const i = chain.rows.findIndex((r) => r.strike >= chain.spot)
    const mid = i < 0 ? chain.rows.length : i
    return wide ? chain.rows : chain.rows.slice(Math.max(0, mid - 12), mid + 12)
  }, [chain, wide])
  const zoneAt = (k) => zoneOf(levels, k)
  const greeksOf = (side, r) => {
    const q = r[side]
    return q && q.iv > 0 ? bsGreeks(side, chain.spot, r.strike, Math.max(chain.dte, 0.5), q.iv) : null
  }

  const ltpCell = (r, side) => {
    const q = r[side]
    const leg = legAt(legs, side, r.strike)
    const name = `${strikeText(r.strike)} ${side}`
    return (
      <td className={`num chain-ltp ${side.toLowerCase()}${leg ? (leg.action === 'SELL' ? ' leg-sell' : ' leg-buy') : ''}`}>
        <span>{q ? num(q.ltp) : '—'}</span>
        {q?.pchg != null && <small className={`px-chg ${q.pchg > 0 ? 'up' : q.pchg < 0 ? 'down' : ''}`} title="Last trade vs yesterday's close">{pctText(q.pchg)}</small>}
        {leg && (
          <span className="chain-lots" role="group" aria-label={`${leg.action === 'SELL' ? 'Sold' : 'Bought'} ${name}`} onClick={(e) => e.stopPropagation()}>
            <button type="button" onClick={() => onAdd(side, r.strike, leg.action === 'SELL' ? 'BUY' : 'SELL')} aria-label={`One lot less of ${name}`}><Minus size={12} /></button>
            <b className="num">{leg.action === 'SELL' ? 'S' : 'B'}&thinsp;{leg.lots}</b>
            <button type="button" onClick={() => onAdd(side, r.strike, leg.action)} aria-label={`One lot more of ${name}`}><Plus size={12} /></button>
          </span>
        )}
      </td>
    )
  }
  // The columns outside the LTP for one side, outermost first (calls read right-to-left).
  const sideCells = (r, side) => {
    const q = r[side]
    const s = side.toLowerCase()
    if (tab === 'oi') {
      return [
        <td key="oi" className={`num chain-oi ${s}`} title={q ? `Open interest ${int(q.oi)}` : undefined}>
          {q ? <>
            <span className="oi-bar" style={{ width: `${Math.round((q.oi / maxOi) * 100)}%` }} aria-hidden /><span>{compact(q.oi)}</span>
            {q.oi_chg != null && q.oi_chg !== 0 && <small className={`oi-chg ${q.oi_chg > 0 ? 'up' : 'down'}`}>{q.oi_chg > 0 ? '+' : '−'}{compact(Math.abs(q.oi_chg))}</small>}
          </> : '—'}
        </td>,
      ]
    }
    const g = greeksOf(side, r)
    const cell = (k, v, d, cls = '') => <td key={k} className={`num chain-g ${s} ${cls}`}>{v == null ? '—' : num(v, d)}</td>
    return [
      cell('v', g?.vega, 2), cell('t', g?.theta, 2), cell('g', g?.gamma, 4),
      cell('d', g?.delta, 2), cell('iv', q?.iv > 0 ? q.iv : null, 1),
    ]
  }
  const head = tab === 'oi' ? [['OI', 'chain-oi']] : [['Vega', ''], ['Θ', ''], ['Γ', ''], ['Δ', ''], ['IV', '']]
  const span = head.length + 1

  return (
    <>
      <div className="chain-toolbar">
        <h2>Option chain</h2>
        <Seg label="Chain view" value={tab} onChange={setTab} options={[['oi', 'OI'], ['greeks', 'Greeks']]} />
        <button type="button" className="btn small" aria-pressed={wide} onClick={() => setWide((w) => !w)}>{wide ? 'Near strikes' : 'All strikes'}</button>
      </div>
      <div className="expiry-pills" role="group" aria-label="Expiry">
        {chain.expiries.map((x) => {
          const dte = Math.max(0, Math.round((new Date(x) - new Date(todayIso())) / 864e5))
          return (
            <button key={x} type="button" aria-pressed={x === chain.expiry} onClick={() => x !== chain.expiry && onExpiry(x)}>
              {shortDate(x)} <small>({weeksText(dte)})</small>
            </button>
          )
        })}
      </div>
      <div className="chain-wrap">
        <table className={`chain-table chain-v2 tab-${tab}`}>
          <thead>
            <tr className="chain-cols">
              {head.map(([t, c]) => <th key={`c${t}`} className={`ce ${c}`}>{t}</th>)}
              <th className="ce">Call LTP</th>
              <th className="chain-k">Strike</th>
              <th className="pe">Put LTP</th>
              {[...head].reverse().map(([t, c]) => <th key={`p${t}`} className={`pe ${c}`}>{t}</th>)}
            </tr>
          </thead>
          <tbody>
            {near.map((r) => {
              const ceOi = r.CE?.oi ?? 0
              const peOi = r.PE?.oi ?? 0
              const zone = zoneAt(r.strike)
              const isOpen = open === r.strike
              return (
                <Fragment key={r.strike}>
                  <tr className={`chain-row${r.strike === atm ? ' atm' : ''}${isOpen ? ' open' : ''}`}
                    onClick={() => setOpen(isOpen ? null : r.strike)} aria-expanded={isOpen}>
                    {sideCells(r, 'CE').map((c) => cloneWithItm(c, r.strike < chain.spot))}
                    {cloneWithItm(ltpCell(r, 'CE'), r.strike < chain.spot)}
                    <th scope="row" className={`num chain-k${zone ? ` in-zone ${zone.type}` : ''}`} title={zone ? `In a ${zone.type} zone` : undefined}>
                      <span className={r.strike === atm ? 'atm-chip' : ''}>{strikeText(r.strike)}</span>
                      <span className="pair-bar" aria-label={`Call OI ${compact(ceOi)}, put OI ${compact(peOi)}`}
                        style={{ width: `${Math.max(12, Math.round(((ceOi + peOi) / maxPair) * 100))}%` }}>
                        <i className="pb-ce" style={{ flexGrow: ceOi || 0.0001 }} /><i className="pb-pe" style={{ flexGrow: peOi || 0.0001 }} />
                      </span>
                    </th>
                    {cloneWithItm(ltpCell(r, 'PE'), r.strike > chain.spot)}
                    {[...sideCells(r, 'PE')].reverse().map((c) => cloneWithItm(c, r.strike > chain.spot))}
                  </tr>
                  {isOpen && (
                    <tr className="chain-actions">
                      {['CE', null, 'PE'].map((side) => side === null
                        ? <td key="k" className="chain-k" />
                        : (
                          <td key={side} colSpan={span} className={side.toLowerCase()}>
                            {r[side] ? (
                              <div className="act-strip">
                                <span className="num muted small">Bid {num(r[side].bid)} · Ask {num(r[side].ask)}</span>
                                <button className="act buy" onClick={() => onAdd(side, r.strike, 'BUY')} aria-label={`Buy ${r.strike} ${side}`}>Buy</button>
                                <button className="act sell" onClick={() => onAdd(side, r.strike, 'SELL')} aria-label={`Sell ${r.strike} ${side}`}>Sell</button>
                              </div>
                            ) : <span className="muted small">No {side === 'CE' ? 'call' : 'put'} quoted</span>}
                          </td>
                        ))}
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
      {chain.summary && (
        <dl className="chain-foot">
          <div><dt>PCR</dt><dd className="num">{chain.summary.pcr ?? '—'}</dd></div>
          <div><dt>Max pain</dt><dd className="num">{chain.summary.max_pain == null ? '—' : strikeText(chain.summary.max_pain)}</dd></div>
          <div><dt>ATM IV</dt><dd className="num">{chain.summary.atm_iv == null ? '—' : num(chain.summary.atm_iv, 2)}</dd></div>
        </dl>
      )}
      <p className="oi-legend small muted">Tap a strike to buy or sell.{tab === 'greeks' && ' Swipe sideways to see every Greek.'} Strike bar: <span className="oi-chg down">red</span> call OI · <span className="oi-chg up">green</span> put OI. Price change is the last trade vs yesterday's close.</p>
    </>
  )
}

// Shades the in-the-money side of a strike (calls below spot, puts above).
const DRAFT_KEY = 'builder:draft'

function JoinPrompt({ onClose }) {
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-labelledby="join-h">
      <div className="modal">
        <h2 id="join-h"><UserPlus size={20} aria-hidden /> Place this trade for free</h2>
        <p>Create a free account to place this strategy on a ₹2 lakh virtual account with live NSE prices,
          see its margin, and track your progress through the levels. Your legs are kept: they will be
          here when you come back signed in.</p>
        <div className="modal-actions">
          <button className="btn ghost" onClick={onClose}>Keep exploring</button>
          <Link to="/login?next=%2Fbuilder" className="btn">Sign in</Link>
          <Link to="/register" className="btn primary" autoFocus>Join free</Link>
        </div>
      </div>
    </div>
  )
}

const cloneWithItm = (el, itm) => (itm ? cloneElement(el, { className: `${el.props.className} itm` }) : el)

// Signed-out visitors may load one chain per 2 s (server READER_EVERY). Switching stock faster
// waits out the gap and retries once, instead of showing "Too many requests" (#198).
const READER_WAIT_MS = 2100
const builderRpc = (method, params) => rpc(method, params).catch((e) =>
  /^Too many requests/.test(e.message)
    ? new Promise((r) => setTimeout(r, READER_WAIT_MS)).then(() => rpc(method, params))
    : Promise.reject(e))

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
  // Adjust mode (from Portfolio): the open position on this stock and expiry is held fixed, the legs
  // below are the adjustment, and the analysis shows the position after it against the one now.
  const adjust = params.get('adjust') === '1'
  const [held, setHeld] = useState([])
  const [heldTick, setHeldTick] = useState(0)

  // Readers (#163): a signed-out visitor builds with the public, per-IP-limited chain and is asked
  // to join when they place; their legs wait in the browser and come back after sign-up.
  const reader = user === null
  const checking = user === undefined // auth still loading: call nothing yet
  const [join, setJoin] = useState(false)
  useEffect(() => {
    if (checking) return
    ;(reader ? rpc('reader_universe') : rpc('get_config').then((c) => c.universe)).then(setUniverse).catch((e) => setError(e.message))
  }, [reader, checking])

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
    if (!symbol || checking) return
    setChain(null); setError(null); setLegs([]); setDone(null); setBaseline(null); setDaysAhead(0); setIvShift(0)
    // `asked` records which request a chain answers, so a saved strategy waits for the right one.
    let live = true // a quiet retry can land after the visitor picked another stock
    builderRpc(reader ? 'reader_chain' : 'builder_chain', expiry ? { symbol, expiry } : { symbol })
      .then((c) => live && setChain({ ...c, asked: expiry })).catch((e) => live && setError(e.message))
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, expiry, checking])

  // A trade built before joining (#163): open it once, after sign-in.
  useEffect(() => {
    if (reader || checking) return
    let draft = null
    try { draft = JSON.parse(localStorage.getItem(DRAFT_KEY)); localStorage.removeItem(DRAFT_KEY) } catch { /* no storage */ }
    if (draft?.symbol && draft.legs?.length) openSaved({ name: '', expired: false, ...draft })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reader, checking])

  useEffect(() => {
    setHeld([])
    if (!adjust || !chain || chain.asked !== expiry) return
    rpc('va_get_positions').then((p) => {
      const grp = p.groups.find((x) => x.symbol === chain.symbol && x.expiry === chain.expiry)
      if (grp) setHeld(heldLegs(chain, grp))
      else setNotice(`No open ${chain.symbol} position for ${shortDate(chain.expiry)}: build a new strategy instead.`)
    }).catch((e) => setNotice(e.message))
  }, [adjust, chain, expiry, heldTick])

  useEffect(() => {
    setLevels(null)
    if (!symbol || checking) return
    let live = true
    builderRpc(reader ? 'reader_levels' : 'builder_levels', { symbol }).then((l) => live && setLevels(l)).catch(() => {})
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, checking])

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
  const adjustHeld = (h, roll) => { setLegs((ls) => netLegs(chain, [...ls, ...closeOrRoll(chain, h, roll)])); setDone(null) }
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
    if (!chain || !legs.length || reader) return undefined
    debounce.current = setTimeout(() => {
      rpc('va_preview_order', { symbol: chain.symbol, expiry: chain.expiry, legs: orderLegs })
        .then(setPreview).catch((e) => setPreviewError(e.message))
    }, 400)
    return () => clearTimeout(debounce.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, chain])

  const lot = chain?.lot_size || 0
  // Everything below analyses `all`: the new legs, plus the held ones when adjusting.
  const all = useMemo(() => [...held, ...legs], [held, legs])
  const s = useMemo(() => (chain && all.length ? stats(all, chain.spot, lot) : null), [all, chain, lot])
  const net = useMemo(() => (chain && legs.length ? stats(legs, chain.spot, lot).net : 0), [legs, chain, lot])
  const iv = chain ? atmIv(chain) : 0
  const g = useMemo(() => (chain ? greeks(all, chain.spot, chain.dte, lot, iv) : null), [all, chain, lot, iv])
  const card = chain ? scorecard(chain, held.length ? resulting(chain, held, legs) : legs, levels) : []
  const failing = card.filter((r) => !r.ok).length
  const pop = useMemo(() => (chain ? probProfit(all, chain) : null), [all, chain])
  // When adjusting, the position as it is now is the baseline (margin 0: the preview gives the change).
  const before = useMemo(() => (chain && held.length
    ? { legs: held, stats: stats(held, chain.spot, lot), margin: 0, pop: probProfit(held, chain), delta: greeks(held, chain.spot, chain.dte, lot, atmIv(chain)).delta }
    : null), [held, chain, lot])
  const base = before ?? baseline
  const days = chain ? Math.min(daysAhead, chain.dte) : 0
  const points = useMemo(() => (chain && all.length ? curve(all, chain, { daysAhead: days, ivShift, baseline: base?.legs }) : []),
    [all, chain, days, ivShift, base])
  const sd = chain && iv > 0 ? sdRange(chain.spot, iv, chain.dte, 1) : null
  const nowLabel = days === 0 ? 'Today' : days >= (chain?.dte ?? 0) ? 'Expiry' : `In ${days} day${days > 1 ? 's' : ''}`
  const pnlThen = chain && all.length ? pnlOn(all, chain.spot, chain.dte, lot, chain.spot, Math.max(chain.dte - days, 0), ivShift, iv) : 0
  const margin = preview?.margin_change
  const rom = !held.length && s && margin > 0 && Number.isFinite(s.maxProfit) ? s.maxProfit / margin : null
  const pin = () => setBaseline({ legs, stats: s, margin, pop })
  const needsConfirm = (preview?.illiquid?.length || preview?.waiting?.length) > 0

  async function place() {
    if (reader) {
      try { localStorage.setItem(DRAFT_KEY, JSON.stringify({ symbol: chain.symbol, expiry: chain.expiry, legs: orderLegs })) } catch { /* no storage */ }
      setJoin(true)
      return
    }
    if (needsConfirm && !confirm) { setConfirm(true); return }
    setBusy(true); setPreviewError(null)
    try {
      setDone(await rpc('va_place_order', {
        symbol: chain.symbol, expiry: chain.expiry, legs: orderLegs,
        confirm_waiting: confirm, confirm_illiquid: confirm,
      }))
      setLegs([]); budget?.refresh?.()
      if (adjust) setHeldTick((t) => t + 1) // reload what is now held
    } catch (e) { setPreviewError(e.message) } finally { setBusy(false); setConfirm(false) }
  }


  const delta = (a, b, f) => (a == null || b == null || !Number.isFinite(a) || !Number.isFinite(b) ? '—' : `${a - b >= 0 ? '+' : '−'}${f(Math.abs(a - b))}`)

  const blocked = reader ? !legs.length : busy || !preview || !!preview.buy_rule || !preview.sufficient
  const placeLabel = busy ? 'Placing…' : confirm ? 'Place anyway' : held.length ? 'Place adjustment on virtual account' : 'Place on virtual account'
  const dockNote = reader ? 'Join free to see margin and place' : preview?.buy_rule ? 'Not allowed at your level yet'
    : preview && !preview.sufficient ? 'Not enough free margin'
      : confirm ? 'Check the note above, then press again'
        : previewError || (preview ? `Margin ${rupee(preview.margin_change)}` : 'Checking margin…')

  return (
    <div className={`builder-page${legs.length ? ' has-dock' : ''}`}>
      {join && <JoinPrompt onClose={() => setJoin(false)} />}
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
              {Object.entries(TEMPLATES).map(([k, t]) => [k, t, t.gate && user?.sell_levels?.[t.gate]])
                .sort(([, , a], [, , b]) => (a > user?.level) - (b > user?.level)) // locked last, so a phone shows what the level can trade
                .map(([k, t, unlock]) => {
                return unlock && user.level < unlock
                  ? <button key={k} className="tpl" disabled title={`Unlocks at Level ${unlock}`}><Shape d={SHAPES[k]} />{t.label} <span className="lock-tag"><Lock size={11} aria-hidden /> Level {unlock}</span></button>
                  : <button key={k} className="tpl" onClick={() => template(k)}><Shape d={SHAPES[k]} />{t.label}</button>
              })}
              <button className="tpl" onClick={() => setLegs([])}><Eraser size={16} aria-hidden />Blank</button>
            </div>
            <label className="safe-toggle small">
              <input type="checkbox" checked={safe} onChange={(e) => setSafe(e.target.checked)} />
              <ShieldCheck size={15} aria-hidden /> Rule-safe strikes: sold strikes under delta {chain.rules.delta_max_abs}{levels ? ' and clear of S/R zones' : ''}, most premium first
            </label>
            {notice && <p className="alert builder-notice" role="status"><AlertTriangle size={16} aria-hidden /> {notice}</p>}

            {held.length > 0 && (
              <section className="card builder-held" aria-label="Open position">
                <div className="card-head"><h2>Open position</h2><span className="muted small">held, priced from entry</span></div>
                <ul className="leg-list">
                  {held.map((h) => (
                    <li key={`${h.side}${h.strike}`} className={`held-leg ${h.action === 'BUY' ? 'is-buy' : 'is-sell'}`}>
                      <span className="side-pill">{h.action === 'BUY' ? 'Long' : 'Short'}</span>
                      <span className="leg-name num">{h.lots > 1 ? `${h.lots}× ` : ''}{strikeText(h.strike)} {h.side}</span>
                      <span className="leg-px num">{rupee2(h.premium)}<small>now {rupee2(h.mark)}</small></span>
                      <button type="button" className="btn small" onClick={() => adjustHeld(h, false)} aria-label={`Close ${strikeText(h.strike)} ${h.side}`}>Close</button>
                      <button type="button" className="btn small" onClick={() => adjustHeld(h, true)} aria-label={`Roll ${strikeText(h.strike)} ${h.side}`}>Roll out</button>
                    </li>
                  ))}
                </ul>
                <p className="muted small">The legs below are the adjustment. Roll out closes a leg and opens it one strike further out; change that strike in the list.</p>
              </section>
            )}

            <section className="card builder-legs" aria-label="Legs">
              <div className="card-head"><h2>{held.length ? 'Adjustment' : 'Legs'}</h2>{legs.length > 0 && <span className="muted small">{legs.length} leg{legs.length > 1 ? 's' : ''}</span>}</div>
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
            {all.length > 0 && s ? (
              <>
                {held.length > 0 && <p className="small muted">{legs.length ? 'The position after this adjustment.' : 'The position as it is now. Add legs to adjust it.'}</p>}
                <div className="b-net">
                  <span>{held.length ? 'Adjustment ' : ''}{net >= 0 ? (held.length ? 'credit' : 'Net credit') : (held.length ? 'debit' : 'Net debit')}</span>
                  <strong className="num">{rupee(Math.abs(net))}</strong>
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
                  <div><dt>Theta / day</dt><dd className="num">{signedRupee(g.theta)}</dd></div>
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
                  <p className="small">P&L at today's spot, {nowLabel.toLowerCase()}: <b className={`num ${pnlThen >= 0 ? 'pos' : 'neg'}`}>{signedRupee(pnlThen)}</b>
                    {(days || ivShift) ? <button type="button" className="link-btn" onClick={() => { setDaysAhead(0); setIvShift(0) }}>Reset</button> : null}</p>
                </div>
                <div className="baseline">
                  {base ? (
                    <>
                      <div className="card-head"><h3>{before ? 'Change from the position now' : 'Against the pinned version'}</h3>
                        {!before && <button type="button" className="btn small" onClick={() => setBaseline(null)}><PinOff size={14} aria-hidden /> Unpin</button>}</div>
                      <dl className="builder-stats">
                        {before ? (
                          <>
                            <div><dt>Max profit</dt><dd className="num">{delta(s.maxProfit, base.stats.maxProfit, rupee)}</dd></div>
                            <div><dt>Net delta</dt><dd className="num">{delta(g.delta, base.delta, (v) => num(v, 1))}</dd></div>
                          </>
                        ) : <div><dt>Net credit</dt><dd className="num">{delta(s.net, base.stats.net, rupee)}</dd></div>}
                        <div><dt>Max loss</dt><dd className="num">{delta(s.maxLoss, base.stats.maxLoss, rupee)}</dd></div>
                        <div><dt>Margin</dt><dd className="num">{delta(margin, base.margin, rupee)}</dd></div>
                        <div><dt>Probability of profit</dt><dd className="num">{delta(pop, base.pop, (v) => `${num(v * 100, 0)} pts`)}</dd></div>
                      </dl>
                    </>
                  ) : (
                    <button type="button" className="btn small" onClick={pin} disabled={!preview}>
                      <Pin size={14} aria-hidden /> Pin to compare an adjustment
                    </button>
                  )}
                </div>
                {legs.length > 0 && <div className="builder-save">
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
                </div>}
                {legs.length > 0 && <div className="builder-place">
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
                </div>}
              </>
            ) : <p className="muted">Add legs to see the payoff, margin and Greeks.</p>}
            {done && (
              <p className="pos b-done" role="status"><CheckCircle2 size={16} aria-hidden /> Order placed: {done.filled.length} filled{done.open.length ? `, ${done.open.length} waiting` : ''}. <Link to="/portfolio">See it in Portfolio</Link></p>
            )}
          </aside>

          <section className="card b-chain" aria-label="Option chain">
            <ChainTable chain={chain} legs={legs} onAdd={add} levels={levels} onExpiry={(x) => choose({ symbol, expiry: x })} />
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
