// Portfolio page: virtual/real account toggle (issue #52). Defaults to whichever account is
// actually connected, disables "Real" when no broker is linked, and switches the whole page's
// data source (not just a label) when clicked.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 900 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { default: Portfolio } = await import('../src/pages/Portfolio.jsx')
const { SettingsProvider } = await import('../src/settings.jsx')
const { act, createElement: h } = React

const VIRTUAL_DATA = {
  account: { unrealized_pnl: 0, realized_pnl: 0, used_margin: 100000, available_margin: 900000, return_pct: 0 },
  groups: [], totals: { theta: 0, delta: 0 }, market_open: true, updated_at: '2026-09-27 10:00:00',
}
let brokerSummary = { source: 'approx', status: 'disconnected', available_margin_total: 850000, available_cash: 850000,
  used_margin: 150000, span: 120000, exposure: 30000, total_collateral: 0, collateral_liquid_used: 0,
  collateral_equity_used: 0, open_positions: 0, synced_at: null }
let brokerPositions = []
let brokerStops = []

globalThis.fetch = async (_url, opts) => {
  const { method, id } = JSON.parse(opts.body)
  let result = {}
  if (method === 'va_get_positions' || method === 'va_refresh_positions') result = VIRTUAL_DATA
  else if (method === 'va_get_open_orders') result = []
  else if (method === 'broker_account_summary') result = brokerSummary
  else if (method === 'broker_get_positions') result = brokerPositions
  else if (method === 'broker_stop_alerts') result = brokerStops
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}

const text = () => document.body.textContent
let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }

async function render() {
  document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
  const root = createRoot(document.getElementById('r'))
  await act(async () => root.render(h(MemoryRouter, null, h(SettingsProvider, null, h(Portfolio)))))
  await act(async () => { await new Promise((r) => setTimeout(r, 15)) })
  return root
}

const realBtn = () => [...document.querySelectorAll('.account-mode-switch button')].find((b) => b.textContent === 'Real')
const virtualBtn = () => [...document.querySelectorAll('.account-mode-switch button')].find((b) => b.textContent === 'Virtual')

// 1. No broker connected: defaults to Virtual, Real toggle disabled
let root = await render()
check('defaults to virtual view', text().includes('No open positions'))
check('Real toggle is disabled', realBtn().disabled)
check('Virtual toggle is active', virtualBtn().className.includes('active'))
await act(async () => root.unmount())

// 2. Broker connected: defaults to Real, shows broker positions
brokerSummary = { ...brokerSummary, source: 'broker', status: 'active', open_positions: 1 }
brokerPositions = [{ tradingsymbol: 'SUNPHARMA26O2200CE', quantity: -350, average_price: 30, last_price: 28, pnl: 700 }]
root = await render()
check('defaults to real view when a broker is connected', realBtn().className.includes('active'))
check('Real toggle now enabled', !realBtn().disabled)
check('shows the real position', text().includes('SUNPHARMA26O2200CE'))
check('does not show the virtual empty-state', !text().includes('No open positions'))

// 3. Switching to Virtual shows the virtual (empty) view instead
await act(async () => virtualBtn().click())
await act(async () => { await new Promise((r) => setTimeout(r, 15)) })
check('switching to Virtual shows the virtual view', text().includes('No open positions'))
check('switching to Virtual hides the real position', !text().includes('SUNPHARMA26O2200CE'))
check('Virtual toggle is now active', virtualBtn().className.includes('active'))

// 4. Switching back to Real restores the broker view
await act(async () => realBtn().click())
await act(async () => { await new Promise((r) => setTimeout(r, 15)) })
check('switching back to Real restores the broker position', text().includes('SUNPHARMA26O2200CE'))
await act(async () => root.unmount())

console.log(ok ? 'ALL PASS' : 'SOME FAILED')
process.exit(ok ? 0 : 1)
