// Admin page (issue #101): on phones and tablets each table row stacks as label/value lines, so every
// data cell needs a label; newer audit events read as words, not raw keys; IPs have no "/32".
// Roles (issue #46): role column and editor, role filter, owner-only feature toggles.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { default: Admin } = await import('../src/pages/Admin.jsx')
const { act, createElement: h } = React

const ME = { id: 1, name: 'Murali', email: 'admin@test.example', role: 'owner', features: ['manage_users', 'manage_roles', 'live_trading', 'autotrade', 'market_calendar'], prefs: {} }
const USERS = [
  { id: 1, ...ME, status: 'active', created_at: '2026-09-01T10:00:00Z', last_login_at: '2026-09-29T10:00:00Z', links: [] },
  { id: 2, name: 'Demo', email: 'demo@test.example', role: 'user', status: 'active', created_at: '2026-09-02T10:00:00Z',
    last_login_at: null, links: [{ kind: 'network', user_id: 1, name: 'Murali', ip: '10.0.0.1' }] },
]
const LOG = [
  { id: 3, ts: '2026-09-29T09:46:00Z', action: 'broker_disconnected', ip: null, actor: 'admin@test.example', target: null },
  { id: 2, ts: '2026-09-28T04:23:00Z', action: 'password_reset_self', ip: '110.226.112.201', actor: null, target: 'demo@test.example' },
  { id: 1, ts: '2026-09-28T04:20:00Z', action: 'some_future_event', ip: '10.0.0.1', actor: null, target: null },
]
const BLOCKED = [{ id: 9, name: 'Late', email: 'late@test.example', created_at: '2026-09-01T10:00:00Z' }]
const FEATURES = {
  roles: ['sub_admin', 'beta', 'user'],
  features: [{ key: 'live_trading', label: 'Real orders' }, { key: 'autotrade', label: 'Auto-trade' }],
  matrix: { sub_admin: { live_trading: false, autotrade: true }, beta: { live_trading: false, autotrade: true }, user: { live_trading: false, autotrade: true } },
}
const calls = []
const SETTINGS = [{ key: 'auto_approve', value: true, label: 'New accounts can use the app as soon as their email is confirmed.' }]
const RESULT = { admin_get_overrides: [], admin_set_override: [{ feature: 'live_trading', mode: 'grant' }], admin_get_settings: SETTINGS, admin_set_setting: [{ ...SETTINGS[0], value: false }], admin_get_features: FEATURES, admin_set_role: { id: 2, role: 'beta' },
  admin_set_feature: { ...FEATURES, matrix: { ...FEATURES.matrix, beta: { live_trading: true, autotrade: true } } }, auth_me: ME, admin_list_users: USERS, admin_audit_log: LOG, admin_list_blocked: BLOCKED }
globalThis.fetch = async (_url, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result: RESULT[method] ?? {} }) }
}

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 10)) })
const tab = async (label) => {
  const b = [...document.querySelectorAll('[role=tab]')].find((t) => t.textContent.startsWith(label))
  await act(async () => b.click())
}
// Every cell except a row's title (first cell, and the event name on the log) and its actions has a label.
const unlabelled = (skip) => [...document.querySelectorAll('.admin-table tbody tr')].flatMap((tr) =>
  [...tr.children].filter((td, i) => !skip.includes(i) && !td.classList.contains('admin-act-cell') && !td.dataset.label)
    .map((td) => td.textContent))

document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
await act(async () => createRoot(document.getElementById('r')).render(h(MemoryRouter, null, h(AuthProvider, null, h(Admin)))))
await settle()

// Users
check('users: two rows', document.querySelectorAll('.admin-table tbody tr').length === 2)
check('users: every data cell labelled', unlabelled([0]).length === 0, unlabelled([0]))
check('users: dates are shown, not hidden', document.querySelectorAll('td[data-label="Signed up"]').length === 2)
const roleSel = document.querySelector('select[aria-label="Role for Demo"]')
check('users: owner gets a role editor for others, none for self', roleSel && !document.querySelector('select[aria-label="Role for Murali"]'))
check('users: owner can grant sub-admin, never owner', [...roleSel.options].map((o) => o.value).join() === 'sub_admin,beta,user', [...roleSel.options].map((o) => o.value))
await act(async () => {
  Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(roleSel, 'beta')
  roleSel.dispatchEvent(new Event('change', { bubbles: true }))
})
await settle()
check('users: changing the role calls admin_set_role', calls.some((c) => c.method === 'admin_set_role' && c.params.target_id === 2 && c.params.role === 'beta'))
const filterBtn = [...document.querySelectorAll('[aria-label="Filter by role"] button')].find((b) => b.textContent.startsWith('Owner'))
await act(async () => filterBtn.click())
check('users: role filter narrows the list', document.querySelectorAll('.admin-table tbody tr').length === 1)
await act(async () => [...document.querySelectorAll('[aria-label="Filter by role"] button')][0].click())
check('users: actions in their own cell', document.querySelectorAll('.admin-act-cell .admin-actions').length === 2)

// Blocked sign-ups
await tab('Blocked')
check('blocked: every data cell labelled', unlabelled([0]).length === 0, unlabelled([0]))

// Activity
await tab('Activity')
const text = document.querySelector('.admin-log').textContent
check('log: every data cell labelled', unlabelled([0, 1]).length === 0, unlabelled([0, 1]))
check('log: broker events have labels', text.includes('Broker disconnected') && !text.includes('broker_disconnected'))
check('log: self password reset has a label', text.includes('Reset own password') && !text.includes('password_reset_self'))
check('log: unknown events read as words', text.includes('Some future event') && !text.includes('some_future_event'))
check('log: IP shown as sent', text.includes('110.226.112.201'))

// Roles & features (owner only)
await tab('Roles')
const sw = document.querySelector('[role=switch][aria-label="live trading for Beta"]')
check('features: a switch per role and feature', document.querySelectorAll('.feature-matrix [role=switch]:not([aria-label="auto approve"])').length === 6 && sw?.getAttribute('aria-checked') === 'false')
await act(async () => sw.click())
await settle()
check('features: toggling saves and shows the new state', calls.some((c) => c.method === 'admin_set_feature' && c.params.role === 'beta' && c.params.enabled === true)
  && document.querySelector('[role=switch][aria-label="live trading for Beta"]').getAttribute('aria-checked') === 'true')

const auto = document.querySelector('[role=switch][aria-label="auto approve"]')
check('settings: auto-approve switch shown on', auto?.getAttribute('aria-checked') === 'true')
await act(async () => auto.click())
await settle()
check('settings: switching it off saves', calls.some((c) => c.method === 'admin_set_setting' && c.params.key === 'auto_approve' && c.params.value === false)
  && document.querySelector('[role=switch][aria-label="auto approve"]').getAttribute('aria-checked') === 'false')

// Per-user overrides (#123)
const acct = document.querySelector('select[aria-label="Account to override"]')
check('overrides: account picker is a styled field, so it never sizes to its longest option',
  acct.id === 'ov-target' && acct.closest('.field')?.querySelector('label[for=ov-target]') !== null)
check('overrides: owner not offered as a target', ![...acct.options].some((o) => o.textContent.includes('admin@test.example')))
await act(async () => {
  Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(acct, '2')
  acct.dispatchEvent(new Event('change', { bubbles: true }))
})
await settle()
const grant = [...document.querySelectorAll('[aria-label="Override live trading"] button')].find((b) => b.textContent === 'Grant')
await act(async () => grant.click())
await settle()
check('overrides: grant saves and shows', calls.some((c) => c.method === 'admin_set_override' && c.params.target_id === 2 && c.params.mode === 'grant')
  && grant.getAttribute('aria-pressed') === 'true')
check('overrides: no repeated "Override" label on each row', !document.querySelector('.overrides td[data-label]'))
check('overrides: a plain grant is permanent (no months sent)', calls.filter((c) => c.method === 'admin_set_override').at(-1).params.months === undefined)
const dur = document.querySelector('#ov-months')
await act(async () => {
  Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value').set.call(dur, '3')
  dur.dispatchEvent(new Event('change', { bubbles: true }))
})
await act(async () => grant.click())
await settle()
check('overrides: "Grant for 3 months" sends months (phase 3)', calls.filter((c) => c.method === 'admin_set_override').at(-1).params.months === 3)

process.exit(ok ? 0 : 1)
