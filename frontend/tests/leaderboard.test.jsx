// Leaderboard (#125): loads signed out with the paper-trading label and the join call, monthly and
// quarterly with a period stepper, a podium then rows, empty bands folded into one line, your own
// row marked, and only nicknames (no emails, no rupee amounts).
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

const row = (rank, nickname, level = 5) => ({ rank, nickname, level, ratio: 3 - rank / 10, return_pct: 2.5, max_dd_pct: 0.5, trades: 6, win_rate: 100 })
const board = (period) => ({
  month: period, kind: period.includes('Q') ? 'quarter' : 'month', provisional: period === '2026-10' || period === '2026-Q4',
  months: ['2026-10', '2026-09'], quarters: ['2026-Q4', '2026-Q3'], min_level: 1, min_trades: 5,
  bands: [{ band: '1-3', levels: 'Rising', range: 'Levels 1-3', rows: period === '2026-10' ? [] : [1, 2, 3, 4].map((n) => row(n, `Rider${n}`, 2)) },
    { band: '4-6', levels: 'Levels 4-6', range: 'Levels 4-6', rows: [] }, { band: '7-10', levels: 'Levels 7-10', range: 'Levels 7-10', rows: [] }],
})
let me = null
const calls = []
globalThis.fetch = async (_url, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  const result = method === 'auth_me' ? me : method === 'leaderboard_get' ? board(params.month ?? '2026-10') : null
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result }) }
}

document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
let root = null
const render = () => act(async () => {
  root?.unmount()
  root = createRoot(document.getElementById('r'))
  root.render(h(MemoryRouter, null, h(AuthProvider, null, h(Leaderboard))))
})
const text = () => document.body.textContent
const btn = (t) => [...document.querySelectorAll('button')].find((b) => b.textContent === t || b.getAttribute('aria-label') === t)
const click = (t) => act(async () => btn(t).click())

await render()
await settle()
check('loads signed out', calls.some((c) => c.method === 'leaderboard_get'))
check('paper-trading label', text().includes('Paper trading, educational'))
check('join call to action links to sign-up', document.querySelector('a[href="/register"]')?.textContent === 'Join free and start at Level 1')
check('no native month dropdown any more', !document.querySelector('select'))
check('running month named and marked so far', document.querySelector('.lb-period')?.textContent === 'October 2026so far')
check('all-empty bands fold into one line, no empty cards', !document.querySelector('.lb-band')
  && text().includes('Nobody ranked yet this period: Rising · Levels 4-6 · Levels 7-10'))
check('Later is off on the newest period', btn('Later').disabled && !btn('Earlier').disabled)

await click('Earlier')
await settle()
check('Earlier asks for the previous month', calls.at(-1).params.month === '2026-09', calls.at(-1))
check('top three on a podium, the rest as rows', document.querySelectorAll('.lb-podium li').length === 3
  && document.querySelectorAll('.lb-rows li').length === 1 && document.querySelector('.lb-rows li').textContent.includes('Rider4'))
check('podium shows nickname, level and ratio', document.querySelector('.lb-place.p1')?.textContent.includes('Rider1')
  && document.querySelector('.lb-place.p1').textContent.includes('Level 2') && document.querySelector('.lb-place.p1 .lb-ratio').textContent.startsWith('2.90'))
check('empty bands listed as still open', text().includes('Still open: Levels 4-6 · Levels 7-10'))
check('no emails or rupee amounts', !text().includes('@') && !text().includes('₹'))

await click('Quarterly')
await settle()
check('Quarterly asks for the newest quarter', calls.at(-1).params.month === '2026-Q4', calls.at(-1))
check('quarter named', document.querySelector('.lb-period')?.textContent.startsWith('Q4 2026'))

me = { id: 1, name: 'R', email: 'a@x', role: 'user', level: 2, features: [], prefs: {}, nickname: 'Rider2', leaderboard_opt_in: true }
await render()
await settle()
check('no join prompt when signed in', !document.querySelector('a[href="/register"]'))
check('not ranked yet: says how to get on', text().includes('Close 5 paper trades this month to get ranked'))
await click('Earlier')
await settle()
check('your own place is marked', document.querySelector('.lb-place.me')?.textContent.includes('You'))
check('and the how-to note goes away once ranked', !text().includes('to get ranked'))

me = { ...me, nickname: 'Hidden', leaderboard_opt_in: false }
await render()
await settle()
check('opted out: says where to change it', text().includes("You've chosen not to appear here"))
process.exit(ok ? 0 : 1)
