import { num, signedPct } from '../format'

/**
 * Where the short strikes sit against spot, the 1σ expected move to expiry and nearby S/R zones,
 * on one horizontal price scale. The question every option seller asks first: how much room is there?
 */
export default function RangeStrip({ spot, legs = [], iv, dte, zones = [], labels = true }) {
  if (!spot) return <span className="muted">—</span>
  const sd = iv && dte ? spot * (iv / 100) * Math.sqrt(dte / 365) : spot * 0.05
  const far = legs.reduce((m, l) => Math.max(m, Math.abs(l.strike - spot)), 0)
  const half = Math.max(sd * 1.9, far * 1.18, spot * 0.04)
  const lo = spot - half
  const x = (v) => Math.min(100, Math.max(0, ((v - lo) / (2 * half)) * 100))
  // Nearest two zones on each side; older swing levels further out only add noise at this size.
  const near = (type) =>
    zones.filter((z) => z.type === type && Math.abs(z.level - spot) < half)
      .sort((a, b) => Math.abs(a.level - spot) - Math.abs(b.level - spot)).slice(0, 2)
  const inView = [...near('support'), ...near('resistance')]
  const pe = legs.find((l) => l.side === 'PE')
  const ce = legs.find((l) => l.side === 'CE')
  const dist = (k) => signedPct(((k - spot) / spot) * 100, 1)
  const title = [
    `Spot ${num(spot)}`,
    `1σ by expiry ${num(spot - sd, 0)} to ${num(spot + sd, 0)}`,
    ...legs.map((l) => `Short ${l.strike} ${l.side} (${dist(l.strike)})`),
    ...inView.map((z) => `${z.type === 'support' ? 'Support' : 'Resistance'} ~${num(z.level, 0)}`),
  ].join('\n')

  return (
    <span className="rstrip" title={title} role="img" aria-label={title.replaceAll('\n', ', ')}>
      <span className="rstrip-scale" aria-hidden>
        <span className="rstrip-sd" style={{ left: `${x(spot - sd)}%`, width: `${x(spot + sd) - x(spot - sd)}%` }} />
        {inView.map((z) => (
          <span
            key={z.level}
            className={`rstrip-zone ${z.type}`}
            style={{ left: `${x(z.level * 0.985)}%`, width: `${x(z.level * 1.015) - x(z.level * 0.985)}%` }}
          />
        ))}
        <span className="rstrip-spot" style={{ left: `${x(spot)}%` }} />
        {legs.map((l) => (
          <span key={l.side} className={`rstrip-strike ${l.side.toLowerCase()}`} style={{ left: `${x(l.strike)}%` }} />
        ))}
      </span>
      {labels && (
        <span className="rstrip-labels num" aria-hidden>
          <span className={pe ? 'pe' : ''}>{pe ? `${pe.strike} ${dist(pe.strike)}` : `1σ ${num(spot - sd, 0)}`}</span>
          <span className={ce ? 'ce' : ''}>{ce ? `${ce.strike} ${dist(ce.strike)}` : `${num(spot + sd, 0)}`}</span>
        </span>
      )}
    </span>
  )
}
