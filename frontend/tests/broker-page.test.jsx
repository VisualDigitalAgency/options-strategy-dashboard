// Broker connect page: lists every supported broker with a logo and name. Which one(s) show a
// live "Connect" action (vs a disabled "Coming soon") is driven entirely by
// broker_account_summary's `connectable` list — the backend's single source of truth for who may
// connect what, phase 1 admin-only.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 900 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { default: Broker } = await import('../src/pages/Broker.jsx')
const { BROKERS } = await import('../src/brokers.js')
const { act, createElement: h } = React

let summary = { source: 'approx', status: 'disconnected', connectable: [], available_cash: 0 }
globalThis.fetch = async (_url, opts) => {
  const { method, id } = JSON.parse(opts.body)
  const result = method === 'broker_account_summary' ? summary : {}
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}

const text = () => document.body.textContent
let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }

async function render() {
  document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
  const root = createRoot(document.getElementById('r'))
  await act(async () => root.render(h(MemoryRouter, null, h(Broker))))
  await act(async () => { await new Promise((r) => setTimeout(r, 10)) })
  return root
}

// 1. Nothing connectable (non-admin, or admin not yet connected — same UI either way)
let root = await render()
check('every broker listed', BROKERS.every((b) => text().includes(b.name)), BROKERS.map((b) => b.name).join(','))
const cards = document.querySelectorAll('.broker-card')
check('one card per broker', cards.length === BROKERS.length, cards.length)
check('every card marked coming soon', [...cards].every((c) => c.querySelector('.broker-soon')?.textContent === 'Coming soon'))
check('every card has a logo image', [...cards].every((c) => c.querySelector('.broker-logo img')))
check('connect buttons are disabled', [...document.querySelectorAll('.broker-card button')].every((b) => b.disabled))
check('shows the rollout note, not a connect flow', text().includes("isn't switched on for your account yet"))
await act(async () => root.unmount())

// 2. Zerodha connectable (admin, not yet connected): only Zerodha's card goes live
summary = { source: 'approx', status: 'disconnected', connectable: ['zerodha'], available_cash: 0 }
root = await render()
check('connectable copy shown', text().includes('Zerodha is connectable now'))
const zerodhaCard = [...document.querySelectorAll('.broker-card')].find((c) => c.textContent.includes('Zerodha'))
check('Zerodha card has an enabled Connect button', !zerodhaCard.querySelector('button').disabled)
const otherCards = [...document.querySelectorAll('.broker-card')].filter((c) => c !== zerodhaCard)
check('every other broker still shows Coming soon', otherCards.every((c) => c.querySelector('.broker-soon')))
await act(async () => root.unmount())

// 3. Connected: banner shows real available cash
summary = { source: 'broker', status: 'active', connectable: ['zerodha'], available_cash: 250000 }
root = await render()
check('connected banner shows available cash', text().includes('Connected to Zerodha') && text().includes('2,50,000'))
await act(async () => root.unmount())

console.log(ok ? 'ALL PASS' : 'SOME FAILED')
process.exit(ok ? 0 : 1)
