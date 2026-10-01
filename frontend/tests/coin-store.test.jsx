// Coin store (#175): packs and rules render, and Buy stays disabled until payments exist.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { default: CoinStore, PACKS } = await import('../src/pages/CoinStore.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
globalThis.fetch = async (_u, opts) => {
  const { id } = JSON.parse(opts.body)
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result: null }) }
}
const root = createRoot(document.body.appendChild(document.createElement('div')))
await act(async () => root.render(h(MemoryRouter, null, h(CoinStore))))
const packs = document.querySelectorAll('.store-pack')
check('one card per pack', packs.length === PACKS.length)
check('each pack shows coins, capital value and price', [...packs].every((p, i) => p.textContent.includes(`${PACKS[i].coins}`)
  && p.textContent.includes('of virtual capital') && p.textContent.includes(`₹${PACKS[i].price}`)))
check('Buy is disabled until payments exist', [...document.querySelectorAll('.store-pack button')].every((b) => b.disabled))
check('rules: no cash value, not profit', document.querySelector('.store-rules').textContent.includes('no cash value')
  && document.querySelector('.store-rules').textContent.includes('not to your profit'))
process.exit(ok ? 0 : 1)
