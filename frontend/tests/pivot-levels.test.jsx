// Portfolio position card: "Price & pivot levels" loads the chart for that stock, shows all nine
// levels, switches period, and places spot / short strikes among the levels.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 900 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { default: PivotLevels } = await import('../src/components/PivotLevels.jsx')
const { act, createElement: h } = React

const lv = (p) => ({ R4: p + 280, R3: p + 200, R2: p + 120, R1: p + 80, P: p, S1: p - 40, S2: p - 120, S3: p - 160, S4: p - 200 })
const payload = {
  symbol: 'SUNPHARMA', session: '2026-09-28',
  history: Array.from({ length: 120 }, (_, i) => ({ date: `2026-0${4 + Math.floor(i / 30)}-${String((i % 28) + 1).padStart(2, '0')}`, close: 1900 + i, high: 1910 + i, low: 1890 + i })),
  pivots: {
    daily: { from: '2026-09-25', to: '2026-09-25', high: 2010, low: 1990, close: 2000, levels: lv(2000) },
    weekly: { from: '2026-09-21', to: '2026-09-25', high: 2030, low: 1970, close: 2000, levels: lv(1990) },
    monthly: { from: '2026-08-01', to: '2026-08-31', high: 2066, low: 1868, close: 1907, levels: lv(1947.03) },
  },
}
const calls = []
let fail = false
globalThis.fetch = async (_u, opts) => {
  const { method, params, id } = JSON.parse(opts.body)
  calls.push({ method, params })
  const body = fail ? { jsonrpc: '2.0', id, error: { code: -32000, message: 'No open position in SUNPHARMA' } } : { jsonrpc: '2.0', id, result: payload }
  return { status: 200, json: async () => body }
}

const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 50)) })
const text = () => document.body.textContent
let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }

const legs = [{ id: 1, side: 'CE', strike: 2200, qty: -350 }, { id: 2, side: 'PE', strike: 1800, qty: -350 }]
document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
const root = createRoot(document.getElementById('r'))
await act(async () => root.render(h(PivotLevels, { symbol: 'SUNPHARMA', spot: 2000, legs })))
await settle()

check('asks for this stock only', calls.length === 1 && calls[0].method === 'va_price_levels' && calls[0].params.symbol === 'SUNPHARMA', JSON.stringify(calls))
const cells = [...document.querySelectorAll('.pivot-grid dt')].map((e) => e.textContent)
check('all nine levels listed in order', cells.join(',') === 'R4,R3,R2,R1,P,S1,S2,S3,S4', cells.join(','))
check('monthly by default (August)', text().includes('R4') && text().includes('2,227.03') && text().includes('1,947.03'))
check('spot placed among levels', text().includes('Spot 2,000.00 is between P and R1'))
check('short strikes placed', text().includes('Short CE 2200 is between R3 and R4') && text().includes('Short PE 1800 is between S3 and S2'),
  document.querySelector('.pivot-where')?.textContent)
check('% from spot shown', text().includes('11.4%'))

const btn = (l) => [...document.querySelectorAll('.pivots-head button')].find((b) => b.textContent === l)
await act(async () => btn('Daily').click())
check('daily switch uses daily levels', text().includes('2,280.00') && btn('Daily').getAttribute('aria-checked') === 'true')
check('switching period does not refetch', calls.length === 1)
await act(async () => root.unmount())

fail = true
document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
const r2 = createRoot(document.getElementById('r'))
await act(async () => r2.render(h(PivotLevels, { symbol: 'SUNPHARMA', spot: 2000, legs })))
await settle()
check('server error shown', document.querySelector('.form-error')?.textContent === 'No open position in SUNPHARMA')
await act(async () => r2.unmount())

console.log(ok ? 'ALL PASS' : 'SOME FAILED')
process.exit(ok ? 0 : 1)
