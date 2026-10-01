// Monthly leaderboard (#125): loads signed out with the paper-trading label and the join call to
// action, shows only nicknames (no emails, no rupee amounts), marks the running month provisional,
// switches months, and shows Levels 1-3 the "reach Level 4" teaser instead of the join prompt.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { default: Leaderboard } = await import('../src/pages/Leaderboard.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 20)) })

const row = { rank: 1, nickname: 'ThetaAsha', level: 5, ratio: 2.5, return_pct: 2.5, max_dd_pct: 0, trades: 6, win_rate: 100 }
const board = (month, provisional) => ({
  month, provisional, months: ['2026-10', '2026-09'], min_level: 4, min_trades: 5,
  bands: [{ band: '4-6', levels: 'Levels 4-6', rows: provisional ? [] : [row] }, { band: '7-10', levels: 'Levels 7-10', rows: [] }],
})
let me = null
const calls = []
globalThis.fetch = async (_url, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  const result = method === 'auth_me' ? me
    : method === 'leaderboard_get' ? board(params.month ?? '2026-10', !params.month) : null
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}

document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
let root = null
const render = () => act(async () => {
  root?.unmount()
  root = createRoot(document.getElementById('r'))
  root.render(h(MemoryRouter, null, h(AuthProvider, null, h(Leaderboard))))
})

await render()
await settle()
const text = () => document.body.textContent
check('loads signed out', calls.some((c) => c.method === 'leaderboard_get'))
check('paper-trading label', text().includes('Paper trading, educational'))
check('join call to action links to sign-up', document.querySelector('a[href="/register"]')?.textContent === 'Join free and start at Level 1')
check('running month marked provisional', text().includes('so far: provisional'))

const select = document.querySelector('select[aria-label=Month]')
await act(async () => {
  Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set.call(select, '2026-09')
  select.dispatchEvent(new window.Event('change', { bubbles: true }))
})
await settle()
check('month switch asks for that month', calls.at(-1).params.month === '2026-09', calls.at(-1))
const cells = [...document.querySelectorAll('.leaderboard-table tbody td')].map((td) => td.textContent)
check('row shows nickname, level, ratio, return, drawdown, trades, win rate',
  JSON.stringify(cells) === JSON.stringify(['1', 'ThetaAsha', 'L5', '2.50', '2.50%', '0.00%', '6', '100.0%']), cells)
check('no emails or rupee amounts', !text().includes('@') && !text().includes('₹'))

me = { id: 1, name: 'Asha', email: 'a@x', role: 'user', level: 2, features: [], prefs: {}, nickname: 'ThetaAsha', leaderboard_opt_in: true }
await render()
await settle()
check('Level 1-3 teaser', text().includes('Reach Level 4 to compete'))
check('no join prompt when signed in', !document.querySelector('a[href="/register"]'))
process.exit(ok ? 0 : 1)
