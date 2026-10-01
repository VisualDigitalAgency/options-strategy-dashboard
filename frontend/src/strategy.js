import { bsGreeks, bsPrice, intrinsic, probBelow, sdRange } from './bs'

// Strategy builder maths (issue #137). A leg: { side: 'CE'|'PE', strike, action: 'SELL'|'BUY', lots,
// premium, iv, delta }. Signed sign: +1 for a buy, -1 for a sell. Premium is per share.

export const sign = (l) => (l.action === 'BUY' ? 1 : -1)

// Out-of-the-money strike whose |delta| is closest to `target`, `offset` strikes further out. `room`
// keeps that many strikes free beyond it, so a spread's sell and buy never land on one strike.
export function pickStrike(chain, side, target, offset = 0, room = offset) {
  const otm = chain.rows.filter((r) => r[side]?.delta != null && (side === 'CE' ? r.strike > chain.spot : r.strike < chain.spot))
  if (!otm.length) return null
  const ordered = side === 'CE' ? otm : [...otm].reverse() // nearest the money first
  let best = 0
  ordered.forEach((r, i) => {
    if (Math.abs(Math.abs(r[side].delta) - target) < Math.abs(Math.abs(ordered[best][side].delta) - target)) best = i
  })
  best = Math.max(0, Math.min(best, ordered.length - 1 - room))
  return ordered[Math.min(best + offset, ordered.length - 1)].strike
}

export function atmStrike(chain) {
  return chain.rows.reduce((b, r) => (Math.abs(r.strike - chain.spot) < Math.abs(b - chain.spot) ? r.strike : b), chain.rows[0]?.strike)
}

export const TEMPLATES = {
  short_strangle: { label: 'Short strangle', legs: (c) => [['CE', pickStrike(c, 'CE', 0.1), 'SELL'], ['PE', pickStrike(c, 'PE', 0.1), 'SELL']] },
  short_straddle: { label: 'Short straddle', legs: (c) => [['CE', atmStrike(c), 'SELL'], ['PE', atmStrike(c), 'SELL']] },
  iron_condor: {
    label: 'Iron condor',
    legs: (c) => [['CE', pickStrike(c, 'CE', 0.1, 0, 2), 'SELL'], ['CE', pickStrike(c, 'CE', 0.1, 2), 'BUY'],
      ['PE', pickStrike(c, 'PE', 0.1, 0, 2), 'SELL'], ['PE', pickStrike(c, 'PE', 0.1, 2), 'BUY']],
  },
  bull_put_spread: { label: 'Bull put spread', legs: (c) => [['PE', pickStrike(c, 'PE', 0.12, 0, 2), 'SELL'], ['PE', pickStrike(c, 'PE', 0.12, 2), 'BUY']] },
  bear_call_spread: { label: 'Bear call spread', legs: (c) => [['CE', pickStrike(c, 'CE', 0.12, 0, 2), 'SELL'], ['CE', pickStrike(c, 'CE', 0.12, 2), 'BUY']] },
}

// The price a leg trades at by default: the bid for a sell, the ask for a buy (else the last price).
export function legPrice(q, action) {
  if (!q) return 0
  const touch = action === 'BUY' ? q.ask : q.bid
  return touch > 0 ? touch : q.ltp
}

export function makeLeg(chain, side, strike, action, lots = 1) {
  const q = chain.rows.find((r) => r.strike === strike)?.[side]
  if (!q) return null
  return { side, strike, action, lots, premium: legPrice(q, action), iv: q.iv, delta: q.delta }
}

const pnlAt = (legs, px, lot) => legs.reduce((s, l) => s + sign(l) * (intrinsic(l.side, px, l.strike) - l.premium) * l.lots * lot, 0)

/** Expiry P&L stats. Beyond the highest strike the P&L moves by the net call quantity per rupee: net
 *  short calls mean an unlimited loss, net long calls an unlimited profit. Puts are capped at 0. */
export function stats(legs, spot, lot) {
  if (!legs.length) return null
  const strikes = legs.map((l) => l.strike)
  const lo = 0 // a stock can't fall below zero, so puts' worst case is at 0
  const hi = Math.max(spot * 1.5, ...strikes) + 1
  const pts = [lo, ...[...new Set(strikes)].sort((a, b) => a - b), hi].map((px) => ({ px, pnl: pnlAt(legs, px, lot) }))
  const callSlope = legs.filter((l) => l.side === 'CE').reduce((s, l) => s + sign(l) * l.lots, 0)
  const values = pts.map((p) => p.pnl)
  const breakevens = []
  for (let i = 1; i < pts.length; i++) {
    const a = pts[i - 1], b = pts[i]
    if (a.pnl === 0) breakevens.push(a.px)
    else if (Math.sign(a.pnl) !== Math.sign(b.pnl) && b.pnl !== 0) breakevens.push(a.px + ((b.px - a.px) * -a.pnl) / (b.pnl - a.pnl))
  }
  const net = legs.reduce((s, l) => s - sign(l) * l.premium * l.lots * lot, 0)
  return {
    net, // + = credit received, - = debit paid
    maxProfit: callSlope > 0 ? Infinity : Math.max(...values),
    maxLoss: callSlope < 0 ? -Infinity : Math.min(...values),
    breakevens: breakevens.map((b) => Math.round(b * 100) / 100),
  }
}

export function greeks(legs, spot, dte, lot, fallbackIv = 0) {
  return legs.reduce((g, l) => {
    const one = bsGreeks(l.side, spot, l.strike, Math.max(dte, 0.5), legIv(l, fallbackIv))
    for (const k of ['delta', 'gamma', 'theta', 'vega']) g[k] += sign(l) * one[k] * l.lots * lot
    return g
  }, { delta: 0, gamma: 0, theta: 0, vega: 0 })
}

/** The screening rules as warnings (never blocks, #137). */
export function warnings(chain, legs) {
  const out = []
  const { min_dte: minDte, delta_max_abs: maxDelta, time_exit_dte: exitDte } = chain.rules
  if (chain.dte < minDte) out.push(`${chain.dte} days to expiry: the strategy opens trades at least ${minDte} days out`)
  if (chain.dte < exitDte) out.push(`Fewer than ${exitDte} days left: the position would be closed at the next check`)
  for (const l of legs) {
    if (l.action === 'SELL' && l.delta != null && Math.abs(l.delta) >= maxDelta) {
      out.push(`Sold ${l.strike} ${l.side} has delta ${Math.abs(l.delta).toFixed(2)}, above the ${maxDelta} limit`)
    }
  }
  for (const e of chain.events) out.push(`${e.type === 'results' ? 'Results' : 'Dividend'} on ${e.date}, before expiry`)
  return out
}

// One leg per strike and type (#144): signed lots are added up, so pressing S twice makes 2 lots
// and B on a sold strike takes one off (removing the leg at 0, flipping it past 0). Order is kept.
export function netLegs(chain, legs) {
  const by = new Map()
  for (const l of legs) {
    const k = `${l.side}|${l.strike}`
    by.set(k, (by.get(k) ?? 0) + sign(l) * l.lots)
  }
  return [...by].filter(([, n]) => n !== 0).map(([k, n]) => {
    const [side, strike] = k.split('|')
    return makeLeg(chain, side, Number(strike), n > 0 ? 'BUY' : 'SELL', Math.abs(n))
  }).filter(Boolean)
}

// Adds one lot of `action` on a strike (the chain's S/B and the legs' +/- all come here).
export const addLot = (chain, legs, side, strike, action) =>
  netLegs(chain, [...legs, { side, strike, action, lots: 1 }])

export const legAt = (legs, side, strike) => legs.find((l) => l.side === side && l.strike === strike)

// Saved strategies (#150): rebuild a saved strategy's legs on `chain`. Same expiry: the exact
// strikes at today's prices. Expired: each leg moves to the strike whose |delta| is closest to the
// one it had when saved (or the nearest strike if no delta was kept).
export function restoreLegs(chain, saved, moveByDelta) {
  const legs = saved.legs.map((l) => {
    let strike = l.strike
    if (moveByDelta) {
      const rows = chain.rows.filter((r) => r[l.side])
      const score = (r) => (l.delta != null && r[l.side].delta != null
        ? Math.abs(Math.abs(r[l.side].delta) - Math.abs(l.delta)) : Math.abs(r.strike - l.strike) / 1e6)
      strike = rows.reduce((b, r) => (!b || score(r) < score(b) ? r : b), null)?.strike ?? l.strike
    }
    return makeLeg(chain, l.side, strike, l.action, l.lots)
  })
  return { legs: netLegs(chain, legs.filter(Boolean)), missing: legs.filter((l) => !l).length }
}

// ---- Analysis (T+N curve, probability of profit, rule scorecard, suggested strikes) ----

/** ATM implied volatility: the average of the at-the-money call and put IVs (0 if neither has one). */
export function atmIv(chain) {
  const r = chain.rows.find((x) => x.strike === atmStrike(chain))
  const ivs = [r?.CE?.iv, r?.PE?.iv].filter((v) => v > 0)
  return ivs.length ? ivs.reduce((a, b) => a + b, 0) / ivs.length : 0
}

// Thin stock strikes often quote no IV, or a junk one; those legs are priced at the ATM IV instead.
const legIv = (l, fallback) => (l.iv > 0 && l.iv < 200 ? l.iv : fallback)

/** One leg's value per share at price `px`, `daysLeft` days before expiry, with IV moved by `ivShift`
 *  points. The model's time value is scaled so today's value matches the premium paid or received. */
export function legValue(l, spot, dte, px, daysLeft, ivShift = 0, fallbackIv = 0) {
  const iv = legIv(l, fallbackIv)
  const intrNow = intrinsic(l.side, spot, l.strike)
  const tvNow = bsPrice(l.side, spot, l.strike, dte, iv) - intrNow
  const k = tvNow > 1e-6 ? Math.max(l.premium - intrNow, 0) / tvNow : 1
  const intr = intrinsic(l.side, px, l.strike)
  return intr + (bsPrice(l.side, px, l.strike, daysLeft, Math.max(iv + ivShift, 1)) - intr) * k
}

/** P&L of the strategy at price `px` with `daysLeft` days to go (0 = at expiry). */
export const pnlOn = (legs, spot, dte, lot, px, daysLeft, ivShift = 0, fallbackIv = 0) => legs.reduce(
  (s, l) => s + sign(l) * (legValue(l, spot, dte, px, daysLeft, ivShift, fallbackIv) - l.premium) * l.lots * lot, 0)

/** Points for the payoff chart: expiry P&L, P&L on the chosen day, and a baseline's expiry P&L. */
export function curve(legs, chain, { daysAhead = 0, ivShift = 0, baseline = null } = {}) {
  const { spot, dte, lot_size: lot } = chain
  const iv = atmIv(chain) || 20
  const strikes = [...legs, ...(baseline ?? [])].map((l) => l.strike)
  const band = sdRange(spot, iv, dte, 2.5)
  const lo = Math.min(band.low, ...strikes.map((k) => k * 0.97))
  const hi = Math.max(band.high, ...strikes.map((k) => k * 1.03))
  const left = Math.max(dte - daysAhead, 0)
  return Array.from({ length: 161 }, (_, i) => {
    const px = lo + ((hi - lo) * i) / 160
    const pnl = pnlAt(legs, px, lot)
    return {
      px: Math.round(px * 100) / 100, pnl, profit: Math.max(pnl, 0), loss: Math.min(pnl, 0),
      now: left > 0 ? pnlOn(legs, spot, dte, lot, px, left, ivShift, iv) : pnl,
      base: baseline ? pnlAt(baseline, px, lot) : null,
    }
  })
}

/** Probability the strategy makes money at expiry, from the lognormal at ATM IV. Sums the
 *  probability of every price interval where the expiry P&L is positive. */
export function probProfit(legs, chain) {
  if (!legs.length) return null
  const { spot, dte, lot_size: lot } = chain
  const iv = atmIv(chain)
  if (!(iv > 0) || dte <= 0) return null
  const band = sdRange(spot, iv, dte, 6)
  const n = 600
  let p = 0, prev = probBelow(spot, band.low, dte, iv)
  for (let i = 1; i <= n; i++) {
    const a = band.low + ((band.high - band.low) * (i - 1)) / n
    const b = band.low + ((band.high - band.low) * i) / n
    const cdf = probBelow(spot, b, dte, iv)
    if (pnlAt(legs, (a + b) / 2, lot) > 0) p += cdf - prev
    prev = cdf
  }
  // Tails beyond 6 sigma: count them with whichever side profits there.
  if (pnlAt(legs, band.low * 0.99, lot) > 0) p += probBelow(spot, band.low, dte, iv)
  if (pnlAt(legs, band.high * 1.01, lot) > 0) p += 1 - prev
  return Math.min(1, Math.max(0, p))
}

/** The S/R zone a strike sits in (within the zone width), or null. */
export function zoneAt(levels, strike) {
  if (!levels?.zones?.length) return null
  const w = levels.zone_width_pct ?? 1.5
  return levels.zones.find((z) => (Math.abs(strike - z.level) / z.level) * 100 <= w) ?? null
}

/** The strategy's rules as a scorecard: each row passes or warns, and none of them block (#137).
 *  The warning texts are the same as `warnings`. */
export function scorecard(chain, legs, levels) {
  const { min_dte: minDte, delta_max_abs: maxDelta, time_exit_dte: exitDte } = chain.rules
  const rows = []
  const add = (label, ok, detail) => rows.push({ label, ok, detail })
  add('Days to expiry', chain.dte >= minDte && chain.dte >= exitDte,
    chain.dte < exitDte ? `Fewer than ${exitDte} days left: the position would be closed at the next check`
      : chain.dte < minDte ? `${chain.dte} days to expiry: the strategy opens trades at least ${minDte} days out`
        : `${chain.dte} days, at least ${minDte}`)
  add('Results and dividends', !chain.events.length, chain.events.length
    ? chain.events.map((e) => `${e.type === 'results' ? 'Results' : 'Dividend'} on ${e.date}, before expiry`).join('; ')
    : 'None before expiry')
  const iv = atmIv(chain)
  const sd = iv > 0 ? sdRange(chain.spot, iv, chain.dte, 1) : null
  for (const l of legs.filter((x) => x.action === 'SELL')) {
    const name = `Sold ${strikeLabel(l.strike)} ${l.side}`
    const d = l.delta == null ? null : Math.abs(l.delta)
    add(`${name}: delta`, d == null || d < maxDelta,
      d == null ? 'No delta for this strike' : d < maxDelta ? `${d.toFixed(2)}, under ${maxDelta}`
        : `Sold ${l.strike} ${l.side} has delta ${d.toFixed(2)}, above the ${maxDelta} limit`)
    if (sd) {
      const outside = l.side === 'CE' ? l.strike >= sd.high : l.strike <= sd.low
      add(`${name}: expected move`, outside, outside ? `Outside the 1σ range (${Math.round(sd.low)}–${Math.round(sd.high)})`
        : `Inside the 1σ range (${Math.round(sd.low)}–${Math.round(sd.high)}): about a 1 in 3 chance of being tested`)
    }
    if (levels) {
      const z = zoneAt(levels, l.strike)
      add(`${name}: support/resistance`, !z, z ? `In the ${z.type} zone at ${Math.round(z.level)} (${z.touches} touches): price often turns here, so the strike gets tested`
        : 'Clear of the swing support and resistance zones')
    }
  }
  return rows
}

const strikeLabel = (k) => (k % 1 ? k.toFixed(2) : String(k))

// Sold strike for a rule-safe template: the out-of-the-money strike nearest the money (so the most
// premium) whose |delta| is under the limit and that sits clear of the S/R zones. `room` keeps that
// many strikes free beyond it for the hedge.
export function safeStrike(chain, side, levels, room = 0) {
  const limit = chain.rules.delta_max_abs
  const otm = chain.rows.filter((r) => r[side]?.delta != null && (side === 'CE' ? r.strike > chain.spot : r.strike < chain.spot))
  const ordered = side === 'CE' ? otm : [...otm].reverse()
  const i = ordered.findIndex((r, j) => Math.abs(r[side].delta) < limit && !zoneAt(levels, r.strike) && j < ordered.length - room)
  return i < 0 ? { strike: null, i } : { strike: ordered[i].strike, i, ordered }
}

const hedgeFor = (pick, n = 2) => (pick.strike == null ? null : pick.ordered[pick.i + n]?.strike ?? null)

/** Templates whose sold strikes follow the rules (delta under the limit, clear of S/R zones). */
export const SAFE_TEMPLATES = {
  short_strangle: (c, lv) => [['CE', safeStrike(c, 'CE', lv).strike, 'SELL'], ['PE', safeStrike(c, 'PE', lv).strike, 'SELL']],
  iron_condor: (c, lv) => {
    const ce = safeStrike(c, 'CE', lv, 2), pe = safeStrike(c, 'PE', lv, 2)
    return [['CE', ce.strike, 'SELL'], ['CE', hedgeFor(ce), 'BUY'], ['PE', pe.strike, 'SELL'], ['PE', hedgeFor(pe), 'BUY']]
  },
  bull_put_spread: (c, lv) => { const pe = safeStrike(c, 'PE', lv, 2); return [['PE', pe.strike, 'SELL'], ['PE', hedgeFor(pe), 'BUY']] },
  bear_call_spread: (c, lv) => { const ce = safeStrike(c, 'CE', lv, 2); return [['CE', ce.strike, 'SELL'], ['CE', hedgeFor(ce), 'BUY']] },
}
