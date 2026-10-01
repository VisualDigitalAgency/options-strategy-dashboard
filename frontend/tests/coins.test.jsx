// Coins page (#47): balance, the earning rules, and a one-way exchange that sends whole coins only.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { default: Coins } = await import('../src/pages/Coins.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 30)) })

let balance = 120
const calls = []
globalThis.fetch = async (_url, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  if (method === 'coins_exchange') balance -= params.coins
  const result = {
    coins_status: { balance, rupees_per_coin: 100, levels: [{ level: 2, coins: 25 }],
      rules: [{ key: 'trade', label: 'Profitable short leg', coins: 2, max: 10, per: 'month', done: 3 }],
      history: [{ kind: 'xp', ref: '1', coins: 10, label: 'Every 250 XP', created_at: '2026-10-01T10:00:00Z' }] },
    coins_exchange: { exchanged: params?.coins, rupees: (params?.coins ?? 0) * 100, balance },
  }[method]
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result: result ?? null }) }
}

const root = createRoot(document.body.appendChild(document.createElement('div')))
await act(async () => root.render(h(MemoryRouter, null, h(Coins))))
await settle()
const text = () => document.body.textContent
check('balance and rules shown', text().includes('120') && text().includes('Profitable short leg') && text().includes('3 this month'))
const input = document.getElementById('cx-n')
const btn = () => [...document.querySelectorAll('button')].find((b) => b.textContent.includes('Exchange'))
const type = (v) => act(async () => { Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(input, v); input.dispatchEvent(new Event('input', { bubbles: true })) })
await type('500')
check('more than the balance: button off', btn().disabled)
await type('2.5')
check('fractions: button off', btn().disabled)
await type('20')
check('shows the rupee value', text().includes('₹2,000') && !btn().disabled)
await act(async () => btn().click())
await settle()
const sent = calls.find((c) => c.method === 'coins_exchange')
check('sends whole coins', sent?.params?.coins === 20, sent)
check('confirms the capital added', text().includes('Added ₹2,000'))

process.exit(ok ? 0 : 1)
