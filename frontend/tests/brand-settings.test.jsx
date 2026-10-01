// Branding (issue #133): the name and logo come from app_info and reach the wordmark, tab title and
// favicon; the owner's card saves the name, uploads only PNG/WebP to /brand/logo, and resets.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true
document.head.innerHTML = '<link rel="icon" type="image/svg+xml" href="/favicon.svg">'

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { Logo, useBrand, useTitle } = await import('../src/brand.jsx')
const { default: BrandSettings } = await import('../src/components/BrandSettings.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 20)) })

let info = { name: 'Nifty Dojo', logo: null }
const calls = []
globalThis.fetch = async (url, opts) => {
  if (url === '/brand/logo') {
    calls.push({ url, type: opts.headers['Content-Type'] })
    info = { ...info, logo: 'abc123' }
    return { status: 200, json: async () => ({ result: info }) }
  }
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  if (method === 'admin_set_brand_name') info = { ...info, name: params.name }
  if (method === 'admin_reset_logo') info = { ...info, logo: null }
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result: info }) }
}

function Header() {
  const { name } = useBrand()
  useTitle('Portfolio')
  return h('header', null, h(Logo), h('span', { className: 'wordmark' }, name))
}

const root = createRoot(document.body.appendChild(document.createElement('div')))
await act(async () => root.render(h(React.Fragment, null, h(Header), h(BrandSettings))))
await settle()
check('wordmark from app_info', document.querySelector('header .wordmark').textContent === 'Nifty Dojo')
check('tab title uses the name', document.title === 'Portfolio · Nifty Dojo', document.title)
check('built-in mark while no logo', !!document.querySelector('header svg.dial-mark'))
check('favicon stays the built-in one', document.querySelector('link[rel="icon"]').getAttribute('href') === '/favicon.svg')

const input = document.querySelector('#brand-name')
const type = async (v) => {
  const set = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set
  await act(async () => { set.call(input, v); input.dispatchEvent(new Event('input', { bubbles: true })) })
}
await type('Option Gym')
const btn = (t) => [...document.querySelectorAll('button')].find((b) => b.textContent.includes(t))
await act(async () => btn('Save name').click())
await settle()
check('name saved through admin_set_brand_name', calls.some((c) => c.method === 'admin_set_brand_name' && c.params.name === 'Option Gym'))
check('header renamed at once', document.querySelector('header .wordmark').textContent === 'Option Gym')

const file = document.querySelector('input[type=file]')
const pick = async (f) => {
  Object.defineProperty(file, 'files', { value: [f], configurable: true })
  await act(async () => file.dispatchEvent(new Event('change', { bubbles: true })))
  await settle()
}
await pick(new File(['<svg/>'], 'logo.svg', { type: 'image/svg+xml' }))
check('SVG refused before upload', document.querySelector('[role=alert]')?.textContent.includes('PNG or WebP')
  && !calls.some((c) => c.url === '/brand/logo'))
await pick(new File([new Uint8Array(10)], 'logo.webp', { type: 'image/webp' }))
check('WebP posted raw to /brand/logo', calls.some((c) => c.url === '/brand/logo' && c.type === 'image/webp'))
check('header shows the uploaded logo', document.querySelector('header img.brand-logo')?.getAttribute('src') === '/brand/logo.png?v=abc123')
check('favicon swapped to the upload', document.querySelector('link[rel="icon"]').getAttribute('href') === '/brand/favicon.png?v=abc123')
check('touch icon added', document.querySelector('link[rel="apple-touch-icon"]')?.getAttribute('href') === '/brand/touch.png?v=abc123')

await act(async () => btn('Use built-in logo').click())
await settle()
check('reset restores the dial and favicon', !!document.querySelector('header svg.dial-mark')
  && document.querySelector('link[rel="icon"]').getAttribute('href') === '/favicon.svg'
  && !document.querySelector('link[rel="apple-touch-icon"]'))

await act(async () => root.unmount())
process.exit(ok ? 0 : 1)
