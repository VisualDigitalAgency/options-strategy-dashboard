import { bsGreeks, intrinsic } from './bs'

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

export function greeks(legs, spot, dte, lot) {
  return legs.reduce((g, l) => {
    const one = bsGreeks(l.side, spot, l.strike, Math.max(dte, 0.5), l.iv)
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
