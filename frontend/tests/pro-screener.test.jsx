// Pro screener (issue #136): without Pro the screen provider never calls get_screened_candidates,
// and the upsell explains what Pro adds; with Pro it loads as before.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { ScreenProvider, useScreen } = await import('../src/screen.jsx')
const { default: ProUpsell } = await import('../src/pages/ProUpsell.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 20)) })

const calls = []
globalThis.fetch = async (_url, opts) => {
  const { method, id } = JSON.parse(opts.body)
  calls.push(method)
  const result = method === 'get_screened_candidates' ? { candidates: [], refreshing: false } : { name: 'X', logo: null }
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}

let seen
function Probe() { seen = useScreen(); return null }
const mount = async (tree) => {
  const root = createRoot(document.body.appendChild(document.createElement('div')))
  await act(async () => root.render(tree))
  await settle()
  return root
}

let root = await mount(h(ScreenProvider, { enabled: false }, h(Probe)))
check('free account: no screen request', !calls.includes('get_screened_candidates'), calls)
check('free account: not stuck loading', seen.loading === false && seen.data === null)
await act(async () => root.unmount())

root = await mount(h(ScreenProvider, { enabled: true }, h(Probe)))
check('Pro account: screen loads', calls.includes('get_screened_candidates') && seen.data?.candidates)
await act(async () => root.unmount())

root = await mount(h(MemoryRouter, null, h(ProUpsell)))
const text = document.body.textContent
check('upsell names Pro and what it adds', text.includes('Pro feature') && text.includes('Auto-trade'))
check('upsell says how to upgrade', text.includes('ask the admin'))
await act(async () => root.unmount())
process.exit(ok ? 0 : 1)
