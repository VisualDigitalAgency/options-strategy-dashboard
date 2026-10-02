// Portfolio marks (stale-LTP slippage): a leg is valued at the bid/ask mid, not a stale last trade;
// the stale LTP is flagged; "If closed now" (buy back at the ask) shows beside Unbooked; and the
// "% of premium earned" line uses the mark, so DRREDDY no longer reads -76%.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 900 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} }

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { default: Portfolio } = await import('../src/pages/Portfolio.jsx')
const { SettingsProvider } = await import('../src/settings.jsx')
const { act, createElement: h } = React

const leg = {
  id: 1, side: 'CE', strike: 1400, qty: -625, avg_price: 3.4, lot_size: 625, lots: 1, sl_mode: 'auto', sl_price: 3.4,
  sl_activates_on: '2026-10-13', sl_alert_at: null, opened_at: '2026-09-29T10:00:00', sl_status: 'waiting',
  ltp: 6.0, bid: 3.4, ask: 3.6, mark: 3.5, mark_src: 'mid', ltp_gap_pct: 68.6, pnl: -62.5, pnl_exit: -125, delta: -69.4, theta: 124,
}
const DATA = {
  account: { unrealized_pnl: -62.5, realized_pnl: 0, used_margin: 82310, available_margin: 900000, return_pct: 0 },
  groups: [{
    symbol: 'DRREDDY', expiry: '2026-11-23', dte: 55, spot: 1251.9, legs: [leg], time_exit_on: '2026-11-17',
    strategy: 'Short call', pnl: -62.5, pnl_exit: -125, net_premium: 2125, margin: { total: 82310 },
    greeks: { theta: 124, delta: -69.4, vega: 0, gamma: 0 }, error: null,
  }],
  totals: { theta: 124, delta: -69.4, pnl: -62.5, pnl_exit: -125 }, market_open: true, updated_at: '2026-09-29 10:05:00',
}
globalThis.fetch = async (_u, opts) => {
  const { method, id } = JSON.parse(opts.body)
  const result = method === 'va_get_positions' || method === 'va_refresh_positions' ? DATA
    : method === 'broker_account_summary' ? { status: 'disconnected', source: 'approx' } : []
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
const root = createRoot(document.getElementById('r'))
await act(async () => root.render(h(MemoryRouter, null, h(SettingsProvider, null, h(Portfolio)))))
await act(async () => { await new Promise((r) => setTimeout(r, 30)) })

const text = document.body.textContent
const cell = document.querySelector('td[data-label="Mark"]')
check('Mark column replaces LTP', !!cell && [...document.querySelectorAll('th')].some((t) => t.textContent === 'Mark'))
check('leg shows the mid, not the stale 6.00', cell?.textContent.includes('3.50') && !cell?.textContent.startsWith('6.00'), cell?.textContent)
check('source labelled', cell?.textContent.includes('mid'), cell?.textContent)
check('stale LTP flagged', !!cell?.querySelector('.stale-ltp[aria-label*="stale"]'))
check('bid/ask/LTP in the tooltip', cell?.title.includes('Bid 3.40') && cell?.title.includes('LTP 6.00'), cell?.title)
check('If closed now per group', text.includes('If closed now') && (text.includes('−₹125') || text.includes('-₹125')))
check('premium earned uses the mark, not -76%', !text.includes('-76%') && !text.includes('−76%'), text.match(/[-−]?\d+% of the premium/)?.[0])

// Negative theta (a long leg) reads as a loss, not profit green.
DATA.totals.theta = -40
DATA.groups[0].greeks.theta = -40
await act(async () => root.render(h(MemoryRouter, null, h(SettingsProvider, null, h(Portfolio, { key: 2 })))))
await act(async () => { await new Promise((r) => setTimeout(r, 30)) })
const theta = [...document.querySelectorAll('.stat')].find((e) => e.querySelector('.stat-label')?.textContent === 'Theta / day')?.querySelector('.stat-value')
check('negative theta: red with a minus', theta?.classList.contains('neg') && !theta.classList.contains('pos') && theta.textContent === '−₹40', theta?.className + ' ' + theta?.textContent)
check('negative theta: summary says losing', document.body.textContent.includes('losing ₹40 a day'))

const { shortDate } = await import('../src/format.js')
check('shortDate takes a timestamp', shortDate('2026-09-29T10:00:00+05:30') === shortDate('2026-09-29') && !shortDate('2026-09-29 10:00:00').includes('Invalid'), shortDate('2026-09-29T10:00:00'))

await act(async () => root.unmount())
console.log(ok ? 'ALL PASS' : 'SOME FAILED')
process.exit(ok ? 0 : 1)
