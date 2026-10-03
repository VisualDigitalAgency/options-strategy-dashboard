import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'

const MOOD_ICON = { Bullish: ArrowUpRight, Bearish: ArrowDownRight, Neutral: Minus }

export function SentimentBadge({ sentiment }) {
  if (!sentiment) return <span className="muted">—</span>
  const Icon = MOOD_ICON[sentiment.label]
  return (
    <span className={`mood mood-${sentiment.label.toLowerCase()}`} title={sentiment.signals.join('\n')}>
      <Icon size={14} aria-hidden />
      {sentiment.label}
    </span>
  )
}

export function ActionBadge({ action }) {
  const kind =
    action === 'SELL STRANGLE' ? 'strangle' : action?.startsWith('SELL') ? 'single' : action === 'ERROR' ? 'error' : 'skip'
  const label = { 'SELL STRANGLE': 'Strangle', 'SELL CE ONLY': 'CE only', 'SELL PE ONLY': 'PE only' }[action] ?? (action === 'ERROR' ? 'Error' : 'Skip')
  return <span className={`chip action-${kind}`}>{label}</span>
}

export function ProbMeter({ value, label }) {
  if (value == null) return <span className="muted">—</span>
  const tone = value >= 75 ? 'good' : value >= 60 ? 'ok' : 'weak'
  return (
    <span className={`meter meter-${tone}`} aria-label={`${label ?? 'Probability'} ${value}%`}>
      <span className="meter-track" aria-hidden>
        <span className="meter-fill" style={{ transform: `scaleX(${value / 100})` }} />
      </span>
      <span className="mono">{value.toFixed(1)}%</span>
    </span>
  )
}

/** Broker-style leg badge: solid B/S square plus an outlined CE/PE box. */
export function LegTag({ action, side }) {
  const buy = action === 'BUY'
  return (
    <span className="leg-badge" aria-label={`${buy ? 'Buy' : 'Sell'} ${side}`}>
      <span className={`bs ${buy ? 'b' : 's'}`} aria-hidden>{buy ? 'B' : 'S'}</span>
      <span className={`opt-type ${side.toLowerCase()}`} aria-hidden>{side}</span>
    </span>
  )
}

// Level badges (#120): Mentor from Level 7, Master from Level 9.
export function Badges({ list }) {
  return list?.map((b) => <span key={b} className={`chip badge-${b.toLowerCase()}`}>{b}</span>) ?? null
}
