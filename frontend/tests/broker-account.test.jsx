// Broker account page: mirrors VirtualAccount's statement/equity/ledger layout. When no broker
// is connected (or the connection expired) it falls back to the virtual account's own numbers via
// broker_account_summary's `source: "approx"`, clearly flagged; when connected it shows the real
// broker's figures and positions.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 900 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { default: BrokerAccount } = await import('../src/pages/BrokerAccount.jsx')
const { act, createElement: h } = React

let summary = null
let positions = []
let stops = []
globalThis.fetch = async (_url, opts) => {
  const { method, id } = JSON.parse(opts.body)
  let result = {}
  if (method === 'broker_account_summary') result = summary
  else if (method === 'broker_get_positions') result = positions
  else if (method === 'broker_stop_alerts') result = stops
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}

const text = () => document.body.textContent
let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }

async function render() {
  document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
  const root = createRoot(document.getElementById('r'))
  await act(async () => root.render(h(MemoryRouter, null, h(BrokerAccount))))
  await act(async () => { await new Promise((r) => setTimeout(r, 10)) })
  return root
}

// 1. No broker connected: approximate, virtual-account-derived figures
summary = {
  source: 'approx', broker: null, status: 'disconnected',
  available_margin_total: 850000, available_cash: 850000, used_margin: 150000,
  span: 120000, exposure: 30000, total_collateral: 0,
  collateral_liquid_used: 0, collateral_equity_used: 0, open_positions: 2, synced_at: null,
}
let root = await render()
check('approx: shows the available margin hero value', text().includes('8,50,000'))
check('approx: shows used margin', text().includes('1,50,000'))
check('approx: shows span and exposure tiles', text().includes('Span') && text().includes('Exposure'))
check('approx: shows the two collateral-used tiles', text().includes('Collateral (liquid funds)') && text().includes('Collateral (equity)'))
check('approx: flags the numbers as approximate', text().includes('showing approximate figures from your virtual account'))
check('approx: links to connect a broker', text().includes('Connect a broker'))
check('approx: points to Portfolio for virtual positions, not a real positions table', text().includes('Portfolio page') && !document.querySelector('table.legs.history'))
await act(async () => root.unmount())

// 2. Connection expired: still approximate, but a reconnect prompt instead
summary = { ...summary, status: 'expired' }
root = await render()
check('expired: prompts to reconnect', text().includes('expired') && text().includes('Reconnect'))
await act(async () => root.unmount())

// 3. Broker connected: real figures and a real positions table
summary = {
  source: 'broker', broker: 'zerodha', status: 'active',
  available_margin_total: 620000, available_cash: 500000, used_margin: 300000,
  span: 250000, exposure: 40000, total_collateral: 120000,
  collateral_liquid_used: 20000, collateral_equity_used: 80000, open_positions: 1,
  synced_at: '2026-09-27 10:15:00',
}
positions = [{ tradingsymbol: 'SUNPHARMA26O2200CE', quantity: -350, average_price: 30, last_price: 28, pnl: 700 }]
root = await render()
check('connected: shows real available margin (cash + collateral)', text().includes('6,20,000'))
check('connected: shows real collateral figure', text().includes('1,20,000'))
check('connected: shows the collateral-used breakdown by type', text().includes('20,000') && text().includes('80,000'))
check('connected: does not show the approximate notice', !text().includes('showing approximate figures'))
check('connected: renders the real positions table', !!document.querySelector('table.legs.history'))
check('connected: lists the real position', text().includes('SUNPHARMA26O2200CE'))
check('connected, no real legs: no stop-loss section', !text().includes('Stop losses at your broker'))
await act(async () => root.unmount())

// 4. Broker-side stops (#43): each real leg shows its day-15 alert state
const leg = { symbol: 'SUNPHARMA', expiry: '2026-10-27', side: 'CE', strike: 2200, qty: 350, limit_price: 30, sl_alert_error: null }
stops = [
  { ...leg, id: 1, status: 'complete', average_price: 30, sl_price: 30, sl_alert_status: 'enabled', sl_activates_on: '2026-10-10' },
  { ...leg, id: 2, status: 'complete', average_price: 12, sl_price: 12, sl_alert_status: 'pending', sl_activates_on: '2026-10-12' },
  { ...leg, id: 3, status: 'open', average_price: null, sl_price: null, sl_alert_status: 'pending', sl_activates_on: null },
  { ...leg, id: 4, status: 'complete', average_price: 20, sl_price: 20, sl_alert_status: 'triggered', sl_activates_on: '2026-10-01' },
  { ...leg, id: 5, status: 'complete', average_price: 15, sl_price: 15, sl_alert_status: 'skipped', sl_activates_on: '2026-10-01',
    sl_alert_error: 'Not available at Upstox: manage the stop yourself' },
]
root = await render()
check('stops: section shown', text().includes('Stop losses at your broker'))
check('stops: installed alert', text().includes('Installed at Zerodha') && text().includes('₹30.00'))
check('stops: not yet due shows its install date', text().includes('Installs on'))
check('stops: unfilled entry waits', text().includes('Waiting for the entry to fill'))
check('stops: triggered alert', text().includes('Triggered: buy-back order placed'))
check('stops: unsupported broker says to manage it yourself', text().includes('Not available at Upstox: manage the stop yourself'))
await act(async () => root.unmount())

console.log(ok ? 'ALL PASS' : 'SOME FAILED')
process.exit(ok ? 0 : 1)
