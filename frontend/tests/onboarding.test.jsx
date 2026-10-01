// New-user onboarding (#167): the Getting started checklist (live gate values, links, dismiss) and
// the nickname step (suggestion, live format check, back to a trade built before joining).
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter, Route, Routes, useLocation } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { default: GettingStarted } = await import('../src/components/GettingStarted.jsx')
const { default: Welcome } = await import('../src/pages/Welcome.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 30)) })

let me = { id: 1, name: 'Asha Rao', email: 'a@x', role: 'user', level: 1, features: [], prefs: {}, nickname: 'asha' }
const calls = []
globalThis.fetch = async (_url, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  const result = {
    auth_me: me, profile_set: { ok: true },
    progress_get: { level: 1, next: { level: 2, title: 'Apprentice', checks: [
      { label: '100 XP', ok: false, value: 40 }, { label: '60 days at this level', ok: false, value: 3 },
      { label: 'Pass every Level 1 lesson quiz', ok: true, value: '4/4' }, { label: 'Close 5 trades', ok: false, value: 2 }] } },
  }[method]
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result: result ?? null }) }
}

let where = null
function Where() { where = useLocation().pathname; return null }
document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
let root = null
const render = (el, path = '/') => act(async () => {
  root?.unmount()
  root = createRoot(document.getElementById('r'))
  root.render(h(MemoryRouter, { initialEntries: [path] }, h(AuthProvider, null, h(Routes, null,
    h(Route, { path: '/', element: el }), h(Route, { path: '*', element: h(Where) })))))
})

// 1. Checklist.
await render(h(GettingStarted))
await settle()
const card = () => document.querySelector('.getting-started')
check('shown at Level 1 with live counts', card()?.textContent.includes('Getting started · 2 of 5'), card()?.textContent)
check('done steps ticked, open ones link to where to do them', !!card().querySelector('a[href="/builder"]')
  && card().textContent.includes('Close 5 trades') && !card().querySelector('a[href="/learn"]'))
await act(async () => card().querySelector('button[aria-label="Hide getting started"]').click())
check('dismiss hides it', !card())
await render(h(GettingStarted))
await settle()
check('stays hidden at this level', !card())
localStorage.clear()
me = { ...me, level: 2 }
await render(h(GettingStarted))
await settle()
check('not shown from Level 2', !card())

// 2. Nickname step.
me = { ...me, level: 1, nickname: null }
localStorage.setItem('builder:draft', JSON.stringify({ symbol: 'SBIN', expiry: '2026-12-29', legs: [{}] }))
await render(h(Welcome))
await settle()
const input = () => document.querySelector('input[autocomplete=nickname]')
check('nickname suggested from the name', /^Asha\d{2}$/.test(input().value), input().value)
const type = (v) => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input(), v); input().dispatchEvent(new Event('input', { bubbles: true })) }
await act(async () => type('a b'))
const btn = () => document.querySelector('form button')
check('live format check, button off', document.body.textContent.includes('Only letters, digits and _') && btn().disabled)
await act(async () => type('ThetaAsha'))
check('valid: button on, offers the waiting trade', !btn().disabled && btn().textContent.includes('place my trade'))
await act(async () => btn().click())
await settle()
check('lands on the builder where the trade waits', where === '/builder', where)

process.exit(ok ? 0 : 1)
