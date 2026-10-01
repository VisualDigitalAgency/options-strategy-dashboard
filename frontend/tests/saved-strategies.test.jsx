// Saved strategies (issue #150): locked below Level 5; save sends the legs with their deltas; the
// list opens a live strategy at its exact strikes, and an expired one on the default live expiry
// with strikes matched by delta (and says so); delete.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 900 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter, Route, Routes } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { default: Builder } = await import('../src/pages/Builder.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = (ms = 60) => act(async () => { await new Promise((r) => setTimeout(r, ms)) })

const q = (d) => ({ bid: 5, ask: 5.2, ltp: 5.1, iv: 20, oi: 1000, delta: d })
// Deltas fall as strikes go further out; the live expiry's are shifted by one strike.
const chainFor = (expiry, shift) => ({
  symbol: 'SBIN', expiry, expiries: ['2026-12-29', '2027-01-26'], spot: 1000, dte: 40, lot_size: 100,
  rows: [1000, 1050, 1100, 1150, 1200, 1250].map((k, i) => ({ strike: k, CE: q(+(0.5 - 0.08 * (i - shift)).toFixed(2)), PE: q(-0.5) })),
  events: [], rules: { min_dte: 30, delta_max_abs: 0.15, long_sl_pct: 50, time_exit_dte: 7 },
})
let features = []
let list = []
const calls = []
globalThis.fetch = async (_url, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  const result = {
    auth_me: { id: 1, name: 'A', email: 'a@x', role: 'user', level: features.length ? 5 : 1, features, prefs: {}, nickname: 'a' },
    app_info: { name: 'X', logo: null },
    get_config: { universe: ['SBIN'] },
    builder_chain: params?.expiry === '2026-12-29' ? chainFor('2026-12-29', 0) : chainFor('2027-01-26', 1),
    va_preview_order: { fills: [], margin_change: 1000, available_margin: 1e6, sufficient: true, notes: [], illiquid: [], waiting: [], buy_rule: null },
    strategy_save: { id: 9, name: params?.name, replaced: false },
    strategy_list: list,
    strategy_delete: { deleted: params?.strategy_id },
  }[method]
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}
const btn = (t) => [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === t || b.getAttribute('aria-label') === t)

// Buy/Sell are hidden until the strike row is tapped (#158).
const tapTrade = async (label) => {
  if (!btn(label)) {
    const k = Number(label.split(' ')[1]).toLocaleString('en-IN')
    const th = [...document.querySelectorAll('.chain-row th.chain-k')].find((t) => t.textContent.startsWith(k))
    await act(async () => th.closest('tr').click())
  }
  await act(async () => btn(label).click())
}
const legText = () => [...document.querySelectorAll('.builder-leg .leg-name')].map((e) => e.textContent).join(' | ')

async function mount(url) {
  const root = createRoot(document.body.appendChild(document.createElement('div')))
  await act(async () => root.render(h(MemoryRouter, { initialEntries: [url] },
    h(AuthProvider, null, h(Routes, null, h(Route, { path: '/builder', element: h(Builder) }))))))
  await settle(120)
  return root
}

// 1. Locked below Level 5.
let root = await mount('/builder?symbol=SBIN&expiry=2026-12-29')
await tapTrade('Sell 1100 CE')
await settle(500)
check('locked: Save shows the Level 5 unlock', btn('Save · unlocks at Level 5')?.disabled === true)
check('locked: no list requested', !calls.some((c) => c.method === 'strategy_list'))
await act(async () => root.unmount())
document.body.replaceChildren()

// 2. Level 5: save, list, open, expired, delete.
features = ['saved_strategies']
list = [
  { id: 1, name: 'Live condor', symbol: 'SBIN', expiry: '2026-12-29', expired: false,
    legs: [{ side: 'CE', strike: 1150, action: 'SELL', lots: 2, delta: 0.1 }] },
  { id: 2, name: 'Old call', symbol: 'SBIN', expiry: '2026-09-29', expired: true,
    legs: [{ side: 'CE', strike: 1100, action: 'SELL', lots: 1, delta: 0.34 }] },
]
calls.length = 0
root = await mount('/builder?symbol=SBIN&expiry=2026-12-29')
check('list shown, expired one marked', document.querySelector('[aria-label="My strategies"]')?.textContent.includes('Expired: opens on a live expiry'))
await tapTrade('Sell 1100 CE')
await settle(500)
const input = document.querySelector('#b-save-name')
await act(async () => {
  Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(input, 'My bear call')
  input.dispatchEvent(new Event('input', { bubbles: true }))
})
await act(async () => btn('Save').click())
await settle()
const sv = calls.find((c) => c.method === 'strategy_save')?.params
check('save sends name, stock, expiry and legs with delta', sv?.name === 'My bear call' && sv.symbol === 'SBIN' && sv.expiry === '2026-12-29'
  && sv.legs.length === 1 && sv.legs[0].strike === 1100 && sv.legs[0].delta === 0.34, sv)
check('saved message', document.body.textContent.includes('Saved "My bear call"'))

await act(async () => btn('Open Live condor').click())
await settle(200)
check('live strategy opens at its exact strike and lots', legText().includes('1,150 CE') && document.querySelectorAll('.builder-leg').length === 1
  && document.querySelector('[aria-label="Sold 1,150 CE"]')?.textContent.includes('2'), legText())

await act(async () => btn('Open Old call').click())
await settle(300)
const chainCall = calls.filter((c) => c.method === 'builder_chain').at(-1)
check('expired strategy loads the default live expiry', chainCall && !chainCall.params.expiry, chainCall?.params)
// On the live chain 0.34 sits at 1150 (shifted one strike), not at the saved 1100.
check('strike matched by delta, not copied', legText().includes('1,150 CE'), legText())
check('...and the page says so', document.body.textContent.includes('which has passed') && document.body.textContent.includes('matched by delta'))

await act(async () => btn('Delete Old call').click())
await settle()
check('delete sends the id', calls.some((c) => c.method === 'strategy_delete' && c.params.strategy_id === 2))

await act(async () => root.unmount())
process.exit(ok ? 0 : 1)
