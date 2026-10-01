// Adjusting an open position in the builder: the held legs load from Portfolio's snapshot and stay
// fixed, Close and Roll out add the adjustment legs, the analysis compares after with now, and only
// the adjustment is sent as the order.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 900 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter, Route, Routes } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { default: Builder } = await import('../src/pages/Builder.jsx')
const { closeOrRoll, heldLegs, pnlOn, resulting } = await import('../src/strategy.js')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = (ms = 30) => act(async () => { await new Promise((r) => setTimeout(r, ms)) })

const strike = (k, cd, pd) => ({ strike: k, CE: { bid: 5, ask: 5.2, ltp: 5.1, iv: 20, oi: 1000, delta: cd }, PE: { bid: 4, ask: 4.2, ltp: 4.1, iv: 20, oi: 1000, delta: pd } })
const chain = {
  symbol: 'SBIN', expiry: '2026-12-29', expiries: ['2026-12-29'], spot: 1000, dte: 40, lot_size: 100,
  rows: [800, 850, 900, 950, 1000, 1050, 1100, 1150, 1200].map((k) => strike(k, Math.max(0.02, 0.5 - (k - 1000) / 500), -Math.max(0.02, 0.5 - (1000 - k) / 500))),
  events: [], rules: { min_dte: 30, delta_max_abs: 0.15, long_sl_pct: 50, time_exit_dte: 7 },
}
const group = { symbol: 'SBIN', expiry: '2026-12-29', legs: [
  { id: 1, side: 'CE', strike: 1100, qty: -100, lots: 1, avg_price: 8, mark: 5.1, iv: 20 },
  { id: 2, side: 'PE', strike: 900, qty: -100, lots: 1, avg_price: 6, mark: 4.1, iv: 20 },
] }

// 1. Maths.
const held = heldLegs(chain, group)
check('held legs: sells at the entry price, marked to today', held.length === 2 && held[0].action === 'SELL' && held[0].premium === 8 && held[0].mark === 5.1)
check('today P&L of a held leg counts from entry', Math.abs(pnlOn([held[0]], 1000, 40, 100, 1000, 40) - (8 - 5.1) * 100) < 1)
check('close: one opposite leg', JSON.stringify(closeOrRoll(chain, held[0], false)) === JSON.stringify([{ side: 'CE', strike: 1100, action: 'BUY', lots: 1 }]))
const roll = closeOrRoll(chain, held[1], true)
check('roll out: close plus the next strike further out', roll.length === 2 && roll[1].strike === 850 && roll[1].action === 'SELL', roll)
check('resulting position nets the closed leg away', resulting(chain, held, roll).map((l) => `${l.strike}${l.side}`).sort().join() === '1100CE,850PE')

// 2. Page.
const calls = []
globalThis.fetch = async (_url, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  const result = {
    auth_me: { id: 1, name: 'A', email: 'a@x', role: 'user', level: 1, features: [], prefs: {}, nickname: 'a' },
    app_info: { name: 'X', logo: null },
    get_config: { universe: ['SBIN'] },
    builder_chain: chain,
    builder_levels: { symbol: 'SBIN', pivots: {}, zones: [], zone_width_pct: 1.5 },
    va_get_positions: { groups: [group] },
    va_preview_order: { fills: [], margin_change: -2500, available_margin: 1e6, sufficient: true, notes: [], illiquid: [], waiting: [], buy_rule: null },
    va_place_order: { filled: [1, 2], open: [] },
  }[method]
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}
const root = createRoot(document.body.appendChild(document.createElement('div')))
await act(async () => root.render(h(MemoryRouter, { initialEntries: ['/builder?symbol=SBIN&expiry=2026-12-29&adjust=1'] },
  h(AuthProvider, null, h(Routes, null, h(Route, { path: '/builder', element: h(Builder) }))))))
await settle(120)
const text = () => document.body.textContent
const btn = (t) => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === t || b.getAttribute('aria-label') === t)
check('open position listed', document.querySelectorAll('.held-leg').length === 2 && text().includes('Open position'))
check('analysis shows the position now, no order button yet', text().includes('The position as it is now') && !btn('Place adjustment on virtual account'))
await act(async () => btn('Roll 900 PE').click())
await settle(500)
check('roll adds two adjustment legs', document.querySelectorAll('.builder-leg').length === 2)
check('compares after with now', text().includes('Change from the position now') && text().includes('−₹2,500'))
await act(async () => btn('Place adjustment on virtual account').click())
await settle()
const placed = calls.find((c) => c.method === 'va_place_order')
check('only the adjustment is ordered', placed?.params.legs.length === 2 && placed.params.legs.some((l) => l.strike === 900 && l.action === 'BUY')
  && placed.params.legs.some((l) => l.strike === 850 && l.action === 'SELL'), placed?.params)
check('held position reloaded after placing', calls.filter((c) => c.method === 'va_get_positions').length >= 2)

await act(async () => root.unmount())
process.exit(ok ? 0 : 1)
