// Learning path (issue #124): lesson list with passed marks, lesson body rendered from the markdown
// subset, quizzes unlocking in order (#161), quiz needs every answer before submitting, results shown, and signed-out visitors get the
// "Join free" call to action instead of the quiz.
import { GlobalRegistrator } from '@happy-dom/global-registrator'

GlobalRegistrator.register({ width: 375, height: 800 })
globalThis.IS_REACT_ACT_ENVIRONMENT = true

const React = await import('react')
const { createRoot } = await import('react-dom/client')
const { MemoryRouter, Route, Routes } = await import('react-router-dom')
const { AuthProvider } = await import('../src/auth.jsx')
const { Learn, Lesson } = await import('../src/pages/Learn.jsx')
const { act, createElement: h } = React

let ok = true
const check = (name, cond, got = '') => { ok &&= cond; console.log(`${cond ? 'PASS' : 'FAIL'} ${name}`, got) }
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 20)) })

const LIST = [
  { slug: 'what-is-an-option', title: 'What is an option?', level: 1, order: 1, summary: 'Calls and puts', minutes: 6, questions: 2 },
  { slug: 'stop-losses', title: 'Stop-losses', level: 2, order: 5, summary: 'Day 15 rule', minutes: 5, questions: 2 },
  { slug: 'short-strangle', title: 'The short strangle', level: 2, order: 6, summary: 'Two sells', minutes: 5, questions: 2 },
]
const LESSON = {
  slug: 'what-is-an-option', title: 'What is an option?', level: 1, order: 1, summary: 'Calls and puts', minutes: 6,
  body: 'Intro with **bold** and *italic* text.\n\n## Calls and puts\n\n- A **call** is the right to buy.\n- A put is the right to sell.\n\n1. First\n2. Second',
  questions: [{ q: 'Who receives the premium?', options: ['Buyer', 'Seller'] }, { q: 'Lot 500 × ₹6?', options: ['₹6', '₹3,000'] }],
  prev: null, next: 'stop-losses',
}
let lastL1 = false
let me = { id: 1, name: 'Asha', email: 'a@x', role: 'user', features: [], prefs: {} }
const calls = []
globalThis.fetch = async (_url, opts) => {
  const { method, id, params } = JSON.parse(opts.body)
  calls.push({ method, params })
  const result = {
    auth_me: me, lessons_list: LIST,
    lessons_get: params?.slug === 'short-strangle' ? { ...LESSON, slug: 'short-strangle', prev: 'stop-losses', next: null }
      : params?.slug === 'stop-losses' ? { ...LESSON, slug: 'stop-losses', level: 2, prev: 'what-is-an-option', next: 'short-strangle' }
        : { ...LESSON, last_of_level: lastL1 },
    lesson_progress: [{ slug: 'what-is-an-option', passed_at: '2026-09-30T10:00:00Z' }],
    lesson_submit_quiz: { score: 50, passed: false, first_pass: false, pass_pct: 80, retry_at: '2026-10-01T10:00:00Z',
      results: [{ correct: true, why: 'Seller gets it.' }, { correct: false, why: '₹6 × 500 = ₹3,000.' }] },
  }[method]
  return { status: 200, json: async () => ({ jsonrpc: '2.0', id, result: result ?? null }) }
}

document.body.replaceChildren(Object.assign(document.createElement('div'), { id: 'r' }))
let root = null
// A fresh root per page: MemoryRouter only reads initialEntries on mount.
const render = (path) => act(async () => {
  root?.unmount()
  root = createRoot(document.getElementById('r'))
  root.render(h(MemoryRouter, { initialEntries: [path] }, h(AuthProvider, null,
    h(Routes, null, h(Route, { path: '/learn', element: h(Learn) }), h(Route, { path: '/learn/:slug', element: h(Lesson) })))))
})

// ---- list
await render('/learn')
await settle()
const cards = [...document.querySelectorAll('.learn-card')]
check('list: one card per lesson, grouped by level', cards.length === 3 && document.querySelectorAll('.learn-level').length === 4)
check('list: passed lesson marked', cards[0].textContent.includes('Passed') && !cards[1].textContent.includes('Passed'))
check('list: progress summary', document.querySelector('.lede').textContent.includes('passed 1 of 3'))
check('list: next lesson open, the one after it locked (#161)', !cards[1].classList.contains('locked')
  && cards[2].classList.contains('locked') && cards[2].textContent.includes('Locked'))
check('list: Level 4 explained as practice', document.querySelector('#lv-4')?.textContent.includes('Level 4')
  && document.querySelector('.learn-practice')?.textContent.includes('delta 0.15'))

// ---- a locked lesson: readable, quiz replaced by the unlock message
await render('/learn/short-strangle')
await settle()
check('locked lesson: body readable, no quiz', !!document.querySelector('.md') && !document.querySelector('.quiz')
  && document.querySelector('.quiz-cta')?.textContent.includes('Quiz locked')
  && !!document.querySelector('.quiz-cta a[href="/learn/stop-losses"]'))

// ---- lesson body
await render('/learn/what-is-an-option')
await settle()
const md = document.querySelector('.md')
check('body: heading, bullet and numbered lists, bold', md.querySelector('h2')?.textContent === 'Calls and puts'
  && md.querySelectorAll('ul li').length === 2 && md.querySelectorAll('ol li').length === 2 && md.querySelectorAll('strong').length === 2 && md.querySelector('em')?.textContent === 'italic')
check('body: no raw markdown left', !md.textContent.includes('*') && !md.textContent.includes('## '))
check('title set', document.title.startsWith('What is an option?'))
check('disclaimer shown', document.body.textContent.includes('not investment advice'))

// ---- quiz
const submit = () => [...document.querySelectorAll('.quiz button')].find((b) => b.textContent.includes('Submit') || b.textContent.includes('Answer all'))
check('quiz: submit disabled until every question is answered', submit().disabled && submit().textContent.includes('Answer all 2'))
const radios = [...document.querySelectorAll('.quiz input[type=radio]')]
await act(async () => { radios[1].click(); radios[2].click() })
check('quiz: submit enabled once complete', !submit().disabled)
await act(async () => submit().click())
await settle()
const sent = calls.find((c) => c.method === 'lesson_submit_quiz')
check('quiz: answers sent by index', JSON.stringify(sent?.params) === JSON.stringify({ slug: 'what-is-an-option', answers: [1, 0] }), sent)
check('quiz: result and explanations shown', document.querySelector('.quiz-score.fail')?.textContent.includes('50%')
  && document.querySelectorAll('.quiz-why').length === 2)
check('quiz: next lesson link', !!document.querySelector('.lesson-nav a[href="/learn/stop-losses"]'))

// ---- signed out: call to action instead of the quiz
me = null
await render('/learn/what-is-an-option')
await settle()
check('signed out: lesson readable', !!document.querySelector('.md'))
check('signed out, Level 1: no quiz and no sign-up wall, a light note', !document.querySelector('.quiz')
  && !document.querySelector('.quiz-cta') && !!document.querySelector('.soft-join a[href="/register"]'))
lastL1 = true
await render('/learn/what-is-an-option')
await settle()
check('signed out, last Level 1 lesson: the join prompt', document.querySelector('.level-done h2')?.textContent === "You've read every Level 1 lesson"
  && !!document.querySelector('.level-done a[href="/register"]'))
await render('/learn/stop-losses')
await settle()
check('signed out, Level 2: quiz call to action', document.querySelector('.quiz-cta a[href="/register"]')?.textContent === 'Join free'
  && !document.querySelector('.level-done'))

process.exit(ok ? 0 : 1)
