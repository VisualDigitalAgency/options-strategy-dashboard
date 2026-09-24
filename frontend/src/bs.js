// Black-Scholes pricing for the strategy lab. Mirrors engine/greeks_sr.py so numbers match the backend.
export const RISK_FREE = 0.065

const erf = (x) => {
  // Abramowitz-Stegun 7.1.26, max error 1.5e-7
  const s = Math.sign(x)
  const a = Math.abs(x)
  const t = 1 / (1 + 0.3275911 * a)
  const y = 1 - ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-a * a)
  return s * y
}
export const normCdf = (x) => 0.5 * (1 + erf(x / Math.SQRT2))

export const intrinsic = (side, spot, strike) => (side === 'CE' ? Math.max(0, spot - strike) : Math.max(0, strike - spot))

/** Option price per share. ivPct is IV in percent (NSE convention), days is calendar days to expiry. */
export function bsPrice(side, spot, strike, days, ivPct, r = RISK_FREE) {
  if (days <= 0 || ivPct <= 0) return intrinsic(side, spot, strike)
  const t = days / 365
  const v = ivPct / 100
  const d1 = (Math.log(spot / strike) + (r + 0.5 * v * v) * t) / (v * Math.sqrt(t))
  const d2 = d1 - v * Math.sqrt(t)
  const df = Math.exp(-r * t)
  return side === 'CE'
    ? spot * normCdf(d1) - strike * df * normCdf(d2)
    : strike * df * normCdf(-d2) - spot * normCdf(-d1)
}

export function bsDelta(side, spot, strike, days, ivPct, r = RISK_FREE) {
  if (days <= 0 || ivPct <= 0) return side === 'CE' ? (spot > strike ? 1 : 0) : spot < strike ? -1 : 0
  const t = days / 365
  const v = ivPct / 100
  const d1 = (Math.log(spot / strike) + (r + 0.5 * v * v) * t) / (v * Math.sqrt(t))
  return side === 'CE' ? normCdf(d1) : normCdf(d1) - 1
}

/**
 * Model value of a leg that matches its market premium today: the Black-Scholes time value is
 * scaled so that (spot, days-to-expiry) reprices to `premium`, then decays along the model from there.
 */
export function calibratedValue(leg, spot, dte, px, daysLeft) {
  const modelNow = bsPrice(leg.side, spot, leg.strike, dte, leg.iv)
  const tvNow = modelNow - intrinsic(leg.side, spot, leg.strike)
  const k = tvNow > 1e-6 ? Math.max(leg.premium - intrinsic(leg.side, spot, leg.strike), 0) / tvNow : 1
  const intr = intrinsic(leg.side, px, leg.strike)
  return intr + (bsPrice(leg.side, px, leg.strike, daysLeft, leg.iv) - intr) * k
}

/** Risk-neutral lognormal P(price at expiry < level). */
export function probBelow(spot, level, days, ivPct, r = RISK_FREE) {
  if (level <= 0) return 0
  if (days <= 0) return spot < level ? 1 : 0
  const t = days / 365
  const v = ivPct / 100
  const d2 = (Math.log(spot / level) + (r - 0.5 * v * v) * t) / (v * Math.sqrt(t))
  return normCdf(-d2)
}

/** Expiry P&L per share of a set of SHORT legs [{side, strike, premium}] at price px. */
export const shortPnl = (legs, px) => legs.reduce((s, l) => s + l.premium - intrinsic(l.side, px, l.strike), 0)

/** Lognormal n-standard-deviation price range by expiry: spot x e^(±n·σ·√t). */
export function sdRange(spot, ivPct, days, n = 1) {
  const s = (ivPct / 100) * Math.sqrt(Math.max(days, 1) / 365)
  return { low: spot * Math.exp(-n * s), high: spot * Math.exp(n * s), pct: (Math.exp(n * s) - 1) * 100, sigma: s }
}

/** How many standard deviations a strike sits from spot (signed, log space). */
export const sdsAway = (spot, strike, ivPct, days) =>
  Math.log(strike / spot) / ((ivPct / 100) * Math.sqrt(Math.max(days, 1) / 365))

/**
 * Risk for an undefined-risk short: the expiry loss after a 2-standard-deviation move against you,
 * using the average IV of the legs. Returns per-share loss (>= 0) and the move size.
 */
export function twoSigmaRisk(legs, spot, days, ivPct) {
  const move = 2 * (ivPct / 100) * Math.sqrt(Math.max(days, 1) / 365)
  const up = spot * Math.exp(move)
  const down = spot * Math.exp(-move)
  const loss = Math.max(0, -shortPnl(legs, up), -shortPnl(legs, down))
  return { loss, movePct: (Math.exp(move) - 1) * 100, up, down }
}
