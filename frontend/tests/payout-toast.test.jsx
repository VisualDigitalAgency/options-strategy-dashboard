// Payout toast (#192): shown once per reward, nothing on a browser's first visit, no replay.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 1280, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { default: PayoutToast } = await import('../src/components/PayoutToast.jsx')
const { groupItems } = await import('../src/payouts.js')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }

const g = groupItems([
  { kind: 'capital', label: 'Reach Level 2', amount: 25000 }, { kind: 'coins', label: 'Reach Level 2', amount: 25 },
  { kind: 'coins', label: 'Every 250 XP', amount: 10 }, { kind: 'coins', label: 'Every 250 XP', amount: 10 },
])
check('rupees and coins for one achievement share a line', g.length === 2 && g[0].rupees === 25000 && g[0].coins === 25, g)
check('repeats of the same label add up', g[1].coins === 20 && g[1].rupees === 0, g)

const asked = []
let reply = { now: '2026-10-02T10:00:00.000000Z', items: [] }
globalThis.fetch = async (_u, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  if (method === 'payout_news') asked.push(params.since ?? null)
  const result = { auth_me: { id: 7, name: 'A', email: 'a@x', role: 'user', level: 1, features: [], prefs: {}, nickname: 'a' },
    app_info: { name: 'X', logo: null }, payout_news: reply }[method]
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result: result ?? null }) }
}
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 60)) })
const mount = async () => {
  const root = createRoot(document.body.appendChild(document.createElement('div')))
  await act(async () => root.render(h(MemoryRouter, null, h(AuthProvider, null, h(PayoutToast)))))
  await settle()
  return root
}
const toast = () => document.querySelector('.payout-toast')

localStorage.clear()
let root = await mount()
check('first visit: asks without a clock', asked[0] === null, asked)
check('first visit: nothing shown', !toast())
check('the server clock is remembered', localStorage.getItem('theta-payout-clock:7') === '2026-10-02T10:00:00.000000Z')
root.unmount()

reply = { now: '2026-10-02T11:00:00.000000Z', items: [
  { kind: 'capital', label: 'Reach Level 2', amount: 25000, at: 'x' }, { kind: 'coins', label: 'Reach Level 2', amount: 25, at: 'x' }] }
root = await mount()
check('next visit: sends the saved clock', asked[1] === '2026-10-02T10:00:00.000000Z', asked)
check('a payout shows rupees, coins and what earned them', toast()?.textContent.includes('+₹25,000')
  && toast().textContent.includes('+25 coins') && toast().textContent.includes('Reach Level 2'), toast()?.textContent)
check('links to Earn capital', toast()?.querySelector('a')?.getAttribute('href') === '/capital')
check('announced politely to screen readers', toast()?.getAttribute('role') === 'status')
await act(async () => document.querySelector('.payout-x').click())
check('dismiss closes it', !toast())
check('clock advanced, so it is not shown twice', localStorage.getItem('theta-payout-clock:7') === '2026-10-02T11:00:00.000000Z')
root.unmount()

reply = { now: '2026-10-02T12:00:00.000000Z', items: Array.from({ length: 5 }, (_, i) => ({ kind: 'coins', label: `Task ${i}`, amount: 5, at: 'x' })) }
root = await mount()
check('many rewards: three lines and a count', toast()?.querySelectorAll('p').length === 4 && toast().textContent.includes('and 2 more'), toast()?.textContent)
root.unmount()

process.exit(ok ? 0 : 1)
