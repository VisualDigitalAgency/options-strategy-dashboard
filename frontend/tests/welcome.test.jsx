// First-login onboarding (#121): nickname rules on the form, opt-in sent with it, server errors
// shown, and success refreshes the session.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { default: Welcome } = await import('../src/pages/Welcome.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 10)) })
const calls = []
let me = { id: 3, name: 'Asha Rao', email: 'a@x', role: 'user', features: [], prefs: {}, nickname: null }
globalThis.fetch = async (_url, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  const reply = (body) => ({ status: 200, json: async () => ({ jsonrpc: '2.0', id, ...body }) })
  if (method === 'profile_set') {
    if (params.nickname === 'taken') return reply({ error: { code: -32000, message: 'That nickname is taken' } })
    me = { ...me, nickname: params.nickname, leaderboard_opt_in: params.leaderboard_opt_in }
    return reply({ result: me })
  }
  return reply({ result: method === 'auth_me' ? me : null })
}
const type = (value) => {
  const el = document.querySelector('input[autocomplete=nickname]')
  Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set.call(el, value)
  el.dispatchEvent(new window.Event('input', { bubbles: true }))
}
const button = () => document.querySelector('form button')
const submit = () => act(async () => document.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })))

document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
await act(async () => createRoot(document.getElementById('r')).render(h(MemoryRouter, null, h(AuthProvider, null, h(Welcome)))))
await tick()
check('greets by first name and names Level 1', document.body.textContent.includes('Welcome, Asha') && document.body.textContent.includes('Level 1'))
check('button disabled until 3 characters', button().disabled)
const box = document.querySelector('input[type=checkbox]')
check('leaderboard opt-in starts ticked', box.checked)
await act(async () => type('taken'))
await submit()
await tick()
check('server error shown', document.querySelector('.form-error')?.textContent === 'That nickname is taken')
await act(async () => { type('ThetaAsha'); box.click() })
await submit()
await tick()
const sent = calls.filter((c) => c.method === 'profile_set').at(-1)
check('nickname and opt-out sent', sent.params.nickname === 'ThetaAsha' && sent.params.leaderboard_opt_in === false, sent)
check('session refreshed after saving', calls.at(-1).method === 'auth_me')
process.exit(ok ? 0 : 1)
