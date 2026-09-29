// Event badge: shows count/type, risky tone, details on hover and on tap (without following the
// surrounding link). Market calendar page: lists events and holidays and filters them.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 900 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { default: EventBadge } = await import('../src/components/EventBadge.jsx')
const { default: MarketCalendar } = await import('../src/pages/MarketCalendar.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 50)) })

const ev = [
  { symbol: 'SBIN', date: '2026-10-14', type: 'results', purpose: 'Financial Results', days_away: 15, risky: true },
  { symbol: 'SBIN', date: '2026-12-03', type: 'split', purpose: 'Face value split', days_away: 65, risky: false },
]
document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
const root = createRoot(document.getElementById('r'))

// ---- badge
let followed = 0
await act(async () => root.render(h('a', { href: '#x', onClick: () => { followed++ } }, h(EventBadge, { events: ev }))))
const btn = document.querySelector('.ev-badge')
check('badge shows count', btn?.textContent === '2', btn?.textContent)
check('risky tone', btn.classList.contains('risky'))
check('aria label names the next event', btn.getAttribute('aria-label').includes('Results in 15 days'), btn.getAttribute('aria-label'))
check('no tooltip yet', !document.querySelector('[role="tooltip"]'))
await act(async () => { document.querySelector('.ev-wrap').dispatchEvent(new MouseEvent('mouseover', { bubbles: true })) })
check('hover shows details', document.querySelector('[role="tooltip"]')?.textContent.includes('Face value split'), document.querySelector('[role="tooltip"]')?.textContent)
await act(async () => { document.querySelector('.ev-wrap').dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body })) })
check('leave hides', !document.querySelector('[role="tooltip"]'))
await act(async () => { btn.click() })
check('tap toggles details', !!document.querySelector('[role="tooltip"]'))
check('tap does not follow the row link', followed === 0, followed)
await act(async () => root.render(h(EventBadge, { events: [] })))
check('no events -> nothing', !document.querySelector('.ev-badge'))
await act(async () => root.render(h(EventBadge, { events: [ev[1]] })))
check('single event shows its type', document.querySelector('.ev-badge').textContent === 'Split' && !document.querySelector('.ev-badge').classList.contains('risky'))

// ---- calendar page
const payload = {
  today: '2026-09-29', fetched_at: 1, errors: [],
  holidays: [{ date: '2026-10-02', day: 'Friday', description: 'Gandhi Jayanti' }],
  events: [...ev, { symbol: 'INFY', date: '2026-10-24', type: 'dividend', purpose: 'Interim Dividend', days_away: 25, risky: true }],
}
globalThis.fetch = async (_u, opts) => {
  const { id, method } = JSON.parse(opts.body)
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result: method === 'get_market_calendar' ? payload : null }) }
}
await act(async () => root.render(h(MemoryRouter, null, h(MarketCalendar))))
await settle()
const rows = () => [...document.querySelectorAll('[aria-label="Corporate events"] li')]
check('lists events', rows().length === 3, rows().length)
check('lists holidays', document.querySelector('[aria-label="Trading holidays"]')?.textContent.includes('Gandhi Jayanti'))
check('risky rows marked', rows().filter((li) => li.classList.contains('risky')).length === 2)
const pick = async (label, value) => act(async () => {
  const sel = document.querySelector(`select[aria-label="${label}"]`)
  sel.value = value
  sel.dispatchEvent(new Event('change', { bubbles: true }))
})
await pick('Stock', 'INFY')
check('stock filter', rows().length === 1 && rows()[0].textContent.includes('INFY'), rows().length)
await pick('Stock', 'all')
await pick('Event type', 'results')
check('type filter', rows().length === 1 && rows()[0].textContent.includes('Results'), rows().length)
await pick('Event type', 'all')
await act(async () => { [...document.querySelectorAll('[aria-label="Date range"] button')].find((b) => b.textContent === '30d').click() })
check('30-day range drops the December split', rows().length === 2, rows().length)

await act(async () => root.unmount())
process.exit(ok ? 0 : 1)
