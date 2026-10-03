// Real account on the Portfolio page: broker positions render as the same position cards as the virtual
// account (minus app-side stop loss and Adjust), and Exit all previews real BUY LIMIT orders, shows the
// alarming confirm dialog, and sends nothing until that dialog's button is pressed.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 900 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { default: Portfolio } = await import('../src/pages/Portfolio.jsx')
const { SettingsProvider } = await import('../src/settings.jsx')
const { act, createElement: h } = React

const leg = { id: 'SBIN900PE', side: 'PE', strike: 900, qty: -100, lots: 1, lot_size: 100, avg_price: 10, mark: 5, mark_src: 'mid',
  ltp: 5, bid: 4.9, ask: 5.3, pnl: 500, pnl_exit: 470, delta: 2, opened_at: null, sl_mode: 'off', sl_price: null, sl_status: 'off' }
const GROUP = { symbol: 'SBIN', expiry: '2099-01-29', dte: 40, spot: 1000, strategy: 'Short put', pnl: 500, pnl_exit: 470, net_premium: 1000,
  margin: { span: 50000, exposure: 10000, total: 60000 }, greeks: { delta: 2, gamma: 0, theta: 3, vega: 1 }, time_exit_on: '2099-01-14',
  legs: [leg], error: null }
const PREVIEW = { confirm_token: 'tok-1', exit: true, expires_in: 60,
  legs: [{ side: 'PE', strike: 900, qty: 100, action: 'BUY', limit_price: 5.3, market_price: 5.3 }] }
const calls = []

globalThis.fetch = async (_url, opts) => {
  const { method, params, id } = JSON.parse(opts.body)
  calls.push({ method, params })
  let result = {}
  if (method === 'va_get_positions' || method === 'va_refresh_positions')
    result = { account: { unrealized_pnl: 0, realized_pnl: 0, used_margin: 0, available_margin: 1, return_pct: 0 }, groups: [], totals: { theta: 0, delta: 0 }, market_open: true }
  else if (method === 'va_get_open_orders') result = []
  else if (method === 'broker_account_summary') result = { source: 'broker', status: 'active', available_margin_total: 1e6, available_cash: 1e6, used_margin: 0,
    span: 0, exposure: 0, total_collateral: 0, collateral_liquid_used: 0, collateral_equity_used: 0, open_positions: 1, synced_at: null }
  else if (method === 'broker_get_positions') result = [{ tradingsymbol: 'SBIN900PE', quantity: -100, average_price: 10, last_price: 5, pnl: 500 }]
  else if (method === 'broker_stop_alerts') result = []
  else if (method === 'broker_position_groups') result = { groups: [GROUP], totals: {} }
  else if (method === 'broker_preview_exit_group') result = PREVIEW
  else if (method === 'broker_place_exit_group') result = { placed: [{ leg_index: 0, broker_order_id: 'o1' }] }
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}

const text = () => document.body.textContent
let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 20)) })
const btn = (label) => [...document.querySelectorAll('button')].find((b) => b.textContent.includes(label))

const root = createRoot(document.body.appendChild(document.createElement('div')))
await act(async () => root.render(h(MemoryRouter, null, h(SettingsProvider, null, h(Portfolio)))))
await settle()

check('real position shown as a position card', document.querySelector('.pos-group') && text().includes('Short put'))
check('no app-side stop loss column', !text().includes('Stop loss') || !document.querySelector('.pos-legs th')?.parentElement.textContent.includes('Stop loss'))
check('no per-leg Exit or SL buttons', !document.querySelector('.leg-actions'))
check('no Adjust link', !text().includes('Adjust'))
check('the flat broker table gives way to the cards', ![...document.querySelectorAll('h2')].some((x) => x.textContent === 'Open positions'))
check('Exit all is there', !!btn('Exit all'))

await act(async () => btn('Exit all').click())
await settle()
check('preview asked for this group', calls.some((c) => c.method === 'broker_preview_exit_group' && c.params.symbol === 'SBIN' && c.params.expiry === '2099-01-29'))
check('confirm dialog says exit with real orders', text().includes('Exit with REAL orders') && text().includes('BUY'))
check('shows the limit at the ask', text().includes('5.30'))
check('nothing placed before confirming', !calls.some((c) => c.method === 'broker_place_exit_group'))

await act(async () => btn('Cancel').click())
await settle()
check('cancel closes it and still places nothing', !text().includes('Exit with REAL orders') && !calls.some((c) => c.method === 'broker_place_exit_group'))

await act(async () => btn('Exit all').click())
await settle()
await act(async () => btn('Yes, place these real exit orders').click())
await settle()
check('confirm places with the preview token', calls.some((c) => c.method === 'broker_place_exit_group' && c.params.confirm_token === 'tok-1'))
check('success notice, not "closed"', text().includes('1 exit order sent to Zerodha') && text().includes('fill only if the price is reached'))
check('dialog closed', !text().includes('Exit with REAL orders'))
await act(async () => root.unmount())
process.exit(ok ? 0 : 1)
