// Admin page (issue #101): on phones and tablets each table row stacks as label/value lines, so every
// data cell needs a label; newer audit events read as words, not raw keys; IPs have no "/32".
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { default: Admin } = await import('../src/pages/Admin.jsx')
const { act, createElement: h } = React

const ME = { id: 1, name: 'Murali', email: 'admin@test.example', role: 'admin', prefs: {} }
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
const RESULT = { auth_me: ME, admin_list_users: USERS, admin_audit_log: LOG, admin_list_blocked: BLOCKED }
globalThis.fetch = async (_url, opts) => {
  const { method, id } = JSON.parse(opts.body)
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

process.exit(ok ? 0 : 1)
