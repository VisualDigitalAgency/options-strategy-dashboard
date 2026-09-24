import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react'

const MOOD_ICON = { Bullish: ArrowUpRight, Bearish: ArrowDownRight, Neutral: Minus }

export function SentimentBadge({ sentiment }) {
  if (!sentiment) return <span className="muted">—</span>
  const Icon = MOOD_ICON[sentiment.label]
  return (
    <span className={`chip mood-${sentiment.label.toLowerCase()}`} title={sentiment.signals.join('\n')}>
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
