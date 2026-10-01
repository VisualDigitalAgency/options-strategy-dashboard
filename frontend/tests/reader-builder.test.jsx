// Readers (#163): a signed-out visitor builds with the public chain, never calls the signed-in
// methods, and "Place" asks them to join, keeping their legs for after sign-in.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter, Route, Routes } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { default: Builder } = await import('../src/pages/Builder.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = (ms = 30) => act(async () => { await new Promise((r) => setTimeout(r, ms)) })

const strike = (k) => ({ strike: k, CE: { bid: 5, ask: 5.2, ltp: 5.1, iv: 20, oi: 1000, oi_chg: 0, pchg: 0, delta: 0.1 }, PE: { bid: 4, ask: 4.2, ltp: 4.1, iv: 20, oi: 1000, oi_chg: 0, pchg: 0, delta: -0.1 } })
const chain = {
  symbol: 'SBIN', expiry: '2026-12-29', expiries: ['2026-12-29'], spot: 1000, dte: 40, lot_size: 100,
  rows: [800, 900, 1000, 1100, 1200].map(strike), events: [],
  rules: { min_dte: 30, delta_max_abs: 0.15, long_sl_pct: 50, time_exit_dte: 7 },
  summary: { pcr: 1, max_pain: 1000, atm_strike: 1000, atm_iv: 20 },
}
const calls = []
globalThis.fetch = async (_url, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  const result = { auth_me: null, app_info: { name: 'X', logo: null, reader_pages: ['builder'] }, reader_universe: ['SBIN'],
    reader_chain: chain, reader_levels: { symbol: 'SBIN', pivots: {}, zones: [], zone_width_pct: 1.5 } }[method]
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result: result ?? null }) }
}

const root = createRoot(document.body.appendChild(document.createElement('div')))
await act(async () => root.render(h(MemoryRouter, { initialEntries: ['/builder?symbol=SBIN'] },
  h(AuthProvider, null, h(Routes, null, h(Route, { path: '/builder', element: h(Builder) }))))))
await settle(80)
const btn = (t) => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === t)

const used = new Set(calls.map((c) => c.method))
check('public chain and levels used', used.has('reader_chain') && used.has('reader_levels') && used.has('reader_universe'))
check('no signed-in methods called', !['builder_chain', 'builder_levels', 'get_config', 'strategy_list'].some((m) => used.has(m)), [...used])

await act(async () => btn('Short strangle').click())
await settle(500)
check('legs built', document.querySelectorAll('.builder-leg').length === 2)
check('no margin preview for a visitor', !used.has('va_preview_order') && !calls.some((c) => c.method === 'va_preview_order'))
await act(async () => btn('Place on virtual account').click())
const dlg = document.querySelector('[role=dialog]')
check('place opens the join prompt', !!dlg && dlg.textContent.includes('Place this trade for free') && !!dlg.querySelector('a[href="/register"]'))
check('nothing placed', !calls.some((c) => c.method === 'va_place_order'))
const draft = JSON.parse(localStorage.getItem('builder:draft') ?? 'null')
check('legs kept for after sign-in', draft?.symbol === 'SBIN' && draft.expiry === '2026-12-29' && draft.legs.length === 2, draft)

process.exit(ok ? 0 : 1)
