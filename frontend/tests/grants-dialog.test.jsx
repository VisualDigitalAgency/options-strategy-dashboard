// Owner's Grants view (#194): lists a user's capital grants, revoking asks for a reason, a coin
// exchange can't be revoked, and only the owner sees the button.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { default: Admin } = await import('../src/pages/Admin.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 30)) })

const owner = { id: 1, name: 'Murali', email: 'o@x', role: 'owner', features: ['manage_users', 'manage_roles'], prefs: {}, nickname: 'm' }
const sub = { ...owner, id: 3, name: 'Sub', role: 'sub_admin' }
let me = owner
const USERS = [
  { id: 1, ...owner, status: 'active', created_at: '2026-09-01T10:00:00Z', last_login_at: null, links: [] },
  { id: 2, name: 'Demo', email: 'd@x', role: 'user', status: 'active', created_at: '2026-09-02T10:00:00Z', last_login_at: null, links: [] },
]
let grants = [
  { id: 11, label: 'Pass every Level 1 lesson quiz', amount: 25000, at: '2026-10-01T10:00:00Z', revoked: false, revocable: true },
  { id: 12, label: 'Exchanged coins', amount: 1000, at: '2026-10-01T11:00:00Z', revoked: false, revocable: false },
]
const calls = []
globalThis.fetch = async (_u, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  if (method === 'admin_revoke_grant') grants = grants.map((g) => (g.id === params.grant_id ? { ...g, revoked: true, revocable: false } : g))
  const result = { auth_me: me, app_info: { name: 'X', logo: null }, admin_list_users: USERS, admin_audit_log: [], admin_list_blocked: [],
    admin_get_features: { roles: [], features: [], matrix: {} }, admin_get_settings: [], admin_user_grants: grants,
    admin_revoke_grant: { revoked: params?.grant_id } }[method]
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result: result ?? null }) }
}
const mount = async () => {
  document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
  await act(async () => createRoot(document.getElementById('r')).render(h(MemoryRouter, null, h(AuthProvider, null, h(Admin)))))
  await settle()
}
const btn = (t) => [...document.querySelectorAll('button')].find((b) => b.textContent.trim().endsWith(t))
const type = async (el, v) => act(async () => {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, v)
  el.dispatchEvent(new Event('input', { bubbles: true }))
})

await mount()
await act(async () => btn('Grants').click())
await settle()
check('the Grants button asks for that user\'s grants', calls.some((c) => c.method === 'admin_user_grants' && c.params.target_id === 2))
const dlg = () => document.querySelector('[role=dialog]')
check('the dialog lists both grants with amounts', dlg()?.textContent.includes('Pass every Level 1 lesson quiz') && dlg().textContent.includes('₹25,000')
  && dlg().textContent.includes('Exchanged coins'), dlg()?.textContent)
const revokes = [...dlg().querySelectorAll('button')].filter((b) => b.textContent === 'Revoke')
check('only the quiz grant can be revoked; the exchange says why not', revokes.length === 1 && dlg().textContent.includes("Can't be revoked"))

await act(async () => revokes[0].click())
const submit = () => [...dlg().querySelectorAll('button')].find((b) => b.textContent === 'Revoke grant')
check('a reason is asked for, and the warning is shown', !!dlg().querySelector('#grant-reason') && dlg().textContent.includes('never earn this reward again')
  && dlg().textContent.includes('square some off'))
check('the button is off with no reason', submit().disabled)
await type(dlg().querySelector('#grant-reason'), 'ab')
check('still off with 2 characters', submit().disabled)
await type(dlg().querySelector('#grant-reason'), 'invite abuse')
check('on once the reason is long enough', !submit().disabled)
await act(async () => submit().click())
await settle()
const rv = calls.find((c) => c.method === 'admin_revoke_grant')
check('revoke sends the user, the grant and the reason', rv?.params.target_id === 2 && rv.params.grant_id === 11 && rv.params.reason === 'invite abuse', rv?.params)
check('the list reloads and shows it revoked', dlg().textContent.includes('Revoked') && ![...dlg().querySelectorAll('button')].some((b) => b.textContent === 'Revoke'))

me = sub
await mount()
check('a sub-admin gets no Grants button', !btn('Grants'))

process.exit(ok ? 0 : 1)
