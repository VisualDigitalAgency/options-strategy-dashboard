import { useId } from 'react'
import { pct, shortDate } from '../format'

const DAY = 86400000
const days = (a, b) => Math.round((new Date(b) - new Date(a)) / DAY)

/** Share of time value left after `d` of `T` days if spot holds: time value scales with sqrt(time). */
export const remaining = (d, T) => Math.sqrt(Math.max(0, T - d) / T)

/**
 * Theta decay curve from entry to expiry, with the stop-loss arming day marked.
 * `captured` (0..1) plots the real share of premium already earned on an open position.
 */
export default function DecayCurve({ start, slDate, expiry, today = start, captured, compact = false }) {
  const gid = useId().replace(/:/g, '')
  const T = Math.max(days(start, expiry), 1)
  const W = 1000
  const H = compact ? 90 : 170
  const top = compact ? 8 : 14
  const h = H - top - 2
  const x = (d) => (Math.min(Math.max(d, 0), T) / T) * W
  const y = (frac) => top + (1 - frac) * h

  const pts = Array.from({ length: 61 }, (_, i) => {
    const d = (i / 60) * T
    return [x(d), y(remaining(d, T))]
  })
  const line = pts.map(([px, py], i) => `${i ? 'L' : 'M'}${px.toFixed(1)},${py.toFixed(1)}`).join(' ')
  const area = `${line} L${W},${H} L0,${H} Z`

  const dToday = days(start, today)
  const dSl = slDate ? days(start, slDate) : null
  const expectedLeft = remaining(dToday, T)
  const slLeft = dSl != null ? remaining(dSl, T) : null
  const pctX = (d) => `${(x(d) / W) * 100}%`

  return (
    <figure className={`decay ${compact ? 'decay-compact' : ''}`}>
      <div className="decay-plot">
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden>
          <defs>
            <linearGradient id={`fill-${gid}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" className="decay-stop-top" />
              <stop offset="100%" className="decay-stop-bottom" />
            </linearGradient>
            <clipPath id={`past-${gid}`}>
              <rect x="0" y="0" width={x(dToday)} height={H} />
            </clipPath>
          </defs>
          <path d={area} className="decay-area" fill={`url(#fill-${gid})`} />
          <path d={area} className="decay-area-past" clipPath={`url(#past-${gid})`} />
          {dSl != null && <line x1={x(dSl)} x2={x(dSl)} y1={0} y2={H} className="decay-sl" vectorEffect="non-scaling-stroke" />}
          <path d={line} className="decay-line" vectorEffect="non-scaling-stroke" pathLength="1" />
        </svg>
        <span className="decay-dot" style={{ left: pctX(dToday), top: `${(y(expectedLeft) / H) * 100}%` }} />
        {captured != null && (
          <span className="decay-dot actual" style={{ left: pctX(dToday), top: `${(y(1 - Math.min(Math.max(captured, 0), 1)) / H) * 100}%` }} />
        )}
      </div>

      {!compact && (
        <div className="decay-marks">
          <span style={{ left: 0 }}>
            <b>Sell {dToday === 0 ? 'today' : shortDate(today)}</b>
            <small>{T} days to expiry</small>
          </span>
          {dSl != null && (
            <span className="mid" style={{ left: pctX(dSl) }}>
              <b>Stop loss arms {shortDate(slDate)}</b>
              <small>{pct((1 - slLeft) * 100, 0)} of premium decayed</small>
            </span>
          )}
          <span className="end" style={{ left: '100%' }}>
            <b>Expiry {shortDate(expiry)}</b>
            <small>premium fully decayed</small>
          </span>
        </div>
      )}

      {compact ? (
        <figcaption className="decay-cap">
          {captured != null ? (
            <>
              Day {dToday} of {T}. <b className={captured >= 1 - expectedLeft && captured > 0 ? 'pos' : ''}>{pct(captured * 100, 0)}</b> of the premium earned so far
              {dToday > 0 ? `, against ${pct((1 - expectedLeft) * 100, 0)} expected from time decay alone.` : '. Time decay starts paying from tomorrow.'}
            </>
          ) : null}
        </figcaption>
      ) : (
        <figcaption className="decay-cap">
          If the stock holds still, an option loses about {pct((1 - (slLeft ?? expectedLeft)) * 100, 0)} of its value
          before your stop loss arms and the remaining {pct((slLeft ?? expectedLeft) * 100, 0)} in the last{' '}
          {T - (dSl ?? 0)} days. That late acceleration is what this strategy sells.
        </figcaption>
      )}
    </figure>
  )
}
