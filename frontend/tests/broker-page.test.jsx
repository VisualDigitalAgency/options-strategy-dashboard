// Broker connect page: lists every supported broker with a logo, name and a disabled "Coming
// soon" connect action. Purely static — no RPC calls, no backend wiring yet.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 900 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { default: Broker } = await import('../src/pages/Broker.jsx')
const { BROKERS } = await import('../src/brokers.js')
const { act, createElement: h } = React

const text = () => document.body.textContent
let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }

document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
const root = createRoot(document.getElementById('r'))
await act(async () => root.render(h(Broker)))

check('every broker listed', BROKERS.every((b) => text().includes(b.name)), BROKERS.map((b) => b.name).join(','))
const cards = document.querySelectorAll('.broker-card')
check('one card per broker', cards.length === BROKERS.length, cards.length)
check('every card marked coming soon', [...cards].every((c) => c.querySelector('.broker-soon')?.textContent === 'Coming soon'))
check('every card has a logo image', [...cards].every((c) => c.querySelector('.broker-logo img')))
check('connect buttons are disabled (no backend wiring)', [...document.querySelectorAll('.broker-card button')].every((b) => b.disabled))
check('says trading stays virtual', text().includes("isn't wired up yet"))

await act(async () => root.unmount())

console.log(ok ? 'ALL PASS' : 'SOME FAILED')
process.exit(ok ? 0 : 1)
