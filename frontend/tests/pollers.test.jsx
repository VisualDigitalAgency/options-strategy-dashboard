// Does a provider re-arm its poll timer after it unmounts (sign-out while a request is in flight)?
// Also checks the normal case still re-arms while mounted.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register()
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { ScreenProvider } = await import('../src/screen.jsx')
const { SettingsProvider } = await import('../src/settings.jsx')
const { act, createElement: h } = React

let pending = []
globalThis.fetch = () => new Promise((res) => pending.push(() =>
  res({ status: 200, json: async () => ({ jsonrpc: '2.0', id: 1, result: { candidates: [], refreshing: false } }) })))

let armed = 0
const realSetTimeout = globalThis.setTimeout
globalThis.setTimeout = (fn, ms, ...a) => {
  if (ms >= 10000) armed++ // the poll delays are 10 s / 30 s / 60 s
  return realSetTimeout(fn, ms, ...a)
}
const settle = () => act(async () => { await new Promise((r) => realSetTimeout(r, 30)) })

let ok = true
for (const [name, P] of [['ScreenProvider', ScreenProvider], ['SettingsProvider', SettingsProvider]]) {
  // 1. mounted: answering the request re-arms the poll
  pending = []; armed = 0
  const a = createRoot(document.createElement('div'))
  await act(async () => a.render(h(P, null, null)))
  pending.splice(0).forEach((f) => f())
  await settle()
  const whileMounted = armed
  await act(async () => a.unmount())

  // 2. unmounted with a request in flight: answering it must not re-arm anything
  pending = []
  const b = createRoot(document.createElement('div'))
  await act(async () => b.render(h(P, null, null)))
  await act(async () => b.unmount())
  armed = 0
  pending.splice(0).forEach((f) => f())
  await settle()
  const afterUnmount = armed

  const pass = whileMounted >= 1 && afterUnmount === 0
  ok &&= pass
  console.log(`${pass ? 'PASS' : 'FAIL'} ${name}: polls armed while mounted=${whileMounted}, after unmount=${afterUnmount}`)
}
console.log(ok ? 'ALL PASS' : 'SOME FAILED')
process.exit(ok ? 0 : 1)
