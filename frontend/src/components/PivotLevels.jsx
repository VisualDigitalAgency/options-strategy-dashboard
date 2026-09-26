import { useEffect, useMemo, useState } from 'react'
import { CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { rpc } from '../rpc'
import { num, shortDate } from '../format'

const PERIODS = [
  { value: 'daily', label: 'Daily', help: 'From the last completed session. For intraday moves.' },
  { value: 'weekly', label: 'Weekly', help: 'From the last completed week.' },
  { value: 'monthly', label: 'Monthly', help: 'From the last completed month. Suits 30+ day trades.' },
]
const ORDER = ['R4', 'R3', 'R2', 'R1', 'P', 'S1', 'S2', 'S3', 'S4']
const colour = (k) => (k === 'P' ? 'var(--accent)' : k[0] === 'R' ? 'var(--down)' : 'var(--up)')
// R1/S1 strongest, fading out to R4/S4.
const opacity = (k) => (k === 'P' ? 1 : [0.95, 0.75, 0.55, 0.4][Number(k[1]) - 1])
const axisProps = { stroke: 'var(--text-muted)', tick: { fill: 'var(--text-muted)', fontSize: 12 }, tickLine: false, axisLine: false }

/** Where a price sits among the pivots, e.g. "between R1 and R2" or "above R4". */
function band(price, lv) {
  const above = ORDER.find((k, i) => price >= lv[k] && (i === 0 || price < lv[ORDER[i - 1]]))
  if (above === 'R4') return 'above R4'
  if (!above) return 'below S4'
  const i = ORDER.indexOf(above)
  return price === lv[above] ? `at ${above}` : `between ${above} and ${ORDER[i - 1]}`
}

function Tip({ active, payload }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="chart-tip">
      <div><span>Date</span><b className="mono">{shortDate(p.date)}</b></div>
      <div><span>Close</span><b className="mono">{num(p.close)}</b></div>
      <div><span>High / low</span><b className="mono">{num(p.high)} / {num(p.low)}</b></div>
    </div>
  )
}

/** Six-month price with floor pivots (P, R1-R4, S1-S4) and the position's short strikes. */
export default function PivotLevels({ symbol, spot, legs }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [period, setPeriod] = useState('monthly')

  useEffect(() => {
    let live = true
    rpc('va_price_levels', { symbol })
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e.message))
    return () => { live = false }
  }, [symbol])

  const piv = data?.pivots[period]
  const shorts = useMemo(() => legs.filter((l) => l.qty < 0), [legs])
  const domain = useMemo(() => {
    if (!data || !piv) return ['auto', 'auto']
    const all = [...Object.values(piv.levels), ...data.history.map((h) => h.close), ...shorts.map((l) => l.strike)]
    return [Math.min(...all) * 0.985, Math.max(...all) * 1.015]
  }, [data, piv, shorts])

  if (error) return <p className="form-error" role="alert">{error}</p>
  if (!data) return <div className="skeleton" style={{ height: 340 }} aria-label="Loading price chart" />
  const now = spot ?? data.history.at(-1)?.close

  return (
    <div className="pivots">
      <div className="pivots-head">
        <div className="segmented small" role="radiogroup" aria-label="Pivot period">
          {PERIODS.map((p) => (
            <button key={p.value} type="button" role="radio" aria-checked={period === p.value} title={p.help}
              className={period === p.value ? 'active' : ''} onClick={() => setPeriod(p.value)} disabled={!data.pivots[p.value]}>
              {p.label}
            </button>
          ))}
        </div>
        {piv && (
          <span className="muted small">
            From {piv.from === piv.to ? shortDate(piv.from) : `${shortDate(piv.from)} – ${shortDate(piv.to)}`}: high {num(piv.high)},
            low {num(piv.low)}, close {num(piv.close)}
          </span>
        )}
      </div>

      <figure className="chart" aria-label={`${symbol} six-month price with ${period} pivot levels`}>
        <ResponsiveContainer width="100%" height={340}>
          <ComposedChart data={data.history} margin={{ top: 12, right: 76, bottom: 4, left: 8 }}>
            <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
            <XAxis dataKey="date" tickFormatter={shortDate} minTickGap={48} {...axisProps} />
            <YAxis domain={domain} tickFormatter={(v) => Math.round(v)} width={56} {...axisProps} />
            <Tooltip content={<Tip />} cursor={{ stroke: 'var(--text-muted)', strokeDasharray: '3 3' }} />
            {piv && ORDER.map((k) => (
              <ReferenceLine key={k} y={piv.levels[k]} stroke={colour(k)} strokeOpacity={opacity(k)} strokeWidth={k === 'P' ? 1.75 : 1.25}
                strokeDasharray={k === 'P' ? undefined : '6 4'} ifOverflow="extendDomain"
                label={{ value: `${k} ${Math.round(piv.levels[k])}`, fill: colour(k), fontSize: 11, position: 'right' }} />
            ))}
            {shorts.map((l) => (
              <ReferenceLine key={l.id} y={l.strike} stroke={l.side === 'CE' ? 'var(--ce)' : 'var(--pe)'} strokeWidth={1.5}
                label={{ value: `Short ${l.side} ${l.strike}`, fill: l.side === 'CE' ? 'var(--ce)' : 'var(--pe)', fontSize: 11,
                  position: l.side === 'CE' ? 'insideTopLeft' : 'insideBottomLeft' }} />
            ))}
            <Line dataKey="close" stroke="var(--text)" strokeWidth={1.75} dot={false} isAnimationActive={false} name="Close" />
          </ComposedChart>
        </ResponsiveContainer>
        <figcaption className="legend-row">
          <span><i className="sw sw-line-primary" /> Close</span>
          <span><i className="sw sw-dash-down" /> Resistance R1–R4</span>
          <span><i className="sw sw-line-accent" /> Pivot P</span>
          <span><i className="sw sw-dash-up" /> Support S1–S4</span>
          {shorts.some((l) => l.side === 'CE') && <span><i className="sw sw-ce" /> Short call</span>}
          {shorts.some((l) => l.side === 'PE') && <span><i className="sw sw-pe" /> Short put</span>}
        </figcaption>
      </figure>

      {piv && (
        <>
          <dl className="pivot-grid">
            {ORDER.map((k) => (
              <div key={k} className={`pv-${k[0]}`}>
                <dt>{k}</dt>
                <dd className="mono">{num(piv.levels[k])}</dd>
                {now != null && <dd className="mono muted">{((piv.levels[k] / now - 1) * 100).toFixed(1)}%</dd>}
              </div>
            ))}
          </dl>
          <p className="muted small pivot-where">
            Spot {num(now)} is {band(now, piv.levels)}.
            {shorts.map((l) => ` Short ${l.side} ${l.strike} is ${band(l.strike, piv.levels)}.`).join('')}
          </p>
        </>
      )}
    </div>
  )
}
