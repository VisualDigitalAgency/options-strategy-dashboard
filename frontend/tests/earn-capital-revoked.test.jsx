// A revoked grant (#194) reads as "Revoked" on the user's own Earn capital page, not as money earned.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { default: EarnCapital } = await import('../src/pages/EarnCapital.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const S = { capital: 200000, base: 200000, start: 200000, tasks: [], levels: [],
  grants: [{ task: 'l1_lessons', ref: '', amount: 25000, created_at: '2026-10-01 10:00:00', revoked: true, label: 'Pass every Level 1 lesson quiz' },
    { task: 'share_card', ref: 'level', amount: 25000, created_at: '2026-10-01 11:00:00', revoked: false, label: 'Share a level-up or course card' }] }
globalThis.fetch = async (_u, opts) => {
  const { method, id } = JSON.parse(opts.body)
  const result = { auth_me: { id: 1, name: 'A', email: 'a@x', role: 'user', level: 1, features: [], prefs: {}, nickname: 'a' },
    app_info: { name: 'X', logo: null }, capital_status: S }[method]
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result: result ?? null }) }
}
await act(async () => createRoot(document.body.appendChild(document.createElement('div'))).render(
  h(MemoryRouter, null, h(AuthProvider, null, h(EarnCapital)))))
await act(async () => { await new Promise((r) => setTimeout(r, 50)) })
const rows = [...document.querySelectorAll('.capital-grants li')]
check('both grants are listed', rows.length === 2, rows.length)
check('the revoked one says Revoked and shows no gain', rows[0].textContent.includes('Revoked') && !rows[0].textContent.includes('+₹'), rows[0].textContent)
check('the other still shows its gain', rows[1].textContent.includes('+₹25,000'), rows[1].textContent)
check('dates read as dates, in the format the server sends', !document.body.textContent.includes('Invalid Date') && rows[0].textContent.includes('Oct'), rows[0].textContent)
process.exit(ok ? 0 : 1)
