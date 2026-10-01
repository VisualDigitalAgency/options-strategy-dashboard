// Strategy builder (issue #137): chain and templates, expiry stats (unlimited vs capped), rule
// warnings that never block, the server's buy-leg reason shown and the button disabled, and placing.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter, Route, Routes } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { default: Builder } = await import('../src/pages/Builder.jsx')
const { stats, TEMPLATES } = await import('../src/strategy.js')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = (ms = 30) => act(async () => { await new Promise((r) => setTimeout(r, ms)) })

// 1. Maths.
const L = (side, strike, action, premium) => ({ side, strike, action, lots: 1, premium })
let st = stats([L('CE', 1100, 'SELL', 5), L('PE', 900, 'SELL', 5)], 1000, 100)
check('short strangle: credit 1000, unlimited loss', st.net === 1000 && st.maxLoss === -Infinity && st.maxProfit === 1000, st)
check('short strangle breakevens', st.breakevens.join() === '890,1110', st.breakevens)
st = stats([L('PE', 900, 'SELL', 5), L('PE', 800, 'BUY', 2)], 1000, 100)
check('bull put spread: capped loss 9700', st.maxLoss === -9700 && st.maxProfit === 300, st)
st = stats([L('CE', 1100, 'BUY', 5)], 1000, 100)
check('long call: debit, unlimited profit, loss = premium', st.net === -500 && st.maxProfit === Infinity && st.maxLoss === -500, st)

// 2. Page.
const strike = (k, cd, pd) => ({ strike: k, CE: { bid: 5, ask: 5.2, ltp: 5.1, iv: 20, oi: 1000, delta: cd }, PE: { bid: 4, ask: 4.2, ltp: 4.1, iv: 20, oi: 1000, delta: pd } })
const chain = {
  symbol: 'SBIN', expiry: '2026-12-29', expiries: ['2026-11-24', '2026-12-29'], spot: 1000, dte: 20, lot_size: 100,
  rows: [800, 850, 900, 950, 1000, 1050, 1100, 1150, 1200].map((k) => strike(k, Math.max(0.02, 0.5 - (k - 1000) / 500), -Math.max(0.02, 0.5 - (1000 - k) / 500))),
  events: [{ symbol: 'SBIN', date: '2026-11-05', type: 'results', risky: true }],
  rules: { min_dte: 30, delta_max_abs: 0.15, long_sl_pct: 50, time_exit_dte: 7 },
}
const condor = TEMPLATES.iron_condor.legs(chain)
check('iron condor: 4 legs, each buy 2 strikes beyond its sell', condor.length === 4
  && condor[1][1] - condor[0][1] === 100 && condor[2][1] - condor[3][1] === 100, condor)
const calls = []
globalThis.fetch = async (_url, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  const buys = params.legs?.filter((l) => l.action === 'BUY') ?? []
  const sells = params.legs?.filter((l) => l.action === 'SELL') ?? []
  const result = {
    auth_me: { id: 1, name: 'A', email: 'a@x', role: 'user', level: 1, features: [], prefs: {}, nickname: 'a' },
    app_info: { name: 'X', logo: null },
    get_config: { universe: ['RELIANCE', 'SBIN'] },
    builder_chain: chain,
    va_preview_order: { fills: [], margin_change: 12345, available_margin: 1e6, sufficient: true, notes: [], illiquid: [], waiting: [],
      buy_rule: buys.length && !sells.length ? 'Buying a CE on its own unlocks at Level 6.' : null },
    va_place_order: { filled: [1, 2, 3, 4], open: [] },
  }[method]
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}

const root = createRoot(document.body.appendChild(document.createElement('div')))
await act(async () => root.render(h(MemoryRouter, { initialEntries: ['/builder?symbol=SBIN'] },
  h(AuthProvider, null, h(Routes, null, h(Route, { path: '/builder', element: h(Builder) }))))))
await settle(80)
const text = () => document.body.textContent
const btn = (t) => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === t || b.getAttribute('aria-label') === t)
check('chain loaded for the stock in the URL', calls.some((c) => c.method === 'builder_chain' && c.params.symbol === 'SBIN') && !!document.querySelector('.chain-table'))
check('free account: buy rule explained up front', text().includes('until Level 6'))

await act(async () => btn('Iron condor').click())
await settle(500)
check('iron condor: 4 legs on the page', document.querySelectorAll('.builder-leg').length === 4)
check('warnings: DTE and results, never blocking', text().includes('20 days to expiry') && text().includes('Results on 2026-11-05')
  && !btn('Place on virtual account').disabled)
check('margin from the preview', text().includes('12,345'))
check('payoff chart drawn', !!document.querySelector('.chart'))

await act(async () => btn('Place on virtual account').click())
await settle()
const placed = calls.find((c) => c.method === 'va_place_order')
check('places all 4 legs on the virtual account', placed?.params.legs.length === 4 && placed.params.symbol === 'SBIN', placed?.params)
check('success links to Portfolio', text().includes('Order placed: 4 filled'))

await act(async () => btn('Buy 1200 CE').click())
await settle(500)
check('naked buy: server reason shown', text().includes('unlocks at Level 6') && btn('Place on virtual account').disabled)

await act(async () => root.unmount())
process.exit(ok ? 0 : 1)
