// Sidebar navigation: on desktop the menu button shrinks it to an icon rail and back, remembered per
// browser; below 1024px it is a drawer that opens from the menu button and closes on Escape, the
// backdrop or a link. Only pages the account's features allow are listed.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1440, height: 900 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

let desktop = true
window.matchMedia = (q) => ({ matches: q.includes('min-width: 1024px') ? desktop : false, addEventListener() {}, removeEventListener() {} })

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { default: App } = await import('../src/App.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 30)) })
let features = []
let levelLocked = {}
globalThis.fetch = async (_url, opts) => {
  const { method, id } = JSON.parse(opts.body)
  const result = {
    auth_me: { id: 1, name: 'Asha Rao', email: 'a@x', role: 'user', level: 2, features, level_locked: levelLocked, prefs: {}, nickname: 'asha', status: 'active' },
    app_info: { name: 'Acme', logo: null },
  }[method]
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result: result ?? null }) }
}

document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
let root = null
const render = (path = '/learn') => act(async () => {
  root?.unmount()
  root = createRoot(document.getElementById('r'))
  root.render(h(MemoryRouter, { initialEntries: [path] }, h(App)))
})
const nav = () => document.querySelector('#sidebar')
const menu = () => document.querySelector('.menu-btn')
const labels = () => [...nav().querySelectorAll('a')].map((a) => a.textContent)

// Desktop.
localStorage.clear()
await render()
await settle()
check('desktop: sidebar expanded by default', nav() && !nav().classList.contains('shrunk') && menu().getAttribute('aria-label') === 'Shrink menu')
check('free account: screener marked Pro', labels()[0].includes('Pro'), labels())
// Locked items stay visible with what unlocks them (#165).
const cal = [...nav().querySelectorAll('a')].find((a) => a.textContent.includes('Calendar'))
check('locked calendar: badge, leads to Progress', cal?.textContent.includes('Unlocks at Level 3') && cal.getAttribute('href') === '/progress', cal?.outerHTML)
const brk = [...nav().querySelectorAll('a')].find((a) => a.textContent.includes('Broker'))
check('broker: invitation badge, still opens its preview', brk?.textContent.includes('By invitation') && brk.getAttribute('href') === '/broker')
check('coin store hidden while the owner keeps it off', !labels().some((l) => l.includes('Coin store')))
levelLocked = { coin_store: 4 }
await render()
await settle()
const store = [...nav().querySelectorAll('a')].find((a) => a.textContent.includes('Coin store'))
check('coin store on for the role, below Level 4: locked, leads to Progress (#175)',
  store?.textContent.includes('Unlocks at Level 4') && store.getAttribute('href') === '/progress', store?.outerHTML)
levelLocked = {}
await render()
await settle()
check('active page marked', nav().querySelector('a.active')?.textContent === 'Learn')
await render('/progress')
await settle()
check('on /progress only Progress is active, not the locked Calendar that links there', [...nav().querySelectorAll('a.active')].map((a) => a.textContent).join() === 'Progress',
  [...nav().querySelectorAll('a.active')].map((a) => a.textContent))
await render()
await settle()
await act(async () => menu().click())
check('menu button shrinks to an icon rail', nav().classList.contains('shrunk') && document.querySelector('.app-shell.shrunk') !== null)
check('rail keeps names for tooltips and screen readers', nav().querySelector('a[title="Learn"] .sb-label')?.textContent === 'Learn')
check('choice remembered', localStorage.getItem('theta-sidebar-shrunk') === '1')
await render()
await settle()
check('still shrunk after reload', nav().classList.contains('shrunk'))
await act(async () => document.querySelector('.sb-toggle').click())
check('footer button expands it again', !nav().classList.contains('shrunk') && localStorage.getItem('theta-sidebar-shrunk') === '0')

features = ['market_calendar', 'screener']
await render()
await settle()
check('feature unlocks its page, Pro tag gone', labels().includes('Calendar') && !labels()[0].includes('Pro'), labels())

// Phone / tablet.
desktop = false
await render()
await settle()
check('mobile: drawer closed, menu says Open', !nav().classList.contains('open') && menu().getAttribute('aria-label') === 'Open menu' && nav().hasAttribute('inert'))
check('mobile: no shrink toggle', !document.querySelector('.sb-toggle'))
await act(async () => menu().click())
check('menu opens the drawer and moves focus into it', nav().classList.contains('open') && nav().contains(document.activeElement)
  && !!document.querySelector('.sidebar-scrim'))
await act(async () => document.dispatchEvent(new window.KeyboardEvent('keydown', { key: 'Escape' })))
check('Escape closes it', !nav().classList.contains('open'))
await act(async () => menu().click())
await act(async () => document.querySelector('.sidebar-scrim').click())
check('backdrop closes it', !nav().classList.contains('open'))
await act(async () => menu().click())
await act(async () => [...nav().querySelectorAll('a')].find((a) => a.textContent === 'Portfolio').click())
check('choosing a page closes it', !nav().classList.contains('open'))

await act(async () => root.unmount())
process.exit(ok ? 0 : 1)
