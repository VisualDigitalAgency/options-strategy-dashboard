// Event badge: next event + date on one chip, risky tone, details on hover and on tap (without
// following the surrounding link), screener hides AGMs/board meetings. Market calendar page: events
// grouped by expiry cycle, held-stock tags, filter tabs, search, holidays.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 900 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { default: EventBadge } = await import('../src/components/EventBadge.jsx')
const { default: MarketCalendar } = await import('../src/pages/MarketCalendar.jsx')
const { eventNote, screenerEvents } = await import('../src/events.js')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 50)) })
const inRouter = (el) => h(MemoryRouter, null, el)

const ev = [
  { symbol: 'SBIN', date: '2026-10-14', type: 'results', purpose: 'Financial Results', days_away: 15, risky: true },
  { symbol: 'SBIN', date: '2026-12-03', type: 'split', purpose: 'Face value split from Rs 10 to Rs 5', days_away: 65, risky: false },
]
document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
const root = createRoot(document.getElementById('r'))

// ---- badge
let followed = 0
await act(async () => root.render(inRouter(h('a', { href: '#x', onClick: () => { followed++ } }, h(EventBadge, { events: ev, expiry: '2026-12-29' })))))
const btn = document.querySelector('.ev-badge')
check('badge shows next event, date and +n', /^Results\s*14 Oct\s*\+1$/.test(btn?.textContent), btn?.textContent)
check('risky tone', btn.classList.contains('risky'))
check('aria label names the next event', btn.getAttribute('aria-label').includes('Next: Results 14 Oct'), btn.getAttribute('aria-label'))
const pop = () => document.querySelector('.ev-pop')
check('closed at first', !pop() && btn.getAttribute('aria-expanded') === 'false')
await act(async () => { document.querySelector('.ev-wrap').dispatchEvent(new MouseEvent('mouseover', { bubbles: true })) })
check('hover shows details', pop()?.textContent.includes('Face value split from Rs 10 to Rs 5'), pop()?.textContent)
check('popover names the expiry', pop()?.textContent.includes('Before the 29 Dec expiry'), pop()?.textContent)
check('generic purpose not repeated', !pop()?.textContent.includes('Financial Results'), pop()?.textContent)
check('popover links to the calendar', pop()?.textContent.includes('Market calendar'))
await act(async () => { document.querySelector('.ev-wrap').dispatchEvent(new MouseEvent('mouseout', { bubbles: true, relatedTarget: document.body })) })
check('leave hides', !pop())
await act(async () => { btn.click() })
check('tap opens details', !!pop())
check('tap does not follow the row link', followed === 0, followed)
// A touch tap fires hover and focus before the click; the click must not close what they opened.
await act(async () => { btn.click() })
check('second tap closes', !pop())
await act(async () => {
  btn.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))
  document.querySelector('.ev-wrap').dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
  btn.focus()
})
await act(async () => { btn.click() })
check('touch sequence leaves it open', !!pop())
await act(async () => root.render(inRouter(h(EventBadge, { events: [] }))))
check('no events -> nothing', !document.querySelector('.ev-badge'))
await act(async () => root.render(inRouter(h(EventBadge, { events: [ev[1]] }))))
check('single neutral event: type and date, no count', document.querySelector('.ev-badge').textContent.replace(/\s/g, '') === 'Split3Dec' && !document.querySelector('.ev-badge').classList.contains('risky'), document.querySelector('.ev-badge').textContent)

// ---- helpers
const agm = { symbol: 'SBIN', date: '2026-10-20', type: 'agm', purpose: 'Annual General Meeting', days_away: 21, risky: false }
const bm = { symbol: 'SBIN', date: '2026-10-21', type: 'board_meeting', purpose: 'To consider fund raising', days_away: 22, risky: false }
check('screener hides AGMs and board meetings', screenerEvents([...ev, agm, bm]).map((e) => e.type).join() === 'results,split')
check('note keeps useful purpose', eventNote(bm) === 'To consider fund raising' && eventNote(agm) === '' && eventNote(ev[0]) === '')

// ---- calendar page
const payload = {
  today: '2026-09-29', fetched_at: 1, errors: [], expiries: ['2026-10-27', '2026-11-24'],
  holidays: [{ date: '2026-10-02', day: 'Friday', description: 'Gandhi Jayanti' }, { date: '2026-11-08', day: 'Sunday', description: 'Diwali Laxmi Pujan' }],
  events: [ev[0], { symbol: 'INFY', date: '2026-10-24', type: 'dividend', purpose: 'Interim Dividend - Rs 21', days_away: 25, risky: true }, agm, ev[1]],
}
globalThis.fetch = async (_u, opts) => {
  const { id, method } = JSON.parse(opts.body)
  const result = method === 'get_market_calendar' ? payload : method === 'va_get_positions' ? { groups: [{ symbol: 'INFY' }] } : null
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}
await act(async () => root.render(inRouter(h(MarketCalendar))))
await settle()
const cycles = () => [...document.querySelectorAll('.cal-cycle')]
const rows = () => [...document.querySelectorAll('.cal-cycle tbody tr')]
check('default shows results & dividends only', rows().length === 2, rows().length)
check('grouped under the Oct expiry', cycles().length === 1 && cycles()[0].textContent.includes('27 Oct expiry'), cycles().map((c) => c.querySelector('h2').textContent))
check('held stock tagged', rows().find((r) => r.textContent.includes('INFY'))?.querySelector('.held-chip')?.textContent === 'Held')
check('summary counts results and dividends before the next expiry', document.querySelector('.cal-session').textContent.includes('Results1 before expirySBIN'), document.querySelector('.cal-session').textContent)
check('summary: held positions hit', document.querySelector('.cal-session').textContent.includes('1 of 1 with an event'))
check('next holiday skips weekends', document.querySelector('.cal-session').textContent.includes('Gandhi Jayanti'))
const tab = (label) => act(async () => { [...document.querySelectorAll('[aria-label="Event filter"] button')].find((b) => b.textContent.startsWith(label)).click() })
await tab('All')
check('all: four events in Oct, Dec (after last expiry) groups', rows().length === 4 && cycles().length === 2 && cycles()[1].textContent.includes('After 24 Nov'), cycles().map((c) => c.querySelector('h2').textContent))
await tab('Corporate actions')
check('corporate actions tab', rows().length === 2 && rows().every((r) => !r.classList.contains('risky')), rows().length)
await tab('All')
await act(async () => {
  const input = document.querySelector('input[placeholder="Search symbol"]')
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, 'inf')
  input.dispatchEvent(new Event('input', { bubbles: true }))
})
check('search filters by symbol', rows().length === 1 && rows()[0].textContent.includes('INFY'), rows().length)
const hol = [...document.querySelectorAll('[aria-label="Trading holidays"] li')]
check('holidays listed, weekend marked', hol.length === 2 && hol[1].classList.contains('weekend') && hol[1].textContent.includes('Weekend'))

await act(async () => root.unmount())
process.exit(ok ? 0 : 1)
