import { AlertTriangle } from 'lucide-react'

// RMS margin banner (#178): shown once margin used reaches the warning level. At the square-off
// level the worker closes positions (largest margin first) while the market is open.
export default function MarginBanner({ account: a }) {
  if (!a || !a.margin_status || a.margin_status === 'ok') return null
  const used = a.margin_used_pct == null ? 'more than your account value' : `${a.margin_used_pct}% of your account value`
  return (
    <div className={`alert margin-banner ${a.margin_status}`} role="alert">
      <AlertTriangle size={18} aria-hidden />
      <span>
        <b>{a.margin_status === 'squareoff' ? 'Margin shortfall: positions are being squared off.' : 'Margin running low.'}</b>{' '}
        Margin used is {used}. New sales are blocked at 80%, and at 90% RMS closes your largest positions,
        with square-off charges of ₹50 per order. A shortfall at the end of the day is also charged a penalty.
        Close or reduce a position to bring it down.
      </span>
    </div>
  )
}
