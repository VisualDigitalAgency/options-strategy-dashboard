const inr = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })
const inr2 = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const fixed = {}
const fmtFixed = (d) =>
  (fixed[d] ??= new Intl.NumberFormat('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d }))
/** Indian digit grouping with fixed decimals: 11990 -> 11,990.00 */
export const num = (v, d = 2) => (v == null || Number.isNaN(v) ? '—' : fmtFixed(d).format(v))
export const pnlClass = (v) => (v > 0 ? 'pos' : v < 0 ? 'neg' : '')
export const signedPct = (v, d = 2) =>
  v == null || Number.isNaN(v) ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}%`
// A negative amount reads −₹153, like signedRupee and rupeeShort, never ₹-153 (#197).
export const rupee = (v) => {
  if (v == null) return '—'
  const r = Math.round(v)
  return `${r < 0 ? '−' : ''}₹${inr.format(Math.abs(r))}`
}
export const rupee2 = (v) => (v == null ? '—' : `${v <= -0.005 ? '−' : ''}₹${inr2.format(Math.abs(v))}`)
export const int = (v) => (v == null ? '—' : inr.format(v))
export const pct = (v, d = 1) => (v == null ? '—' : `${Number(v).toFixed(d)}%`)
export const signed = (v, d = 2) => (v == null ? '—' : `${v > 0 ? '+' : ''}${Number(v).toFixed(d)}`)

export const signedRupee = (v) => {
  if (v == null) return '—'
  const r = Math.round(v)
  return `${r > 0 ? '+' : r < 0 ? '−' : ''}₹${inr.format(Math.abs(r))}`
}

export const dateTime = (s) =>
  s ? new Date(s.replace(' ', 'T')).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '—'

export const longDate = (iso) =>
  iso ? new Date(iso + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'long' }) : '—'

const isoLocal = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
export const todayIso = () => isoLocal(new Date())
export const addDaysIso = (iso, n) => {
  const d = new Date(iso + 'T00:00:00')
  d.setDate(d.getDate() + n)
  return isoLocal(d)
}

// Takes a date or a timestamp: only the day part is used.
export const shortDate = (iso) =>
  iso ? new Date(iso.slice(0, 10) + 'T00:00:00').toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) : '—'

export function suggestLots(margin, perTrade) {
  if (!margin || !perTrade) return 0
  return Math.floor(perTrade / margin)
}

/** Compact Indian notation for tight spaces: ₹9.47L, ₹1.2Cr. */
export function rupeeShort(v) {
  if (v == null) return '—'
  const a = Math.abs(v), s = v < 0 ? '−' : ''
  if (a >= 1e7) return `${s}₹${(a / 1e7).toFixed(2)}Cr`
  if (a >= 1e5) return `${s}₹${(a / 1e5).toFixed(2)}L`
  if (a >= 1e3) return `${s}₹${(a / 1e3).toFixed(1)}k`
  return `${s}₹${Math.round(a)}`
}
