// A new visitor opening the home page lands on the first public page (the builder), not the sign-in
// form. Only when the owner has every public page off does "/" go to sign-in.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter, useLocation } = await import('react-router-dom')
const { default: App } = await import('../src/App.jsx')
const { setBrand } = await import('../src/brand.jsx') // app_info loads once per page
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }

let pages = ['builder', 'learn', 'progress', 'leaderboard']
globalThis.fetch = async (_url, opts) => {
  const { method, id } = JSON.parse(opts.body)
  const result = { auth_me: null, app_info: { name: 'X', logo: null, reader_pages: pages }, reader_universe: [] }[method] ?? null
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}

let where = null
function Where() { where = useLocation().pathname; return null }
const visit = async () => {
  document.body.replaceChildren()
  const root = createRoot(document.body.appendChild(document.createElement('div')))
  await act(async () => root.render(h(MemoryRouter, { initialEntries: ['/'] }, h(App), h(Where))))
  await act(async () => { await new Promise((r) => setTimeout(r, 80)) })
  root.unmount()
}

await visit()
check('home opens the public builder, not sign-in', where === '/builder', where)
pages = ['learn']
setBrand({ name: 'X', reader_pages: pages })
await visit()
check('builder off: home opens the next public page', where === '/learn', where)
pages = []
setBrand({ name: 'X', reader_pages: pages })
await visit()
check('every public page off: home goes to sign-in', where === '/login', where)

process.exit(ok ? 0 : 1)
