import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Minus, Plus, Rocket, WalletCards } from 'lucide-react'
import { rpc } from '../rpc'
import { bsGreeks, calibratedValue, intrinsic, probBelow, sdRange, sdsAway, twoSigmaRisk } from '../bs'
import { addDaysIso, int, num, pct, rupee, rupee2, shortDate, signed, signedRupee, todayIso } from '../format'
import { LabPayoff } from './Charts'
import { LegTag } from './Badges'
import OrderModal from './OrderModal'

const DELTA_LIMIT = 0.15
const ZONE_PCT = 1.5

function strikesFor(chain, side, spot) {
  return chain
    .filter((r) => (side === 'CE' ? r.strikePrice > spot : r.strikePrice < spot) && r[`${side}_LTP`] > 0 && r[`${side}_IV`] > 0)
    .map((r) => ({ strike: r.strikePrice, premium: r[`${side}_LTP`], bid: r[`${side}_BID`], iv: r[`${side}_IV`], oi: r[`${side}_OI`] }))
    .sort((a, b) => a.strike - b.strike)
}

function Stepper({ label, value, onDec, onInc, decDisabled, incDisabled, children }) {
  return (
    <div className="stepper-box" role="group" aria-label={label}>
      <button type="button" onClick={onDec} disabled={decDisabled} aria-label={`Lower ${label}`}><Minus size={14} /></button>
      {children ?? <span className="num">{value}</span>}
      <button type="button" onClick={onInc} disabled={incDisabled} aria-label={`Raise ${label}`}><Plus size={14} /></button>
    </div>
  )
}

function Range({ id, value, min, max, step, onChange, valueText }) {
  const fill = max > min ? ((value - min) / (max - min)) * 100 : 0
  return (
    <input
      id={id}
      className="lab-range"
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      aria-valuetext={valueText}
      style={{ '--fill': `${fill}%` }}
    />
  )
}

export default function StrategyLab({ d, lots: initialLots }) {
  const sides = d.legs.map((l) => l.side)
  const lists = useMemo(
    () => Object.fromEntries(sides.map((s) => [s, strikesFor(d.chain, s, d.spot)])),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [d],
  )
  const recommended = useMemo(
    () => Object.fromEntries(d.legs.map((l) => [l.side, Math.max(0, lists[l.side].findIndex((r) => r.strike === l.strike))])),
    [d, lists],
  )
  const [idx, setIdx] = useState(recommended)
  const [day, setDay] = useState(0)
  const [target, setTarget] = useState(d.spot)
  const [lots, setLots] = useState(Math.max(initialLots, 1))
  const [sdCount, setSdCount] = useState(2)
  const [tab, setTab] = useState('payoff')
  const [margin, setMargin] = useState(null)
  const [ticket, setTicket] = useState(false)
  useEffect(() => { setIdx(recommended); setDay(0); setTarget(d.spot) }, [recommended, d.spot])
  useEffect(() => setLots(Math.max(initialLots, 1)), [initialLots])

  const legs = sides.map((s) => ({ side: s, ...lists[s][idx[s]] })).filter((l) => l.strike != null)
  const qty = (d.lot_size || 0) * lots
  const daysLeft = Math.max(d.dte - day, 0)

  const m = useMemo(() => {
    if (!legs.length) return null
    const ce = legs.find((l) => l.side === 'CE')
    const pe = legs.find((l) => l.side === 'PE')
    const credit = legs.reduce((s, l) => s + l.premium, 0)
    const upper = ce ? ce.strike + credit : null
    const lower = pe ? pe.strike - credit : null
    const pUp = ce ? probBelow(d.spot, upper, d.dte, ce.iv) : 1
    const pLo = pe ? probBelow(d.spot, lower, d.dte, pe.iv) : 0
    const kUp = ce ? probBelow(d.spot, ce.strike, d.dte, ce.iv) : 1
    const kLo = pe ? probBelow(d.spot, pe.strike, d.dte, pe.iv) : 0
    const avgIv = legs.reduce((s, l) => s + l.iv, 0) / legs.length
    const risk = twoSigmaRisk(legs, d.spot, d.dte, avgIv)
    const rows = legs.map((l) => {
      const valueOnDay = calibratedValue(l, d.spot, d.dte, target, daysLeft)
      const g = bsGreeks(l.side, target, l.strike, Math.max(daysLeft, 0.5), l.iv)
      const zone = d.sr_zones?.find((z) => (Math.abs(l.strike - z.level) / z.level) * 100 <= ZONE_PCT)
      const deltaNow = bsGreeks(l.side, d.spot, l.strike, d.dte, l.iv).delta
      return {
        ...l, zone, deltaNow, g,
        intrAtTarget: intrinsic(l.side, target, l.strike),
        sds: sdsAway(d.spot, l.strike, l.iv, d.dte),
        valueOnDay,
        pnlOnDay: (l.premium - valueOnDay) * qty,
      }
    })
    // Short position Greeks = negative of long, scaled to quantity
    const net = ['delta', 'gamma', 'theta', 'vega'].reduce((o, k) => ({ ...o, [k]: -rows.reduce((s, r) => s + r.g[k], 0) * qty }), {})
    const sd = { 1: sdRange(d.spot, avgIv, d.dte, 1), 2: sdRange(d.spot, avgIv, d.dte, 2), 3: sdRange(d.spot, avgIv, d.dte, 3) }
    const type = ce && pe ? 'Short strangle' : ce ? 'Short call' : 'Short put'
    return {
      credit, upper, lower, rows, sd, avgIv, net, type,
      maxProfit: credit * qty,
      pop: (pUp - pLo) * 100,
      mpp: (kUp - kLo) * 100,
      risk: risk.loss * qty,
      riskMove: risk.movePct,
      pnlOnDay: rows.reduce((s, r) => s + r.pnlOnDay, 0),
    }
  }, [legs, d, qty, daysLeft, target])

  const key = legs.map((l) => `${l.side}${l.strike}`).join('|')
  useEffect(() => {
    if (!legs.length) return
    setMargin(null)
    const t = setTimeout(() => {
      rpc('calc_margin', { symbol: d.symbol, expiry: d.expiry, legs: legs.map((l) => ({ side: l.side, strike: l.strike })), lots })
        .then(setMargin)
        .catch(() => setMargin({ error: true }))
    }, 350)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, lots, d.symbol, d.expiry])

  if (!m) return <p className="muted">No strikes with live prices to explore.</p>

  const tStep = d.spot >= 1000 ? 5 : d.spot >= 200 ? 1 : 0.5
  const tMin = Math.floor(m.sd[2].low / tStep) * tStep
  const tMax = Math.ceil(m.sd[2].high / tStep) * tStep
  const snapTarget = (v) => {
    const c = Math.min(tMax, Math.max(tMin, v))
    return Math.abs(c - d.spot) < tStep / 2 ? d.spot : c
  }
  const tMove = ((target - d.spot) / d.spot) * 100
  const atSpot = Math.abs(target - d.spot) < tStep / 2
  const onDate = addDaysIso(todayIso(), day)
  const ratio = m.risk > 0 ? m.maxProfit / m.risk : null
  const stepStrike = (side, dir) =>
    setIdx((s) => ({ ...s, [side]: Math.min(lists[side].length - 1, Math.max(0, s[side] + dir)) }))
  const changed = sides.some((s) => idx[s] !== recommended[s])
  const warnings = [
    ...m.rows.filter((r) => Math.abs(r.deltaNow) >= DELTA_LIMIT).map((r) => `${r.strike} ${r.side} delta ${num(Math.abs(r.deltaNow), 3)} breaks your 0.15 limit`),
    ...m.rows.filter((r) => r.zone).map((r) => `${r.strike} ${r.side} sits in the ${r.zone.type} zone near ${Math.round(r.zone.level)}`),
    ...m.rows.filter((r) => Math.abs(r.sds) < 1).map((r) => `${r.strike} ${r.side} is inside the 1σ expected move`),
  ]

  // P&L table: evenly spaced prices across the 2σ range, plus spot and target
  const tableRows = (() => {
    const pts = Array.from({ length: 11 }, (_, i) => m.sd[2].low + ((m.sd[2].high - m.sd[2].low) * i) / 10)
    const all = [...pts, d.spot, ...(atSpot ? [] : [target])].map((p) => Math.round(p / tStep) * tStep)
    return [...new Set(all)].sort((a, b) => a - b).map((px) => ({
      px,
      move: ((px - d.spot) / d.spot) * 100,
      onDay: legs.reduce((s, l) => s + l.premium - calibratedValue(l, d.spot, d.dte, px, daysLeft), 0) * qty,
      expiry: legs.reduce((s, l) => s + l.premium - intrinsic(l.side, px, l.strike), 0) * qty,
      isSpot: Math.abs(px - d.spot) < tStep,
      isTarget: !atSpot && Math.abs(px - target) < tStep,
    }))
  })()

  return (
    <div className="lab">
      <div className="lab-grid">
        {/* ---------- Builder ---------- */}
        <section className="builder" aria-label="Strategy builder">
          <div className="builder-head" aria-hidden>
            <span>B/S</span><span>Expiry</span><span>Strike</span><span>Type</span><span className="num">Price</span>
          </div>
          {m.rows.map((r) => (
            <div key={r.side} className="builder-row">
              <LegTag action="SELL" side={r.side} />
              <span className="chip-box">{shortDate(d.expiry)}</span>
              <Stepper
                label={`${r.side} strike`}
                onDec={() => stepStrike(r.side, -1)}
                onInc={() => stepStrike(r.side, 1)}
                decDisabled={idx[r.side] <= 0}
                incDisabled={idx[r.side] >= lists[r.side].length - 1}
              >
                <select
                  className="strike-select num"
                  value={idx[r.side]}
                  onChange={(e) => setIdx((s) => ({ ...s, [r.side]: Number(e.target.value) }))}
                  aria-label={`${r.side} strike`}
                >
                  {lists[r.side].map((o, i) => <option key={o.strike} value={i}>{o.strike}</option>)}
                </select>
              </Stepper>
              <span className={`opt-type ${r.side.toLowerCase()}`}>{r.side}</span>
              <span className="builder-price num">
                {rupee2(r.premium)}
                <small className={Math.abs(r.deltaNow) >= DELTA_LIMIT ? 'warn' : ''}>Δ {num(Math.abs(r.deltaNow), 2)}, {num(Math.abs(r.sds), 2)}σ</small>
              </span>
            </div>
          ))}

          {warnings.length > 0 && (
            <div className="lab-rules">
              {warnings.map((w) => <p key={w} className="rule-warn"><AlertTriangle size={14} aria-hidden /> {w}</p>)}
            </div>
          )}

          <dl className="builder-sum">
            <div><dt>Net premium</dt><dd className="num pos">{rupee(m.maxProfit)}</dd></div>
            <div>
              <dt>Margin</dt>
              <dd className="num">{margin?.total ? rupee(margin.total) : margin?.error ? '—' : <span className="skeleton" style={{ width: 70, height: 16 }} />}</dd>
            </div>
            <div><dt>Return on margin</dt><dd className="num">{margin?.total ? pct((m.maxProfit / margin.total) * 100, 2) : '—'}</dd></div>
          </dl>

          <div className="builder-actions">
            <div className="lot-box">
              <span>Lots</span>
              <Stepper label="lots" value={lots} onDec={() => setLots((l) => Math.max(1, l - 1))} onInc={() => setLots((l) => l + 1)} decDisabled={lots <= 1} />
            </div>
            <button className="btn" onClick={() => setTicket(true)}>
              <WalletCards size={16} aria-hidden /> Add to virtual
            </button>
            <button className="btn primary" disabled title="Enabled once a broker API is connected">
              <Rocket size={16} aria-hidden /> Execute
            </button>
          </div>
          {changed && (
            <button className="link-btn reset-link" onClick={() => setIdx(recommended)}>Back to the recommended strikes</button>
          )}
        </section>

        {/* ---------- Simulation ---------- */}
        <section className="sim" aria-label="Payoff simulation">
          <dl className="sim-summary">
            <div><dt>Type</dt><dd>{m.type}</dd></div>
            <div><dt>Max profit</dt><dd className="num pos">{rupee(m.maxProfit)}</dd></div>
            <div><dt>Max loss</dt><dd className="neg">Unlimited</dd></div>
            <div><dt>POP</dt><dd className="num">{pct(m.pop)}</dd></div>
            <div title={`Risk is the loss at a ${pct(m.riskMove, 1)} (2σ) move against you`}>
              <dt>Risk : reward</dt><dd className="num">{ratio ? `1 : ${ratio.toFixed(2)}` : 'No 2σ loss'}</dd>
            </div>
            <div><dt>Breakeven</dt><dd className="num">{[m.lower, m.upper].filter(Boolean).map((v) => num(v, 0)).join(' – ')}</dd></div>
          </dl>

          <div className="sim-panel">
            <div className="sim-tabs">
              <div role="tablist" aria-label="Simulation view" className="tab-line">
                {[['payoff', 'Payoff'], ['table', 'P&L table'], ['greeks', 'Greeks']].map(([k, label]) => (
                  <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? 'active' : ''} onClick={() => setTab(k)}>{label}</button>
                ))}
              </div>
              <div className="sim-legend" aria-hidden>
                <span><i className="lg-expiry" /> Expiry</span>
                <span><i className="lg-target" /> {day === 0 ? 'Today' : `Target date ${shortDate(onDate)}`}</span>
              </div>
            </div>

            {tab === 'payoff' && (
              <LabPayoff
                legs={m.rows}
                spot={d.spot}
                target={atSpot ? null : target}
                dte={d.dte}
                qty={qty}
                daysLeft={daysLeft}
                day={day}
                breakevens={[m.lower, m.upper].filter(Boolean)}
                sd={m.sd}
                sdCount={sdCount}
              />
            )}

            {tab === 'table' && (
              <div className="table-scroll">
                <table className="pnl-table">
                  <thead>
                    <tr><th className="num">{d.symbol} at</th><th className="num">Move</th><th className="num">P&L {day === 0 ? 'today' : `on ${shortDate(onDate)}`}</th><th className="num">P&L at expiry</th></tr>
                  </thead>
                  <tbody>
                    {tableRows.map((r) => (
                      <tr key={r.px} className={r.isSpot ? 'is-spot' : r.isTarget ? 'is-target' : ''}>
                        <td className="num">{num(r.px, tStep < 1 ? 1 : 0)} {r.isSpot && <span className="tag">spot</span>}{r.isTarget && <span className="tag">target</span>}</td>
                        <td className="num muted">{signed(r.move, 1)}%</td>
                        <td className={`num ${r.onDay > 0 ? 'pos' : r.onDay < 0 ? 'neg' : ''}`}>{signedRupee(r.onDay)}</td>
                        <td className={`num ${r.expiry > 0 ? 'pos' : r.expiry < 0 ? 'neg' : ''}`}>{signedRupee(r.expiry)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {tab === 'greeks' && (
              <div className="table-scroll">
                <table className="pnl-table">
                  <thead>
                    <tr><th>Leg</th><th className="num">Value</th><th className="num">Intrinsic</th><th className="num">Time value</th><th className="num">Delta</th><th className="num">Gamma</th><th className="num">Theta / day</th><th className="num">Vega</th></tr>
                  </thead>
                  <tbody>
                    {m.rows.map((r) => (
                      <tr key={r.side}>
                        <td><LegTag action="SELL" side={r.side} /> <b className="num">{r.strike}</b></td>
                        <td className="num">{rupee2(r.valueOnDay)}</td>
                        <td className="num">{rupee2(r.intrAtTarget)}</td>
                        <td className="num">{rupee2(r.valueOnDay - r.intrAtTarget)}</td>
                        <td className="num">{signed(-r.g.delta * qty, 1)}</td>
                        <td className="num">{signed(-r.g.gamma * qty, 3)}</td>
                        <td className="num pos">{signedRupee(-r.g.theta * qty)}</td>
                        <td className="num">{signedRupee(-r.g.vega * qty)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="muted small lab-note">
                  At {atSpot ? "today's price" : `₹${num(target, 0)}`}{day ? ` on ${shortDate(onDate)}` : ' today'}, for {int(qty)} qty.
                  Out-of-the-money options are all time value until the stock crosses the strike.
                </p>
              </div>
            )}

            <div className="greek-strip">
              <span title="Delta: ₹ change per ₹1 move in the stock">δ <b className="num">{signed(m.net.delta, 2)}</b></span>
              <span title="Theta: ₹ earned per day from time decay">θ <b className="num pos">{signed(m.net.theta, 2)}</b></span>
              <span title="Gamma: change in delta per ₹1 move">γ <b className="num">{signed(m.net.gamma, 3)}</b></span>
              <span title="Vega: ₹ change per 1 point of IV">ν <b className="num">{signed(m.net.vega, 2)}</b></span>
              <span className="sd-control">
                Standard deviation
                <Stepper label="standard deviation lines" value={`${sdCount}σ`} onDec={() => setSdCount((n) => Math.max(1, n - 1))} onInc={() => setSdCount((n) => Math.min(3, n + 1))} decDisabled={sdCount <= 1} incDisabled={sdCount >= 3} />
              </span>
            </div>
          </div>

          <div className="sim-sliders">
            <div className="sim-slider">
              <div className="sim-slider-head">
                <label htmlFor="lab-target">{d.symbol} target</label>
                <button className="link-btn" onClick={() => setTarget(d.spot)} disabled={atSpot}>Reset</button>
                <span className={`num move ${tMove > 0 ? 'pos' : tMove < 0 ? 'neg' : 'muted'}`}>{signed(tMove, 1)}%</span>
                <Stepper
                  label="target price"
                  onDec={() => setTarget((t) => snapTarget(t - tStep))}
                  onInc={() => setTarget((t) => snapTarget(t + tStep))}
                  decDisabled={target <= tMin}
                  incDisabled={target >= tMax}
                >
                  <span className="num">{num(target, tStep < 1 ? 1 : 0)}</span>
                </Stepper>
              </div>
              <Range id="lab-target" value={target} min={tMin} max={tMax} step={tStep} onChange={(v) => setTarget(snapTarget(v))}
                valueText={atSpot ? `${num(d.spot)}, current price` : `${num(target, 0)}, ${signed(tMove, 1)}%`} />
              <div className="range-ends" aria-hidden><span>{num(tMin, 0)} (−2σ)</span><span>{num(tMax, 0)} (+2σ)</span></div>
            </div>

            <div className="sim-slider">
              <div className="sim-slider-head">
                <label htmlFor="lab-day">Target date <span className="muted">({daysLeft} day{daysLeft === 1 ? '' : 's'} to expiry)</span></label>
                <button className="link-btn" onClick={() => setDay(0)} disabled={day === 0}>Reset</button>
                <span className="chip-box num">{shortDate(onDate)}</span>
              </div>
              <Range id="lab-day" value={day} min={0} max={d.dte} step={1} onChange={setDay}
                valueText={day === 0 ? 'Today' : `Day ${day}, ${shortDate(onDate)}, ${daysLeft} days to expiry`} />
              <div className="range-ends" aria-hidden><span>Today</span><span>Expiry {shortDate(d.expiry)}</span></div>
            </div>
          </div>

          <p className={`sim-outcome ${m.pnlOnDay > 0 ? 'pos' : m.pnlOnDay < 0 ? 'neg' : ''}`}>
            {day === 0 && atSpot
              ? `Sell now for ${rupee(m.maxProfit)}. Each day ${d.symbol} holds still adds about ${rupee(Math.max(m.net.theta, 0))} of theta.`
              : `If ${d.symbol} is at ₹${num(target, 0)} ${day === 0 ? 'today' : `on ${shortDate(onDate)}`}, this position shows ${signedRupee(m.pnlOnDay)}.`}
          </p>
        </section>
      </div>

      {ticket && (
        <OrderModal
          d={{ ...d, legs: m.rows.map((r) => ({ side: r.side, strike: r.strike, premium: r.premium })) }}
          lots={lots}
          onClose={() => setTicket(false)}
        />
      )}
    </div>
  )
}
