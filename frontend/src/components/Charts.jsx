import { useMemo, useState } from 'react'
import {
  Area, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ReferenceArea, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { int, num, rupee, shortDate } from '../format'
import { calibratedValue, intrinsic, sdRange } from '../bs'

const C = {
  grid: 'var(--chart-grid)',
  axis: 'var(--text-muted)',
  up: 'var(--up)',
  down: 'var(--down)',
  primary: 'var(--text)',
  accent: 'var(--accent)',
  ce: 'var(--ce)',
  pe: 'var(--pe)',
}
const axisProps = { stroke: C.axis, tick: { fill: C.axis, fontSize: 12 }, tickLine: false, axisLine: false }

function Tip({ active, payload, label, rows }) {
  if (!active || !payload?.length) return null
  return (
    <div className="chart-tip">
      {rows(label, payload[0].payload).map(([k, v]) => (
        <div key={k}>
          <span>{k}</span>
          <b className="mono">{v}</b>
        </div>
      ))}
    </div>
  )
}

export function PayoffChart({ d, lots }) {
  const qty = (d.lot_size || 1) * Math.max(lots, 1)
  const s = d.strategy
  const ce = d.legs.find((l) => l.side === 'CE')
  const pe = d.legs.find((l) => l.side === 'PE')
  const iv = d.legs.reduce((t, l) => t + l.iv, 0) / Math.max(d.legs.length, 1)
  const sd = useMemo(() => ({ 1: sdRange(d.spot, iv, d.dte, 1), 2: sdRange(d.spot, iv, d.dte, 2) }), [d.spot, iv, d.dte])

  const points = useMemo(() => {
    const lo = Math.min(d.spot * 0.82, (s.breakeven_lower ?? d.spot) * 0.95, sd[2].low * 0.97)
    const hi = Math.max(d.spot * 1.18, (s.breakeven_upper ?? d.spot) * 1.05, sd[2].high * 1.03)
    const step = (hi - lo) / 160
    return Array.from({ length: 161 }, (_, i) => {
      const px = lo + i * step
      let pnl = s.credit_per_share
      if (ce) pnl -= Math.max(0, px - ce.strike)
      if (pe) pnl -= Math.max(0, pe.strike - px)
      const total = pnl * qty
      return { px: Math.round(px * 100) / 100, pnl: total, profit: Math.max(total, 0), loss: Math.min(total, 0) }
    })
  }, [d, s, ce, pe, qty, sd])

  return (
    <figure className="chart" aria-label={`Payoff at expiry. Max profit ${rupee(s.credit_per_share * qty)} between ${pe?.strike ?? 'any price'} and ${ce?.strike ?? 'any price'}.`}>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={points} margin={{ top: 16, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid stroke={C.grid} vertical={false} />
          <XAxis dataKey="px" type="number" domain={['dataMin', 'dataMax']} tickFormatter={(v) => Math.round(v)} {...axisProps} />
          <YAxis tickFormatter={(v) => `${v < 0 ? '-' : ''}₹${int(Math.abs(Math.round(v / 1000)))}k`} width={60} {...axisProps} />
          <Tooltip
            content={<Tip rows={(px, p) => [['Price at expiry', num(px)], ['P&L', rupee(p.pnl)]]} />}
            cursor={{ stroke: C.axis, strokeDasharray: '3 3' }}
          />
          {d.sr_zones?.map((z, i) => (
            <ReferenceArea key={i} x1={z.level * 0.985} x2={z.level * 1.015} fill={z.type === 'support' ? C.up : C.down} fillOpacity={0.07} ifOverflow="hidden" />
          ))}
          {sdLayers(sd)}
          <ReferenceLine y={0} stroke={C.axis} />
          <Area dataKey="profit" type="linear" stroke={C.up} fill={C.up} fillOpacity={0.18} strokeWidth={2} isAnimationActive={false} />
          <Area dataKey="loss" type="linear" stroke={C.down} fill={C.down} fillOpacity={0.18} strokeWidth={2} isAnimationActive={false} />
          <ReferenceLine x={d.spot} stroke={C.primary} strokeWidth={1.5} label={{ value: `Spot ${num(d.spot, 0)}`, fill: C.primary, fontSize: 12, position: 'top' }} />
          {s.breakeven_lower && <ReferenceLine x={s.breakeven_lower} stroke={C.accent} strokeDasharray="4 4" label={{ value: `BE ${num(s.breakeven_lower, 0)}`, fill: C.accent, fontSize: 12, position: 'insideBottomLeft' }} />}
          {s.breakeven_upper && <ReferenceLine x={s.breakeven_upper} stroke={C.accent} strokeDasharray="4 4" label={{ value: `BE ${num(s.breakeven_upper, 0)}`, fill: C.accent, fontSize: 12, position: 'insideBottomRight' }} />}
        </ComposedChart>
      </ResponsiveContainer>
      <figcaption className="legend-row">
        <span><i className="sw sw-up" /> Profit</span>
        <span><i className="sw sw-down" /> Loss</span>
        <span><i className="sw sw-line-primary" /> Spot</span>
        <span><i className="sw sw-dash-accent" /> Breakeven</span>
        <span><i className="sw sw-zone" /> S/R zone</span>
        <span><i className="sw sw-sd" /> 1σ {num(sd[1].low, 0)}–{num(sd[1].high, 0)}, 2σ {num(sd[2].low, 0)}–{num(sd[2].high, 0)}</span>
        <span className="muted">At expiry, {int(qty)} qty</span>
      </figcaption>
    </figure>
  )
}

/** Shaded 1σ band and dashed 2σ edges, drawn behind a payoff. */
function sdLayers(sd) {
  if (!sd) return null
  return [
    <ReferenceArea key="sd1" x1={sd[1].low} x2={sd[1].high} fill="var(--text)" fillOpacity={0.05} ifOverflow="hidden"
      label={{ value: '1σ', fill: C.axis, fontSize: 11, position: 'insideTop' }} />,
    <ReferenceLine key="sd2l" x={sd[2].low} stroke={C.axis} strokeOpacity={0.6} strokeDasharray="2 4" ifOverflow="hidden"
      label={{ value: '2σ', fill: C.axis, fontSize: 11, position: 'insideTopLeft' }} />,
    <ReferenceLine key="sd2h" x={sd[2].high} stroke={C.axis} strokeOpacity={0.6} strokeDasharray="2 4" ifOverflow="hidden"
      label={{ value: '2σ', fill: C.axis, fontSize: 11, position: 'insideTopRight' }} />,
  ]
}

function PriceBadge({ viewBox, value }) {
  if (!viewBox) return null
  const w = 150, h = 22
  const x = Math.max(4, viewBox.x - w / 2)
  return (
    <g>
      <rect x={x} y={viewBox.y - h - 4} width={w} height={h} rx={5} fill="var(--tip-bg)" stroke="var(--border-strong)" />
      <text x={x + w / 2} y={viewBox.y - 11} textAnchor="middle" fontSize={12} fontWeight={600} fill="var(--text)">{value}</text>
    </g>
  )
}

/**
 * Strategy lab payoff: expiry P&L (areas) plus the modelled P&L on the target date (brass line),
 * with ±n standard-deviation lines and a boxed current-price marker.
 */
export function LabPayoff({ legs, spot, target, dte, qty, daysLeft, day, breakevens, sd, sdCount = 2 }) {
  const edge = sd[Math.min(sdCount + 0, 3)] ?? sd[2]
  const points = useMemo(() => {
    const lo = Math.min(spot * 0.85, edge.low * 0.98, ...breakevens.map((b) => b * 0.96))
    const hi = Math.max(spot * 1.15, edge.high * 1.02, ...breakevens.map((b) => b * 1.04))
    const step = (hi - lo) / 180
    return Array.from({ length: 181 }, (_, i) => {
      const px = lo + i * step
      const exp = legs.reduce((s, l) => s + l.premium - intrinsic(l.side, px, l.strike), 0) * qty
      const onDay = legs.reduce((s, l) => s + l.premium - calibratedValue(l, spot, dte, px, daysLeft), 0) * qty
      return { px: Math.round(px * 100) / 100, pnl: exp, profit: Math.max(exp, 0), loss: Math.min(exp, 0), onDay }
    })
  }, [legs, spot, dte, qty, daysLeft, breakevens, edge])

  const sdLines = []
  for (let n = 1; n <= sdCount; n++) {
    sdLines.push(
      <ReferenceLine key={`l${n}`} x={sd[n].low} stroke={C.axis} strokeOpacity={0.55} strokeDasharray="3 4" ifOverflow="hidden"
        label={{ value: `−${n}SD`, fill: C.axis, fontSize: 11, position: 'top' }} />,
      <ReferenceLine key={`h${n}`} x={sd[n].high} stroke={C.axis} strokeOpacity={0.55} strokeDasharray="3 4" ifOverflow="hidden"
        label={{ value: `${n}SD`, fill: C.axis, fontSize: 11, position: 'top' }} />,
    )
  }

  return (
    <figure className="chart lab-payoff" aria-label={`Payoff at expiry and on day ${day}, breakevens ${breakevens.map((b) => Math.round(b)).join(' and ')}`}>
      <ResponsiveContainer width="100%" height={360}>
        <ComposedChart data={points} margin={{ top: 40, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid stroke={C.grid} vertical={false} />
          {/* Alternating shaded bands between SD lines, like a probability map */}
          {Array.from({ length: sdCount }, (_, i) => i + 1).map((n) => (
            <ReferenceArea key={`b${n}`} x1={sd[n].low} x2={sd[n].high} fill="var(--text)" fillOpacity={0.035} ifOverflow="hidden" />
          ))}
          <XAxis dataKey="px" type="number" domain={['dataMin', 'dataMax']} tickFormatter={(v) => Math.round(v)} {...axisProps} />
          <YAxis tickFormatter={(v) => `${v < 0 ? '-' : ''}₹${int(Math.abs(Math.round(v / 1000)))}k`} width={60} {...axisProps} />
          <Tooltip
            content={<Tip rows={(px, p) => [['Price', num(px)], ['P&L at expiry', rupee(p.pnl)], [day === 0 ? 'P&L today' : `P&L on day ${day}`, rupee(p.onDay)]]} />}
            cursor={{ stroke: C.axis, strokeDasharray: '3 3' }}
          />
          {sdLines}
          <ReferenceLine y={0} stroke={C.axis} />
          <Area dataKey="profit" type="linear" stroke={C.up} fill={C.up} fillOpacity={0.2} strokeWidth={2} isAnimationActive={false} />
          <Area dataKey="loss" type="linear" stroke={C.down} fill={C.down} fillOpacity={0.2} strokeWidth={2} isAnimationActive={false} />
          <Line dataKey="onDay" type="monotone" stroke={C.accent} strokeWidth={2.25} dot={false} isAnimationActive={false} />
          <ReferenceLine x={spot} stroke={C.primary} strokeWidth={1.5} label={<PriceBadge value={`Current price: ${num(spot)}`} />} />
          {target != null && (
            <ReferenceLine x={target} stroke={C.accent} strokeWidth={1.5} strokeDasharray="6 3"
              label={{ value: `Target ${num(target, 0)}`, fill: C.accent, fontSize: 12, position: 'insideBottomRight' }} />
          )}
          {breakevens.map((b) => (
            <ReferenceLine key={b} x={b} stroke="transparent" label={{ value: `BE ${Math.round(b)}`, fill: C.axis, fontSize: 11, position: 'insideBottom' }} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </figure>
  )
}

/** Payoff at expiry for any mix of long/short legs: [{side, strike, qty (signed), avg_price}]. */
export function GroupPayoff({ legs, spot, height = 240 }) {
  const points = useMemo(() => {
    const strikes = legs.map((l) => l.strike)
    const lo = Math.min(spot * 0.82, ...strikes.map((k) => k * 0.9))
    const hi = Math.max(spot * 1.18, ...strikes.map((k) => k * 1.1))
    const step = (hi - lo) / 160
    return Array.from({ length: 161 }, (_, i) => {
      const px = lo + i * step
      const pnl = legs.reduce((s, l) => {
        const intrinsic = l.side === 'CE' ? Math.max(0, px - l.strike) : Math.max(0, l.strike - px)
        return s + (intrinsic - l.avg_price) * l.qty
      }, 0)
      return { px: Math.round(px * 100) / 100, pnl, profit: Math.max(pnl, 0), loss: Math.min(pnl, 0) }
    })
  }, [legs, spot])

  const breakevens = points.slice(1).filter((p, i) => Math.sign(p.pnl) !== Math.sign(points[i].pnl)).map((p) => p.px)

  return (
    <figure className="chart" aria-label={`Payoff at expiry, breakevens ${breakevens.map((b) => Math.round(b)).join(' and ') || 'none'}`}>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={points} margin={{ top: 16, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid stroke={C.grid} vertical={false} />
          <XAxis dataKey="px" type="number" domain={['dataMin', 'dataMax']} tickFormatter={(v) => Math.round(v)} {...axisProps} />
          <YAxis tickFormatter={(v) => `${v < 0 ? '-' : ''}₹${int(Math.abs(Math.round(v / 1000)))}k`} width={60} {...axisProps} />
          <Tooltip content={<Tip rows={(px, p) => [['Price at expiry', num(px)], ['P&L', rupee(p.pnl)]]} />} cursor={{ stroke: C.axis, strokeDasharray: '3 3' }} />
          <ReferenceLine y={0} stroke={C.axis} />
          <Area dataKey="profit" type="linear" stroke={C.up} fill={C.up} fillOpacity={0.18} strokeWidth={2} isAnimationActive={false} />
          <Area dataKey="loss" type="linear" stroke={C.down} fill={C.down} fillOpacity={0.18} strokeWidth={2} isAnimationActive={false} />
          {spot && <ReferenceLine x={spot} stroke={C.primary} strokeWidth={1.5} label={{ value: `Spot ${num(spot, 0)}`, fill: C.primary, fontSize: 12, position: 'top' }} />}
          {breakevens.map((b) => (
            <ReferenceLine key={b} x={b} stroke={C.accent} strokeDasharray="4 4" label={{ value: `BE ${Math.round(b)}`, fill: C.accent, fontSize: 12, position: 'insideBottom' }} />
          ))}
        </ComposedChart>
      </ResponsiveContainer>
    </figure>
  )
}

export function PriceChart({ d }) {
  const data = useMemo(() => {
    const h = d.history ?? []
    return h.map((p, i) => {
      const avg = (n) => (i + 1 >= n ? h.slice(i + 1 - n, i + 1).reduce((s, x) => s + x.close, 0) / n : null)
      return { ...p, ma20: avg(20), ma50: avg(50) }
    })
  }, [d])
  const ce = d.legs.find((l) => l.side === 'CE')
  const pe = d.legs.find((l) => l.side === 'PE')
  const levels = [...d.sr_zones.map((z) => z.level), ce?.strike, pe?.strike, ...data.map((p) => p.close)].filter(Boolean)
  const domain = [Math.min(...levels) * 0.97, Math.max(...levels) * 1.03]

  return (
    <figure className="chart" aria-label={`Six-month price chart with ${d.sr_zones.length} support and resistance zones.`}>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={data} margin={{ top: 12, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid stroke={C.grid} vertical={false} />
          <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={48} {...axisProps} />
          <YAxis domain={domain} tickFormatter={(v) => Math.round(v)} width={56} {...axisProps} />
          <Tooltip
            content={<Tip rows={(date, p) => [['Date', shortDate(date)], ['Close', num(p.close)], ['20 DMA', num(p.ma20)], ['50 DMA', num(p.ma50)]]} />}
            cursor={{ stroke: C.axis, strokeDasharray: '3 3' }}
          />
          {d.sr_zones.map((z, i) => (
            <ReferenceArea key={i} y1={z.level * 0.985} y2={z.level * 1.015} fill={z.type === 'support' ? C.up : C.down} fillOpacity={0.12}
              label={{ value: `${z.type === 'support' ? 'S' : 'R'} ${Math.round(z.level)} · ${z.touches}x`, fill: C.axis, fontSize: 11, position: 'insideLeft' }} />
          ))}
          {ce && <ReferenceLine y={ce.strike} stroke={C.ce} strokeDasharray="5 4" label={{ value: `Short CE ${ce.strike}`, fill: C.ce, fontSize: 12, position: 'insideTopRight' }} />}
          {pe && <ReferenceLine y={pe.strike} stroke={C.pe} strokeDasharray="5 4" label={{ value: `Short PE ${pe.strike}`, fill: C.pe, fontSize: 12, position: 'insideBottomRight' }} />}
          <Line dataKey="close" stroke={C.primary} strokeWidth={1.75} dot={false} isAnimationActive={false} name="Close" />
          <Line dataKey="ma20" stroke="var(--text-muted)" strokeWidth={1.25} dot={false} isAnimationActive={false} name="20 DMA" />
          <Line dataKey="ma50" stroke="var(--text-muted)" strokeWidth={1.25} strokeDasharray="4 3" dot={false} isAnimationActive={false} name="50 DMA" />
          <Legend verticalAlign="bottom" height={28} iconType="plainline" wrapperStyle={{ fontSize: 12, color: 'var(--text-muted)' }} />
        </ComposedChart>
      </ResponsiveContainer>
    </figure>
  )
}

const OI_UP = 'var(--up)'
const OI_DOWN = 'var(--down)'

function OITip({ active, payload, d, mode, marks }) {
  if (!active || !payload?.length) return null
  const r = payload[0].payload
  const pcr = r.CE_OI ? r.PE_OI / r.CE_OI : null
  const dist = ((r.strike - d.spot) / d.spot) * 100
  const tags = [
    marks.shortCE === r.strike && 'Your short call',
    marks.shortPE === r.strike && 'Your short put',
    marks.maxPain === r.strike && 'Max pain',
    marks.topCE === r.strike && 'Highest call OI, likely resistance',
    marks.topPE === r.strike && 'Highest put OI, likely support',
  ].filter(Boolean)
  const chg = (v) => (v > 0 ? `+${int(v)}` : v < 0 ? `−${int(-v)}` : '0')
  const side = (k, label, cls) => (
    <div className={`oi-side ${cls}`}>
      <b>{label}</b>
      <dl>
        <div><dt>Open interest</dt><dd className="num">{int(r[`${k}_OI`])}</dd></div>
        <div><dt>Change today</dt><dd className={`num ${r[`${k}_OI_CHG`] > 0 ? 'pos' : r[`${k}_OI_CHG`] < 0 ? 'neg' : ''}`}>{chg(r[`${k}_OI_CHG`])}</dd></div>
        <div><dt>Last price</dt><dd className="num">{r[`${k}_LTP`] ? `₹${num(r[`${k}_LTP`])}` : '—'}</dd></div>
        <div><dt>IV</dt><dd className="num">{r[`${k}_IV`] ? `${num(r[`${k}_IV`], 1)}%` : '—'}</dd></div>
      </dl>
    </div>
  )
  return (
    <div className="chart-tip oi-tip">
      <div className="oi-tip-head">
        <span className="oi-strike num">{r.strike}</span>
        <span className="muted">{dist > 0 ? '+' : ''}{num(dist, 1)}% from spot</span>
      </div>
      {tags.length > 0 && <div className="oi-tags">{tags.map((t) => <span key={t}>{t}</span>)}</div>}
      <div className="oi-sides">
        {side('CE', 'Call (CE)', 'ce')}
        {side('PE', 'Put (PE)', 'pe')}
      </div>
      <div className="oi-foot">
        <span>Strike PCR <b className="num">{pcr != null ? num(pcr, 2) : '—'}</b></span>
        <span>{pcr == null ? 'No call OI at this strike' : pcr > 1.2 ? 'Put writers dominate' : pcr < 0.8 ? 'Call writers dominate' : 'Balanced writing'}</span>
      </div>
      {mode === 'chg' && <p className="oi-note muted">Bars show today's change in open interest.</p>}
    </div>
  )
}

export function OIChart({ d }) {
  const [mode, setMode] = useState('oi')
  const data = d.chain.map((r) => ({
    ...r,
    strike: r.strikePrice,
    CE: mode === 'oi' ? r.CE_OI : r.CE_OI_CHG,
    PE: mode === 'oi' ? r.PE_OI : r.PE_OI_CHG,
  }))
  const ce = d.legs.find((l) => l.side === 'CE')
  const pe = d.legs.find((l) => l.side === 'PE')
  const nearest = (v) => data.reduce((b, r) => (Math.abs(r.strike - v) < Math.abs(b - v) ? r.strike : b), data[0]?.strike)
  const marks = {
    shortCE: ce?.strike,
    shortPE: pe?.strike,
    maxPain: d.max_pain,
    topCE: data.reduce((b, r) => (r.CE_OI > (b?.CE_OI ?? -1) ? r : b), null)?.strike,
    topPE: data.reduce((b, r) => (r.PE_OI > (b?.PE_OI ?? -1) ? r : b), null)?.strike,
  }
  return (
    <figure className="chart">
      <div className="chart-head">
        <div className="segmented small" role="group" aria-label="OI view">
          <button className={mode === 'oi' ? 'active' : ''} aria-pressed={mode === 'oi'} onClick={() => setMode('oi')}>Open interest</button>
          <button className={mode === 'chg' ? 'active' : ''} aria-pressed={mode === 'chg'} onClick={() => setMode('chg')}>Change today</button>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} margin={{ top: 18, right: 16, bottom: 4, left: 8 }} barGap={1}>
          <CartesianGrid stroke={C.grid} vertical={false} />
          <XAxis dataKey="strike" {...axisProps} minTickGap={16} />
          <YAxis tickFormatter={(v) => int(v)} width={60} {...axisProps} />
          <Tooltip content={<OITip d={d} mode={mode} marks={marks} />} cursor={{ fill: 'var(--hover)' }} wrapperStyle={{ zIndex: 5 }} />
          {mode === 'chg' && <ReferenceLine y={0} stroke={C.axis} />}
          {data.length > 0 && (
            <ReferenceLine x={nearest(d.spot)} stroke={C.primary} strokeWidth={1.5} label={{ value: `Spot ${num(d.spot, 0)}`, fill: C.primary, fontSize: 12, position: 'top' }} />
          )}
          {ce && <ReferenceLine x={ce.strike} stroke={OI_DOWN} strokeDasharray="4 4" label={{ value: 'Short CE', fill: OI_DOWN, fontSize: 11, position: 'insideTopRight' }} />}
          {pe && <ReferenceLine x={pe.strike} stroke={OI_UP} strokeDasharray="4 4" label={{ value: 'Short PE', fill: OI_UP, fontSize: 11, position: 'insideTopLeft' }} />}
          <Bar dataKey="CE" name="Call OI (CE)" fill={OI_DOWN} radius={[2, 2, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="PE" name="Put OI (PE)" fill={OI_UP} radius={[2, 2, 0, 0]} isAnimationActive={false} />
          <Legend verticalAlign="bottom" height={28} wrapperStyle={{ fontSize: 12, color: 'var(--text-muted)' }} />
        </BarChart>
      </ResponsiveContainer>
    </figure>
  )
}
