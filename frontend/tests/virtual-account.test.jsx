// Virtual account page loads its data without a script error (the reset form no longer has a capital
// field since #169; a leftover call to its setter broke the page).
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { SettingsProvider } = await import('../src/settings.jsx')
const { default: VirtualAccount } = await import('../src/pages/VirtualAccount.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const acct = { starting_capital: 200000, created_at: '2026-10-01T10:00:00Z', sl_mode_default: 'auto', realized_pnl: 0,
  unrealized_pnl: 0, account_value: 200000, used_margin: 0, available_margin: 200000, return_pct: 0, open_positions: 0,
  open_orders: 0, blocked_margin: 0, charges: 0, margin_used_pct: 0, margin_status: 'ok' }
globalThis.fetch = async (_u, opts) => {
  const { method, id } = JSON.parse(opts.body)
  const result = { auth_me: { id: 1, name: 'A', email: 'a@x', role: 'user', level: 1, features: [], prefs: {}, nickname: 'a' },
    va_get_account: acct, va_get_orders: [], va_get_closed: [] }[method]
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result: result ?? null }) }
}
const root = createRoot(document.body.appendChild(document.createElement('div')))
await act(async () => root.render(h(MemoryRouter, null, h(AuthProvider, null, h(SettingsProvider, null, h(VirtualAccount))))))
await act(async () => { await new Promise((r) => setTimeout(r, 50)) })
const alert = document.querySelector('.alert[role=alert]')
check('loads with no error banner', !alert, alert?.textContent)
check('shows the capital the reset restarts with', document.body.textContent.includes('Restarts with your capital of ₹2,00,000'))
process.exit(ok ? 0 : 1)
