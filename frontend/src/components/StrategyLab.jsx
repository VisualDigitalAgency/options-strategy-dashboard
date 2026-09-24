import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, RotateCcw } from 'lucide-react'
import { rpc } from '../rpc'
import { bsDelta, calibratedValue, intrinsic, probBelow, sdRange, sdsAway, twoSigmaRisk } from '../bs'
import { addDaysIso, int, num, pct, rupee, rupee2, shortDate, signedRupee, todayIso } from '../format'
import { LabPayoff } from './Charts'

const DELTA_LIMIT = 0.15
const ZONE_PCT = 1.5

function strikesFor(chain, side, spot) {
  return chain
    .filter((r) => (side === 'CE' ? r.strikePrice > spot : r.strikePrice < spot) && r[`${side}_LTP`] > 0 && r[`${side}_IV`] > 0)
    .map((r) => ({ strike: r.strikePrice, premium: r[`${side}_LTP`], bid: r[`${side}_BID`], iv: r[`${side}_IV`], oi: r[`${side}_OI`] }))
    .sort((a, b) => a.strike - b.strike)
}

function Slider({ id, label, value, min, max, step = 1, onChange, valueText, ends }) {
  const fill = max > min ? ((value - min) / (max - min)) * 100 : 0
  return (
    <div className="lab-slider">
      <div className="lab-slider-head">
        <label htmlFor={id}>{label}</label>
        <output htmlFor={id} className="num">{valueText}</output>
      </div>
      <input
        id={id}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-valuetext={valueText}
        style={{ '--fill': `${fill}%` }}
      />
      <div className="lab-slider-ends" aria-hidden>
        <span>{ends[0]}</span>
        <span>{ends[1]}</span>
      </div>
    </div>
  )
}

export default function StrategyLab({ d, lots }) {
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
  const [margin, setMargin] = useState(null)
  useEffect(() => { setIdx(recommended); setDay(0); setTarget(d.spot) }, [recommended, d.spot])

  const legs = sides.map((s) => ({ side: s, ...lists[s][idx[s]] })).filter((l) => l.strike != null)
  const qty = (d.lot_size || 0) * Math.max(lots, 1)
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
      const intrNow = intrinsic(l.side, d.spot, l.strike)
      const intrAtTarget = intrinsic(l.side, target, l.strike)
      const delta = bsDelta(l.side, d.spot, l.strike, d.dte, l.iv)
      const zone = d.sr_zones?.find((z) => (Math.abs(l.strike - z.level) / z.level) * 100 <= ZONE_PCT)
      return {
        ...l, delta, zone, intrNow, timeNow: l.premium - intrNow, sds: sdsAway(d.spot, l.strike, l.iv, d.dte),
        valueOnDay, intrAtTarget, timeOnDay: valueOnDay - intrAtTarget,
        pnlOnDay: (l.premium - valueOnDay) * qty,
      }
    })
    const sd = { 1: sdRange(d.spot, avgIv, d.dte, 1), 2: sdRange(d.spot, avgIv, d.dte, 2) }
    return {
      credit, upper, lower, rows, sd, avgIv,
      maxProfit: credit * qty,
      pop: (pUp - pLo) * 100,
      mpp: (kUp - kLo) * 100,
      risk: risk.loss * qty,
      riskMove: risk.movePct,
      pnlOnDay: rows.reduce((s, r) => s + r.pnlOnDay, 0),
      decayedPct: (1 - rows.reduce((s, r) => s + r.valueOnDay, 0) / credit) * 100,
    }
  }, [legs, d, qty, daysLeft, target])

  const key = legs.map((l) => `${l.side}${l.strike}`).join('|')
  useEffect(() => {
    if (!legs.length) return
    setMargin(null)
    const t = setTimeout(() => {
      rpc('calc_margin', { symbol: d.symbol, expiry: d.expiry, legs: legs.map((l) => ({ side: l.side, strike: l.strike })), lots: Math.max(lots, 1) })
        .then(setMargin)
        .catch(() => setMargin({ error: true }))
    }, 350)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, lots, d.symbol, d.expiry])

  if (!m) return <p className="muted">No strikes with live prices to explore.</p>

  const changed = sides.some((s) => idx[s] !== recommended[s]) || day !== 0 || target !== d.spot
  const tStep = d.spot >= 1000 ? 5 : d.spot >= 200 ? 1 : 0.5
  const tMin = Math.floor(m.sd[2].low / tStep) * tStep
  const tMax = Math.ceil(m.sd[2].high / tStep) * tStep
  const tMove = ((target - d.spot) / d.spot) * 100
  const atSpot = Math.abs(target - d.spot) < tStep / 2
  const onDate = addDaysIso(todayIso(), day)
  const when = day === 0 ? 'today' : `on ${shortDate(onDate)}`
  const ratio = m.risk > 0 ? m.maxProfit / m.risk : null

  return (
    <div className="lab">
      <div className="lab-grid">
        <div className="lab-controls">
          <Slider
            id="lab-target"
            label="Target price"
            value={target}
            min={tMin}
            max={tMax}
            step={tStep}
            onChange={(v) => setTarget(Math.abs(v - d.spot) < tStep / 2 ? d.spot : v)}
            valueText={atSpot ? `₹${num(d.spot)}, current price` : `₹${num(target, target % 1 ? 2 : 0)}, ${tMove > 0 ? '+' : ''}${pct(tMove, 1)}`}
            ends={[`₹${num(tMin, 0)} (2σ)`, `₹${num(tMax, 0)} (2σ)`]}
          />
          {legs.map((l) => (
            <Slider
              key={l.side}
              id={`lab-${l.side}`}
              label={`${l.side === 'CE' ? 'Call' : 'Put'} strike to sell`}
              value={idx[l.side]}
              min={0}
              max={lists[l.side].length - 1}
              onChange={(v) => setIdx((s) => ({ ...s, [l.side]: v }))}
              valueText={`${l.strike} ${l.side}`}
              ends={[lists[l.side][0].strike, lists[l.side][lists[l.side].length - 1].strike]}
            />
          ))}
          <Slider
            id="lab-day"
            label="Days from today"
            value={day}
            min={0}
            max={d.dte}
            onChange={setDay}
            valueText={day === 0 ? 'Today' : `Day ${day}, ${shortDate(onDate)}, ${daysLeft} left`}
            ends={['Today', `Expiry ${shortDate(d.expiry)}`]}
          />

          <div className="lab-rules">
            {m.rows.map((r) =>
              Math.abs(r.delta) >= DELTA_LIMIT ? (
                <p key={`${r.side}d`} className="rule-warn"><AlertTriangle size={14} aria-hidden /> {r.strike} {r.side} delta {num(Math.abs(r.delta), 3)} breaks your 0.15 limit</p>
              ) : null,
            )}
            {m.rows.map((r) =>
              r.zone ? (
                <p key={`${r.side}z`} className="rule-warn"><AlertTriangle size={14} aria-hidden /> {r.strike} {r.side} sits in the {r.zone.type} zone near {Math.round(r.zone.level)}</p>
              ) : null,
            )}
          </div>

          <dl className="sd-box" aria-label="Expected move by expiry">
            <div className="sd-head"><dt>Expected move by {shortDate(d.expiry)}</dt><dd className="muted small">from IV {pct(m.avgIv)}</dd></div>
            {[1, 2].map((n) => (
              <div key={n} className="sd-row">
                <dt><b>{n}σ</b> <span className="muted">{n === 1 ? 'about 68% of outcomes' : 'about 95% of outcomes'}</span></dt>
                <dd className="num">{num(m.sd[n].low, 0)} – {num(m.sd[n].high, 0)} <span className="muted">±{pct(m.sd[n].pct, 1)}</span></dd>
              </div>
            ))}
            {m.rows.map((r) => (
              <div key={r.side} className="sd-row">
                <dt>{r.strike} {r.side}</dt>
                <dd className={`num ${Math.abs(r.sds) < 1 ? 'warn' : ''}`}>
                  {num(Math.abs(r.sds), 2)}σ away{Math.abs(r.sds) < 1 ? ', inside 1σ' : Math.abs(r.sds) >= 2 ? ', beyond 2σ' : ''}
                </dd>
              </div>
            ))}
          </dl>

          <button className="btn ghost small" onClick={() => { setIdx(recommended); setDay(0); setTarget(d.spot) }} disabled={!changed}>
            <RotateCcw size={14} aria-hidden /> Back to the recommended trade
          </button>
        </div>

        <div className="lab-chart">
          <LabPayoff legs={m.rows} spot={d.spot} target={atSpot ? null : target} dte={d.dte} qty={qty} daysLeft={daysLeft} day={day} breakevens={[m.lower, m.upper].filter(Boolean)} sd={m.sd} />
        </div>
      </div>

      <section className="ledger lab-ledger" aria-label="Lab results">
        <div className="stat">
          <span className="stat-label">Premium collected</span>
          <span className="stat-value">{rupee(m.maxProfit)}</span>
          <span className="stat-sub">{rupee2(m.credit)} a share, {int(qty)} qty</span>
        </div>
        <div className="stat">
          <span className="stat-label">POP</span>
          <span className="stat-value">{pct(m.pop)}</span>
          <span className="stat-sub">Max profit {pct(m.mpp)}</span>
        </div>
        <div className="stat">
          <span className="stat-label">Risk : reward</span>
          <span className="stat-value">{ratio ? `1 : ${ratio.toFixed(2)}` : 'No 2σ loss'}</span>
          <span className="stat-sub">{rupee(m.risk)} at a {pct(m.riskMove, 1)} move against you</span>
        </div>
        <div className="stat">
          <span className="stat-label">Breakeven</span>
          <span className="stat-value">{[m.lower, m.upper].filter(Boolean).map((v) => num(v, 0)).join(' – ')}</span>
          <span className="stat-sub">at expiry</span>
        </div>
        <div className="stat">
          <span className="stat-label">Margin</span>
          <span className="stat-value">{margin?.total ? rupee(margin.total) : margin?.error ? '—' : <span className="skeleton" style={{ width: 90, height: 26 }} />}</span>
          <span className="stat-sub">{margin?.total ? `Return ${pct((m.maxProfit / margin.total) * 100, 2)}` : 'SPAN + exposure'}</span>
        </div>
        <div className="stat">
          <span className="stat-label">P&L {when} at ₹{num(target, 0)}</span>
          <span className={`stat-value ${m.pnlOnDay > 0 ? 'pos' : m.pnlOnDay < 0 ? 'neg' : ''}`}>{signedRupee(m.pnlOnDay)}</span>
          <span className="stat-sub">{atSpot ? `${pct(Math.max(m.decayedPct, 0), 0)} of premium decayed at today's price` : `if ${d.symbol} moves ${tMove > 0 ? 'up' : 'down'} ${pct(Math.abs(tMove), 1)}`}</span>
        </div>
      </section>

      <div className="table-scroll">
        <table className="legs lab-legs">
          <thead>
            <tr>
              <th>Leg</th><th className="num">Premium</th><th className="num">Intrinsic</th><th className="num">Time value</th>
              <th className="num">Delta</th><th className="num">σ away</th><th className="num">IV</th><th className="num">Value {when}</th>
              <th className="num">Intrinsic at target</th><th className="num">Time value left</th><th className="num">P&L</th>
            </tr>
          </thead>
          <tbody>
            {m.rows.map((r) => (
              <tr key={r.side}>
                <td><span className={`leg-tag ${r.side.toLowerCase()}`}>SELL {r.side}</span> <b className="num">{r.strike}</b></td>
                <td data-label="Premium" className="num">{rupee2(r.premium)}</td>
                <td data-label="Intrinsic" className="num">{rupee2(r.intrNow)}</td>
                <td data-label="Time value" className="num">{rupee2(r.timeNow)}</td>
                <td data-label="Delta" className={`num ${Math.abs(r.delta) >= DELTA_LIMIT ? 'warn' : ''}`}>{num(r.delta, 3)}</td>
                <td data-label="σ away" className="num">{num(Math.abs(r.sds), 2)}σ</td>
                <td data-label="IV" className="num">{pct(r.iv)}</td>
                <td data-label={`Value ${when}`} className="num">{rupee2(r.valueOnDay)}</td>
                <td data-label="Intrinsic at target" className="num">{rupee2(r.intrAtTarget)}</td>
                <td data-label="Time value left" className="num">{rupee2(r.timeOnDay)}</td>
                <td data-label="P&L" className={`num ${r.pnlOnDay > 0 ? 'pos' : r.pnlOnDay < 0 ? 'neg' : ''}`}>{signedRupee(r.pnlOnDay)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted small lab-note">
        Out-of-the-money options are all time value: intrinsic is zero until the stock crosses the strike. Values on later
        days are modelled with Black-Scholes at today's IV, calibrated to today's market premium, at your target price of ₹{num(target)}.
        Real prices will also move with IV.
      </p>
    </div>
  )
}
