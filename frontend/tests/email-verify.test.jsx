// Sign-up email check (#45): after "Request access" the page asks for the emailed code, and a
// sign-in by an unverified account (error -32005) swaps to the same code form.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 900 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { Login, Register } = await import('../src/pages/AuthPages.jsx')
const { AuthProvider } = await import('../src/auth.jsx')
const { act, createElement: h } = React

const calls = []
const ME = { id: 7, name: 'New User', email: 'new@test.example', role: 'user', status: 'active', features: [], prefs: {}, nickname: null }
let signedIn = false
globalThis.fetch = async (_url, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  const reply = (body) => ({ status: 200, json: async () => ({ jsonrpc: '2.0', id, ...body }) })
  if (method === 'auth_register') return reply({ result: { verify: true, email: params.email, message: 'We emailed a code' } })
  if (method === 'auth_verify_email') {
    if (params.code === '654321') {  // auto-approve on (#121): signed in straight away
      signedIn = true
      return reply({ result: { message: 'Welcome', signed_in: true, user: ME } })
    }
    return params.code === '123456' ? reply({ result: { message: 'Email confirmed. Waiting for approval.' } })
      : reply({ error: { code: -32000, message: 'That code is wrong' } })
  }
  if (method === 'auth_resend_code') return reply({ result: { message: 'A new code is on its way' } })
  if (method === 'auth_login') return reply({ error: { code: -32005, message: 'Confirm your email to continue' } })
  if (method === 'auth_me') return reply({ result: signedIn ? ME : null })
  return reply({ result: null })
}

const text = () => document.body.textContent
let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const tick = () => act(async () => { await new Promise((r) => setTimeout(r, 10)) })

async function render(page, path = '/') {
  document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
  const root = createRoot(document.getElementById('r'))
  await act(async () => root.render(h(MemoryRouter, { initialEntries: [path] }, h(AuthProvider, null, h(page)))))
  await tick()
  return root
}

function type(id, value) {
  const el = document.getElementById(id)
  const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  set.call(el, value)
  el.dispatchEvent(new window.Event('input', { bubbles: true }))
}

async function submit() {
  await act(async () => document.querySelector('form').dispatchEvent(new window.Event('submit', { bubbles: true, cancelable: true })))
  await tick()
}

// 1. Register -> code form -> wrong code -> resend -> right code -> confirmed.
let root = await render(Register)
await act(async () => { type('name', 'New User'); type('email', 'new@test.example'); type('new-password', 'plenty-long-passphrase') })
await submit()
check('no invite code: none sent', !('ref' in calls.find((c) => c.method === 'auth_register').params))
check('after sign-up the code form shows', !!document.getElementById('code') && text().includes('We emailed a code'), text())
await act(async () => type('code', '000000'))
await tick() // a full code confirms itself, no button press (#167)
check('a wrong code shows the error', text().includes('That code is wrong'))
const resend = [...document.querySelectorAll('button')].find((b) => b.textContent.includes('Send a new code'))
await act(async () => resend.click())
await tick()
check('resend asks for the same email', calls.at(-1).method === 'auth_resend_code' && calls.at(-1).params.email === 'new@test.example', calls.at(-1))
check('resend message shown', text().includes('A new code is on its way'))
await act(async () => type('code', '123 456'))
await tick() // a full code confirms itself, no button press (#167)
check('right code (pasted with a space) confirms itself', text().includes('Email confirmed'), text())
root.unmount()

// 2. Sign-in by an unverified account swaps to the code form.
root = await render(Login)
await act(async () => { type('email', 'New@Test.example '); type('password', 'plenty-long-passphrase') })
await submit()
check('unverified sign-in shows the code form', !!document.getElementById('code') && text().includes('Confirm your email'), text())
await act(async () => type('code', '123456'))
await tick() // a full code confirms itself, no button press (#167)
check('the code is checked for the typed email', calls.at(-1).method === 'auth_verify_email' && calls.at(-1).params.email === 'new@test.example', calls.at(-1))
root.unmount()

// 3. Auto-approved: the right code signs in and refreshes the session instead of "wait for approval".
root = await render(Register)
await act(async () => { type('name', 'New User'); type('email', 'new@test.example'); type('new-password', 'plenty-long-passphrase') })
await submit()
await act(async () => type('code', '654321'))
await tick() // a full code confirms itself, no button press (#167)
check('auto-approved: no waiting message', !text().includes('Waiting for approval') && !text().includes('Email confirmed'), text())
check('auto-approved: session refreshed', calls.at(-1).method === 'auth_me' && signedIn, calls.at(-1))
root.unmount()

// 4. Invite link (#126): the code from ?ref= goes with the sign-up, and survives a detour.
sessionStorage.clear()
root = await render(Register, '/register?ref=AbC123xy')
root.unmount()
root = await render(Register, '/register')
await act(async () => { type('name', 'Friend'); type('email', 'f@test.example'); type('new-password', 'plenty-long-passphrase') })
await submit()
check('invite code sent with the sign-up', calls.findLast((c) => c.method === 'auth_register').params.ref === 'AbC123xy', calls.at(-1))
root.unmount()

process.exit(ok ? 0 : 1)
