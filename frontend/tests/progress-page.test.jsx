// My progress (issue #126): XP bar against the next threshold, the gate checklist as returned,
// days left at the level, ledger reasons in plain English, the one-time level-up screen, and sharing
// (level and finished-course cards, % return off unless ticked, share links point at /c/<slug>).
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { default: Progress } = await import('../src/pages/Progress.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 20)) })

let prog = {
  level: 2, title: 'Apprentice', xp: 250, leveled_up: null,
  next: { level: 3, title: 'Seller', xp_needed: 400, xp_from: 100, days: 20, min_days: 60, ready: false,
    checks: [{ label: '400 XP', ok: false, value: 250 }, { label: '60 days at this level', ok: false, value: 20 },
      { label: 'Not available yet', ok: false, value: null }] },
}
const calls = []
globalThis.fetch = async (_url, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  const result = {
    auth_me: { id: 1, name: 'Asha', email: 'a@x', role: 'user', level: prog.level, features: [], prefs: {} },
    progress_get: prog,
    progress_history: [{ ts: '2026-09-30', points: 20, reason: 'trade_ok', ref: 'trade:1' },
      { ts: '2026-09-29', points: -30, reason: 'no_sl', ref: 'trade:2' },
      { ts: '2026-09-28', points: 50, reason: 'lesson', ref: 'lesson:what-is-an-option' }],
    lessons_list: [{ slug: 'a', level: 1 }, { slug: 'b', level: 1 }, { slug: 'c', level: 2 }],
    lesson_progress: [{ slug: 'a', passed_at: 'x' }, { slug: 'b', passed_at: 'x' }, { slug: 'c', passed_at: null }],
    card_create: { slug: 'Abc123xyz' },
    referral_get: { code: 'AbC123xy', url: 'https://t.example/register?ref=AbC123xy', joined: 2 },
    habits_get: { streak: { weeks: 3, this_week: false }, challenge: { week: '2026-W40', label: 'Pass a lesson quiz', target: 1, progress: 0, done: false, coins: 30 } },
  }[method]
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result: result ?? null }) }
}

document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
let root = null
const render = () => act(async () => {
  root?.unmount()
  root = createRoot(document.getElementById('r'))
  root.render(h(MemoryRouter, null, h(AuthProvider, null, h(Progress))))
})

localStorage.clear()
await render()
await settle()
const fill = document.querySelector('.progress-fill')
check('XP bar measures from this level\'s start', fill?.style.transform === 'scaleX(0.5)', fill?.style.transform)
check('XP shown against next threshold', document.body.textContent.includes('250 / 400 XP'))
const items = [...document.querySelectorAll('.checklist li')]
check('one checklist line per gate check', items.length === 3 && items[2].textContent.includes('Not available yet'))
check('days left at the level', document.body.textContent.includes('At least 40 more days'))
check('ledger reasons in plain English', document.body.textContent.includes('Trade closed with the stop-loss off')
  && document.body.textContent.includes('what is an option') && !document.body.textContent.includes('no_sl'))
check('negative XP marked', document.querySelector('.xp-list .neg')?.textContent === '-30')
check('first visit: no celebration, level recorded', !document.querySelector('.levelup') && localStorage.getItem('theta-seen-level') === '2')

// The nightly job moved the user up while away: celebrate once.
prog = { ...prog, level: 3, title: 'Seller' }
await render()
await settle()
check('level above the seen one: celebration shown', document.querySelector('.levelup')?.textContent.includes('Level 3 · Seller'))
await act(async () => document.querySelector('.levelup button').click())
await settle()
check('closing records the level', !document.querySelector('.levelup') && localStorage.getItem('theta-seen-level') === '3')
await render()
await settle()
check('not shown again', !document.querySelector('.levelup'))

check('invite link and joined count shown', document.querySelector('.invite-row input')?.value === 'https://t.example/register?ref=AbC123xy'
  && document.body.textContent.includes('2 joined through your link'))

// ---- sharing
const shareBtns = [...document.querySelectorAll('.share-list button')].map((b) => b.textContent)
check('share: current level and only finished courses', shareBtns.join('|') === 'Level 3 · Seller|Level 1 course complete', shareBtns)
await act(async () => document.querySelectorAll('.share-list button')[1].click())
const make = [...document.querySelectorAll('.share-modal button')].find((b) => b.textContent.includes('Make share link'))
await act(async () => make.click())
await settle()
const sent = calls.findLast((c) => c.method === 'card_create')
check('share: % return off unless ticked', sent.params.kind === 'course' && sent.params.ref === 1 && sent.params.show_return === false, sent)
const links = [...document.querySelectorAll('.share-links a')].map((a) => a.getAttribute('href'))
check('share: WhatsApp, X, Telegram and image links carry the card URL', links.length === 4
  && links.slice(0, 3).every((h) => h.includes(encodeURIComponent('/c/Abc123xyz'))) && links[3] === '/c/Abc123xyz.png', links)
check('share: preview image shown', document.querySelector('.share-preview')?.getAttribute('src') === '/c/Abc123xyz.png')

check('this week: streak and challenge (phase 1)', document.querySelector('.this-week')?.textContent.includes('3 weeks streak')
  && document.querySelector('.this-week').textContent.includes('Pass a lesson quiz') && document.querySelector('.this-week').textContent.includes('0/1'))
check('this week: keep-your-streak hint while this week is empty', document.querySelector('.this-week').textContent.includes('keep your streak'))
check('email nudges toggle, on by default', [...document.querySelectorAll('.check-row')].some((l) => l.textContent.includes('Email me the day before') && l.querySelector('input').checked))
process.exit(ok ? 0 : 1)
