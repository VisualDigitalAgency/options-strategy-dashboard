// BrokerCard: the connectable broker (Zerodha) shows live connection state and the right
// action button; every other broker still shows the static "Coming soon" preview regardless.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 900 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { default: BrokerCard } = await import('../src/components/BrokerCard.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }

const zerodha = { id: 'zerodha', name: 'Zerodha', logo: '/z.webp' }
document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
const root = createRoot(document.getElementById('r'))

// Non-connectable (every broker except Zerodha in phase 1): always "Coming soon", disabled button.
await act(async () => root.render(h(BrokerCard, { b: { id: 'upstox', name: 'Upstox', logo: '/u.webp' }, connectable: false })))
check('non-connectable shows Coming soon', document.querySelector('.broker-soon')?.textContent === 'Coming soon')
check('non-connectable Connect button is disabled', document.querySelector('button').disabled)

// Connectable, not yet connected: "Connect" button, enabled.
await act(async () => root.render(h(BrokerCard, { b: zerodha, connectable: true, connection: { status: 'disconnected' } })))
check('disconnected shows Not connected chip', document.querySelector('.broker-status-disconnected')?.textContent === 'Not connected')
check('disconnected shows an enabled Connect button', document.querySelector('button').textContent.includes('Connect') && !document.querySelector('button').disabled)

// Connected: Disconnect button, connected note shown.
await act(async () => root.render(h(BrokerCard, { b: zerodha, connectable: true, connection: { status: 'active' } })))
check('active shows Connected chip', document.querySelector('.broker-status-active')?.textContent === 'Connected')
check('active shows a Disconnect button', document.querySelector('button').textContent.includes('Disconnect'))
check('active shows the real-account-linked note', !!document.querySelector('.broker-connected-note'))

// Expired: Reconnect button, distinct chip.
await act(async () => root.render(h(BrokerCard, { b: zerodha, connectable: true, connection: { status: 'expired' } })))
check('expired shows Reconnect needed chip', document.querySelector('.broker-status-expired')?.textContent === 'Reconnect needed')
check('expired shows a Reconnect button', document.querySelector('button').textContent.includes('Reconnect'))

await act(async () => root.unmount())

console.log(ok ? 'ALL PASS' : 'SOME FAILED')
process.exit(ok ? 0 : 1)
